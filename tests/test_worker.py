import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import config, loop
from fei.approval import ApprovalService
from fei.delegation import plan
from fei.task_state import TaskState, current_task
from fei.tools.delegate import delegate_task
from fei.tools import schemas

class WorkerTests(unittest.TestCase):
    def call(self, name, args, ident):
        return {"id":ident,"function":{"name":name,"arguments":json.dumps(args)}}
    def test_worker_handoff_has_real_diff_and_verification(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config,'WORKDIR',Path(folder)):
            source=Path(folder)/'a.py';source.write_text('value = 1\n')
            contract={"task":"change value to 2", "files":["a.py"], "verification_argv":["{python}","-m","unittest"]}
            child_finish={"summary":"fixed","completed":["changed"],"remaining":[],"verification_ids":["check"],"status":"verified"}
            parent_finish={**child_finish,"verification_ids":["check"]}
            calls=[("",[self.call('delegate_task',contract,'delegate')],None),
                   ("",[self.call('read_file',{'path':'a.py'},'read')],None),
                   ("",[self.call('edit_file',{'path':'a.py','old_text':'value = 1','new_text':'value = 2'},'edit'),self.call('write_file',{'path':'outside.py','content':'bad'},'outside'),self.call('run_bash',{'command':'echo bad'},'shell')],None),
                   ("",[self.call('run_check',{},'check')],None),
                   ("",[self.call('finish_task',child_finish,'done')],None),
                   ("",[self.call('finish_task',parent_finish,'parent-done')],None),
                   ('Review completed; parent verification still required',[],None),
                   ('No independent verification',[],None),
                   ('No independent verification',[],None)]
            record={}
            process=types.SimpleNamespace(returncode=0,stdout='tests passed',stderr='')
            with patch.object(loop,'_chat',side_effect=calls),patch('fei.delegation.run_command',return_value=process) as command:
                loop.run_task(None,[{'role':'user','content':'fix'}],permission_policy=ApprovalService(mode='full'),task_record=record)
            self.assertEqual(source.read_text(),'value = 2\n')
            self.assertFalse((Path(folder)/'outside.py').exists())
            command.assert_called_once()
            child=record['subagents'][0]
            self.assertEqual(child['status'],'completed_verified')
            self.assertIn('+value = 2',child['handoff']['changes'][0]['diff'])
            self.assertEqual(child['handoff']['verification'][0]['id'],'check')
            self.assertEqual(record['status'],'incomplete')
            self.assertTrue(any(c['name']=='finish_task' and c['status']=='error' for c in record['tool_calls']))
            self.assertNotIn('run_check',{t['function']['name'] for t in schemas()})

    def test_invalid_scopes_and_commands(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'WORKDIR',Path(folder)):
            for files in [['../bad.py'],['.env'],['.git/config'],['.'],['a.py','a.py']]:
                with self.assertRaises(ValueError):plan('task',files,['echo','ok'])
            with patch.dict('os.environ',{'FEI_ALLOW_DANGEROUS':'0'}):
                with self.assertRaises(ValueError):plan('task',['a.py'],['shutdown'])

    def test_read_mode_rejects_worker(self):
        from fei.tools import REGISTRY
        service=ApprovalService(mode='read')
        self.assertFalse(service.authorize(REGISTRY['delegate_task'],{},'contract'))

    def test_contract_must_match_approval(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'WORKDIR',Path(folder)):
            state=TaskState();state.execute_callback=lambda value:'unexpected execution'
            state.delegation_plan=plan('task',['a.py'],['echo','ok'])
            token=current_task.set(state)
            try:
                with self.assertRaises(RuntimeError):delegate_task('task',['b.py'],['echo','ok'])
            finally:current_task.reset(token)

    def test_failed_check_cannot_claim_verified(self):
        from fei.hooks import HookEvent
        state=TaskState()
        state.observe(HookEvent('after_tool',{'id':'check','name':'run_check','arguments':{},'error':'failed','result':'failed'}))
        with self.assertRaises(ValueError):state.finish('done',[],[],['check'],'verified')

if __name__=='__main__':unittest.main()
