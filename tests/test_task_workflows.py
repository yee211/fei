"""Task-level regression: scripted model decisions, real files and test processes."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import cli, config, loop, session
from fei.approval import ApprovalService
from fei.status import render_status

class TaskWorkflowTests(unittest.TestCase):
    def call(self,name,args,ident):
        return {"id":ident,"function":{"name":name,"arguments":json.dumps(args)}}
    def fixture(self,root):
        (root/'pricing.py').write_text("def subtotal(items):\n    return sum(i['price'] for i in items)\n")
        (root/'checkout.py').write_text("from pricing import subtotal\ndef total(items, discount=0):\n    return subtotal(items)*(1-discount)\n")
        (root/'test_solution.py').write_text("import unittest\nfrom checkout import total\nclass Checks(unittest.TestCase):\n    def test_total(self):\n        self.assertEqual(total([{'price':10,'quantity':3}],10),27)\nif __name__=='__main__':unittest.main()\n")
        argv=['{python}','-B','test_solution.py']
        (root/'.fei.json').write_text(json.dumps({'version':1,'checks':{'test':{'category':'test','argv':argv}}}))
        return argv
    def finish(self,ident):
        return {'summary':'fixed','completed':['fixed'],'remaining':[],'verification_ids':[ident],'status':'verified'}
    def child_replies(self,argv):
        return [('',[self.call('read_file',{'path':'pricing.py'},'read')],None),
          ('',[self.call('edit_file',{'path':'pricing.py','old_text':"i['price']",'new_text':"i['price']*i['quantity']"},'edit1')],None),
          ('',[self.call('write_file',{'path':'test_solution.py','content':'bad'},'escape')],None),
          ('',[self.call('run_check',{},'failed-check')],None),
          ('',[self.call('edit_file',{'path':'checkout.py','old_text':'1-discount','new_text':'1-discount/100'},'edit2')],None),
          ('',[self.call('run_check',{},'passed-check')],None),
          ('',[self.call('finish_task',self.finish('passed-check'),'child-done')],None)]
    def test_cross_file_worker_recovers_failed_real_check_and_parent_verifies(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'WORKDIR',Path(folder)):
            root=Path(folder);argv=self.fixture(root)
            protected={name:(root/name).read_bytes() for name in ['test_solution.py','.fei.json']}
            contract={'task':'fix subtotal and discount','files':['pricing.py','checkout.py'],'verification_argv':argv}
            replies=[('',[self.call('delegate_task',contract,'worker')],None)]+self.child_replies(argv)+[
              ('',[self.call('review_worker',{'subtask_id':'worker-id','decision':'accept','reason':'Reviewed both diffs and fixed child checks'},'review')],None),
              ('',[self.call('verify_project',{},'parent-check')],None),
              ('',[self.call('finish_task',self.finish('parent-check'),'parent-done')],None)]
            record={}
            with patch.object(loop,'_chat',side_effect=replies), patch('fei.delegation.uuid4',return_value=type('ID', (), {'hex':'worker-id'})()):
                loop.run_task(None,[{'role':'user','content':'fix pricing'}],permission_policy=ApprovalService(mode='full'),task_record=record)
            self.assertEqual(record['status'],'completed_verified')
            child=record['subagents'][0]
            checks=[c['status'] for c in child['tool_calls'] if c['name']=='run_check']
            self.assertEqual(checks,['error','ok'])
            self.assertEqual(record['completion']['verification_ids'],['parent-check'])
            self.assertEqual(len(child['handoff']['changes']),2)
            self.assertTrue(all((root/name).read_bytes()==content for name,content in protected.items()))
            self.assertFalse(any(c['name'] in {'edit_file','write_file'} for c in record['tool_calls']))
            status=render_status([],record,'full')
            self.assertIn('parent-check',status)
            self.assertIn('pricing.py',status)
            self.assertIn('worker',status)
    def test_interrupt_restore_keeps_plan_requires_new_parent_evidence(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'WORKDIR',Path(folder)),patch.object(session,'SESSIONS_DIR',Path(folder)/'sessions'):
            root=Path(folder);self.fixture(root)
            saved=session.Session();messages=[{'role':'user','content':'fix and verify'}]
            steps=[{'id':'fix','title':'修复','status':'completed'},{'id':'verify','title':'验证','status':'pending'}]
            replies=[('',[self.call('update_plan',{'steps':steps},'plan')],None),('',[self.call('edit_file',{'path':'pricing.py','old_text':"i['price']",'new_text':"i['price']*i['quantity']"},'edit1'),self.call('edit_file',{'path':'checkout.py','old_text':'1-discount','new_text':'1-discount/100'},'edit2')],None),KeyboardInterrupt()]
            record={}
            with patch.object(loop,'_chat',side_effect=replies), patch('fei.delegation.uuid4',return_value=type('ID', (), {'hex':'worker-id'})()):
                with self.assertRaises(KeyboardInterrupt):loop.run_task(None,messages,task_record=record,permission_policy=ApprovalService(mode='full'),checkpoint=saved.save_state)
            saved.append_task(record)
            restored=session.Session.load_state(saved.path)
            self.assertEqual(session.Session.load_latest_task(saved.path)['status'],'interrupted')
            self.assertEqual(session.Session.load_latest_task(saved.state_path)['status'],'interrupted')
            self.assertIn('已中断',render_status(restored,record,'auto'))
            self.assertIn('待办：验证',render_status(restored,record,'auto'))
            restored.append({'role':'user','content':'继续'})
            steps[1]['status']='completed'
            replies=[('',[self.call('verify_project',{},'resume-check')],None),('',[self.call('update_plan',{'steps':steps},'plan2')],None),('',[self.call('finish_task',self.finish('resume-check'),'done')],None)]
            resumed={}
            with patch.object(loop,'_chat',side_effect=replies), patch('fei.delegation.uuid4',return_value=type('ID', (), {'hex':'worker-id'})()):loop.run_task(None,restored,permission_policy=ApprovalService(mode='full'),task_record=resumed)
            self.assertEqual(resumed['status'],'completed_verified')
            self.assertEqual(resumed['completion']['verification_ids'],['resume-check'])
    def test_status_command_never_calls_model_and_clear_resets(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(session,'SESSIONS_DIR',Path(folder)),patch.object(cli.llm,'make_client',return_value=None),patch.object(cli,'run_task') as run,patch('builtins.input',side_effect=['/status','/clear','/status','/exit']),patch('sys.stdout',new_callable=io.StringIO) as output:
            cli._interactive_main()
            run.assert_not_called()
            self.assertEqual(output.getvalue().count('暂无当前会话任务记录'),2)

if __name__=='__main__':unittest.main()
