import copy
import unittest
from fei.task_state import TaskState
from fei.skills import sync_skills, restore_skills
from fei.state_messages import compact_system_messages
from fei.runtime_limits import TaskBudget
from fei.status import render_status

class CachePrefixTests(unittest.TestCase):
    def test_plan_and_skills_updates_append_without_mutating_prefix(self):
        messages=[{'role':'system','content':'fixed'},{'role':'user','content':'task'}]
        state=TaskState()
        state.update_plan([{'id':'a','title':'work','status':'pending'}])
        state.sync_plan(messages)
        sync_skills(messages,{'test':{'instructions':'old'}})
        prefix=copy.deepcopy(messages)
        state.update_plan([{'id':'a','title':'work','status':'completed'}])
        state.sync_plan(messages)
        sync_skills(messages,{'test':{'instructions':'new'}})
        self.assertEqual(messages[:len(prefix)],prefix)
        length=len(messages)
        state.sync_plan(messages);sync_skills(messages,{'test':{'instructions':'new'}})
        self.assertEqual(len(messages),length)
        restored=TaskState();restored.restore_plan(messages)
        self.assertEqual(restored.plan[0]['status'],'completed')
        self.assertEqual(restore_skills(messages)['test']['instructions'],'new')
        compacted=compact_system_messages(messages)
        self.assertEqual(len(compacted),3)
        self.assertEqual(restore_skills(compacted)['test']['instructions'],'new')
    def test_clear_plan_does_not_restore_old_steps(self):
        messages=[];state=TaskState()
        state.update_plan([{'id':'a','title':'work','status':'pending'}]);state.sync_plan(messages)
        state.update_plan([]);state.sync_plan(messages)
        restored=TaskState();restored.restore_plan(messages)
        self.assertEqual(restored.plan,[])
    def test_cache_metrics_distinguish_unknown_from_zero(self):
        budget=TaskBudget()
        budget.record({'prompt_tokens':100,'completion_tokens':10},0,'')
        self.assertIsNone(budget.snapshot()['cache_hit_rate'])
        budget.record({'prompt_tokens':100,'completion_tokens':10,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':20},0,'')
        budget.record({'prompt_tokens':100,'completion_tokens':10,'prompt_tokens_details':{'cached_tokens':20}},0,'')
        snapshot=budget.snapshot()
        self.assertEqual(snapshot['cache_hit_rate'],0.5)
        self.assertEqual(snapshot['cache_reported_requests'],2)
        text=render_status([],{'goal':'task','status':'returned','budget':snapshot,'tool_calls':[]},'auto')
        self.assertIn('50.0%',text)
    def test_snapshot_survives_cleanup_of_interrupted_batch(self):
        messages=[{'role':'user','content':'task'},{'role':'assistant','tool_calls':[{'id':'pending'}]}]
        state=TaskState();state.update_plan([{'id':'a','title':'work','status':'pending'}]);state.sync_plan(messages)
        self.assertTrue(state.is_plan_message(messages[1]))
        del messages[2:]
        restored=TaskState();restored.restore_plan(messages)
        self.assertEqual(len(restored.plan),1)

if __name__=='__main__':unittest.main()
