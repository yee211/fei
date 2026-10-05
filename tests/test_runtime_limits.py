import json
import types
import unittest
from unittest.mock import Mock, patch
from fei import config, context, loop
from fei.hooks import HookRegistry
from fei.runtime_limits import LoopWatch, TaskBudget, BudgetExceeded, current_budget
from fei.tools.base import Tool

class RuntimeLimitsTests(unittest.TestCase):
    def call(self,name,args,ident):
        return {"id":ident,"function":{"name":name,"arguments":json.dumps(args)}}
    def test_repeat_executes_only_three_and_keeps_pairs(self):
        record={};messages=[{'role':'user','content':'inspect'}]
        tool=Tool('probe','test',{'type':'object','properties':{}},Mock(return_value='same'))
        responses=[('',[self.call('probe',{},str(i))],None) for i in range(6)]
        with patch.dict(loop.REGISTRY,{'probe':tool}),patch.object(loop,'_chat',side_effect=responses) as chat:
            loop.run_task(None,messages,confirm=lambda *args:True,task_record=record)
        self.assertEqual(record['status'],'loop_detected')
        self.assertEqual(chat.call_count,3)
        self.assertEqual(tool.handler.call_count,3)
        context.complete_blocks(messages)
        self.assertIsNone(current_budget.get())
    def test_remaining_batch_is_not_executed_after_stop(self):
        tool=Tool('probe','test',{},Mock(return_value='same'))
        calls=[self.call('probe',{},str(i)) for i in range(5)]
        messages=[];record={}
        with patch.dict(loop.REGISTRY,{'probe':tool}),patch.object(loop,'_chat',return_value=('',calls,None)):
            loop.run_task(None,messages,confirm=lambda *args:True,task_record=record)
        self.assertEqual(tool.handler.call_count,3)
        self.assertEqual(len(record['tool_calls']),5)
        self.assertEqual(record['tool_calls'][-1]['status'],'error')
        context.complete_blocks(messages)
    def test_tool_count_limit_completes_pending_pairs(self):
        tool=Tool('probe','test',{},Mock(return_value='same'))
        calls=[self.call('probe',{'x':i},str(i)) for i in range(5)]
        record={};messages=[]
        with patch.object(config,'MAX_TASK_TOOL_CALLS',2),patch.dict(loop.REGISTRY,{'probe':tool}),patch.object(loop,'_chat',return_value=('',calls,None)):
            loop.run_task(None,messages,confirm=lambda *args:True,task_record=record)
        self.assertEqual(record['status'],'budget_exceeded')
        self.assertEqual(record['budget']['tool_calls'],2)
        self.assertEqual(len(record['tool_calls']),5)
        context.complete_blocks(messages)

    def test_changed_result_and_edit_allow_real_recovery(self):
        watch=LoopWatch()
        for value in range(5):self.assertIsNone(watch.observe('read_file',{'path':'a.py'},value,None))
        self.assertIsNone(watch.observe('run_check',{},'failed','failed'))
        self.assertIsNone(watch.observe('run_check',{},'failed','failed'))
        self.assertIsNone(watch.observe('edit_file',{'path':'a.py'},'change_id=real',None))
        self.assertIsNone(watch.observe('run_check',{},'failed','failed'))
    def test_varying_errors_still_stop(self):
        watch=LoopWatch()
        with patch.object(config,'CONSECUTIVE_ERROR_LIMIT',3):
            self.assertIsNone(watch.observe('missing',{'x':1},'one','err'))
            self.assertIsNone(watch.observe('missing',{'x':2},'two','err'))
            self.assertIsNotNone(watch.observe('missing',{'x':3},'three','err'))
    def test_request_budget_shared_with_child(self):
        call=self.call('explore_code',{'question':'inspect'},'child')
        responses=[('',[call],None),('',[self.call('get_environment',{},'env')],None)]
        record={}
        with patch.object(config,'MAX_MODEL_REQUESTS',2),patch.object(loop,'_chat',side_effect=responses) as chat:
            loop.run_task(None,[],task_record=record)
        self.assertEqual(chat.call_count,2)
        self.assertEqual(record['status'],'budget_exceeded')
        self.assertEqual(record['budget']['requests'],2)
        self.assertEqual(record['subagents'][0]['status'],'budget_exceeded')
    def test_token_budget_fails_before_request_and_records_usage(self):
        budget=TaskBudget()
        budget.record(types.SimpleNamespace(total_tokens=90),0,'')
        with patch.object(config,'MAX_TASK_TOKENS',100):
            with self.assertRaises(BudgetExceeded):budget.before_request(9,2)
        self.assertEqual(budget.requests,0)
        budget.record(None,5,'a')
        self.assertEqual(budget.tokens,96)
        self.assertTrue(budget.estimated)
    def test_usage_calibration_avoids_premature_compaction(self):
        tool=Tool('probe','test',{},lambda:'x'*4000)
        responses=[('',[self.call('probe',{},'read')],types.SimpleNamespace(prompt_tokens=100,total_tokens=110)),('done',[],types.SimpleNamespace(prompt_tokens=1000,total_tokens=1010))]
        with patch.dict(loop.REGISTRY,{'probe':tool}),patch.object(loop,'schemas',return_value=[]),patch.object(config,'COMPACT_TOKENS',8000),patch.object(loop,'_chat',side_effect=responses),patch.object(loop,'compact_running') as compact:
            self.assertEqual(loop.run_task(None,[{'role':'user','content':'x'*5000}],confirm=lambda *args:True),'done')
            compact.assert_not_called()

    def test_summary_uses_same_request_budget(self):
        messages=[{'role':'user','content':'goal'}]+[{'role':'assistant','content':'x'*3000} for _ in range(5)]
        budget=TaskBudget();budget.requests=2
        token=current_budget.set(budget)
        client=Mock()
        try:
            with patch.object(config,'MAX_MODEL_REQUESTS',2):
                with self.assertRaises(BudgetExceeded):context.compact_running(client,messages)
            client.chat.completions.create.assert_not_called()
        finally:current_budget.reset(token)

if __name__=='__main__':unittest.main()
