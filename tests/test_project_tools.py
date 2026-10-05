import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from fei import config,loop
from fei.discovery import list_directory,find_files,matches
from fei.hooks import HookEvent
from fei.project_verify import load_plan,plan_description,verify_project
from fei.task_state import TaskState,current_task
from fei.permission import permission_request
from fei.tools import REGISTRY

class ProjectToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        patcher=patch.object(config,'WORKDIR',self.root);patcher.start();self.addCleanup(patcher.stop)
    def config(self,checks=None):
        value={'version':1,'checks':checks or {'test':{'category':'test','argv':['{python}','-B','-m','unittest'],'timeout':10}}}
        (self.root/'.fei.json').write_text(json.dumps(value),encoding='utf-8')
    def call(self,name,args,id='c'):
        return {'id':id,'function':{'name':name,'arguments':json.dumps(args)}}
    def test_directory_ignores_and_depth(self):
        for name in ['src/deep','node_modules','__pycache__','.git']: (self.root/name).mkdir(parents=True)
        for name in ['main.py','src/a.py','src/deep/b.py','node_modules/no.py','.secret']:(self.root/name).write_text('x')
        output=list_directory(depth=1)
        self.assertIn('main.py',output);self.assertNotIn('src/a.py',output);self.assertNotIn('node_modules',output);self.assertNotIn('.secret',output)
        self.assertIn('src/a.py',list_directory(depth=2))
        self.assertIn('node_modules/',list_directory(include_ignored=True))
        self.assertIn('.secret',list_directory(include_hidden=True))
    def test_glob_zero_or_many_directories(self):
        for path in ['tests/a.py','tests/unit/a.py','tests/unit/deep/a.py']:self.assertTrue(matches(path,'tests/**/*.py'))
        self.assertFalse(matches('other/a.py','tests/**/*.py'))
        self.assertTrue(matches('root.py','**/*.py'))
        self.assertTrue(matches('src/config.json','*config*'))
    def test_find_and_output_limit(self):
        (self.root/'tests').mkdir();(self.root/'tests/a.py').write_text('x');(self.root/'tests/b.py').write_text('x')
        output=find_files('tests/**/*.py',limit=1)
        self.assertIn('tests/a.py',output);self.assertIn('truncated',output);self.assertNotIn('tests/b.py',output)
        with self.assertRaises(ValueError):list_directory('missing')
    def test_scan_budget(self):
        with patch('fei.discovery.time.monotonic',side_effect=[0,6]):self.assertIn('truncated',list_directory())
    def test_symlinks_not_followed(self):
        target=self.root/'real';target.mkdir();(target/'a.py').write_text('x')
        link=self.root/'link'
        try:link.symlink_to(target,target_is_directory=True)
        except OSError:self.skipTest('Symlink creation not available')
        self.assertNotIn('link/',list_directory())
    def test_directory_read_permissions(self):
        self.assertIsNone(permission_request(REGISTRY['list_directory'],{}))
        self.assertIsNotNone(permission_request(REGISTRY['find_files'],{'pattern':'*.py','path':'..'}))
    def test_config_missing_unknown_and_schema(self):
        with self.assertRaises(ValueError):load_plan()
        self.config()
        with self.assertRaises(ValueError):load_plan(['unknown'])
        with self.assertRaises(ValueError):load_plan(['test','test'])
        self.config({'bad':{'category':'test','argv':['python'],'extra':True}})
        with self.assertRaises(ValueError):load_plan()
    def test_exact_approved_argv_and_multiple_results(self):
        self.config({'test':{'category':'test','argv':['{python}','-m','unittest']},'lint':{'category':'lint','argv':['ruff','check','.']}})
        state=TaskState();token=current_task.set(state)
        try:
            approval=permission_request(REGISTRY['verify_project'],{})
            self.assertIn('ruff',approval);self.assertIn('unittest',approval)
            responses=[types.SimpleNamespace(returncode=0,stdout='tests passed',stderr=''),types.SimpleNamespace(returncode=1,stdout='lint failed',stderr='')]
            with patch('fei.project_verify.run_command',side_effect=responses) as run:
                result=verify_project()
            self.assertFalse(result.success);self.assertEqual([c['status'] for c in result.checks],['passed','failed'])
            self.assertEqual(run.call_args_list[1].args[0],['ruff','check','.'])
        finally:current_task.reset(token)
    def test_config_mutation_after_approval_never_executes(self):
        self.config();state=TaskState();token=current_task.set(state)
        try:
            permission_request(REGISTRY['verify_project'],{})
            self.config({'other':{'category':'build','argv':['echo','changed']}})
            with patch('fei.project_verify.run_command') as run,self.assertRaises(RuntimeError):verify_project()
            run.assert_not_called()
        finally:current_task.reset(token)
    def test_denial_no_process(self):
        self.config();messages=[]
        with patch.object(loop,'_chat',side_effect=[('',[self.call('verify_project',{})],None),('declined',[],None)]),patch('fei.project_verify.run_command') as run:
            loop.run_task(None,messages,confirm=lambda *args:False)
            run.assert_not_called()
    def test_configured_verification_can_finish(self):
        self.config()
        finish={'summary':'checked','completed':['tests'],'remaining':[],'verification_ids':['verify'],'status':'verified'}
        responses=[('',[self.call('verify_project',{},'verify')],None),('',[self.call('finish_task',finish,'finish')],None)]
        record={}
        with patch.object(loop,'_chat',side_effect=responses),patch('fei.project_verify.run_command',return_value=types.SimpleNamespace(returncode=0,stdout='OK',stderr='')):
            loop.run_task(None,[],confirm=lambda *args:True,task_record=record)
        self.assertEqual(record['status'],'completed_verified')
        self.assertEqual(record['tool_calls'][0]['checks'][0]['exit_code'],0)
    def test_failed_project_checks_cannot_claim_verified(self):
        self.config();state=TaskState()
        state.observe(HookEvent('after_tool',{'id':'v','name':'verify_project','arguments':{},'error':'failed','result':'failed','output_path':None}))
        with self.assertRaises(ValueError):state.finish('done',[],[],['v'],'verified')
    def test_configured_project_rejects_generic_command_evidence(self):
        self.config();state=TaskState()
        state.observe(HookEvent('after_tool',{'id':'v','name':'run_bash','arguments':{'purpose':'verification'},'error':None,'result':'echo ok','output_path':None}))
        with self.assertRaises(ValueError):state.finish('done',[],[],['v'],'verified')
    def test_execution_rechecks_dangerous_argv(self):
        self.config();state=TaskState();token=current_task.set(state)
        try:
            permission_request(REGISTRY['verify_project'],{})
            state.verification_plan['checks'][0]['argv']=['shutdown']
            with patch('fei.project_verify.run_command') as run,self.assertRaises(RuntimeError):verify_project()
            run.assert_not_called()
        finally:current_task.reset(token)
    def test_new_rules_read_then_edit_same_batch_requires_review(self):
        folder=self.root/'src';folder.mkdir()
        (folder/'AGENTS.md').write_text('Preserve API signatures')
        (folder/'a.py').write_text('old')
        calls=[self.call('read_file',{'path':'src/a.py'},'read'),self.call('edit_file',{'path':'src/a.py','old_text':'old','new_text':'new'},'edit')]
        with patch.object(loop,'_chat',side_effect=[('',calls,None),('review rules',[],None)]):
            loop.run_task(None,[{'role':'user','content':'fix'}],confirm=lambda *args:True)
        self.assertEqual((folder/'a.py').read_text(),'old')

    def test_guard_invalid_config_and_dangerous_command(self):
        self.config({'test':{'category':'test','argv':['shutdown']}})
        self.assertIsNotNone(REGISTRY['verify_project'].guard({}))

if __name__=='__main__':unittest.main()
