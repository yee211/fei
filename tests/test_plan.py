import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from fei import context, loop, session
from fei.task_state import TaskState

class PlanTests(unittest.TestCase):
    def steps(self, status="in_progress"):
        return [{"id": "fix", "title": "修复问题", "status": status}]

    def call(self, name, args, call_id="plan"):
        return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    def test_validation_is_atomic(self):
        state = TaskState()
        steps = self.steps()
        state.update_plan(steps)
        steps[0]["title"] = "changed"
        self.assertEqual(state.plan[0]["title"], "修复问题")
        for invalid in [self.steps() * 2, self.steps() + [{"id":"other","title":"other","status":"in_progress"}], self.steps("bad"), [{"id":"fix","title":"","status":"pending"}]]:
            with self.assertRaises(ValueError):
                state.update_plan(invalid)
            self.assertEqual(state.plan, self.steps())
        state.update_plan([])
        self.assertEqual(state.plan, [])

    def test_finish_requires_explanation_and_real_evidence(self):
        state = TaskState()
        state.update_plan(self.steps())
        for status, remaining in [("verified", []), ("unverified", []), ("incomplete", [])]:
            with self.assertRaises(ValueError):
                state.finish("done", [], remaining, [], status)
        state.finish("blocked", [], ["修复尚未完成"], [], "incomplete")
        state.update_plan(self.steps("completed"))
        with self.assertRaises(ValueError):
            state.finish("done", ["fixed"], [], [], "verified")
        state.finish("done", ["fixed"], [], [], "unverified")
        self.assertTrue(state.plan_closed)

    def test_interruption_session_restore_and_continue(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)):
            saved = session.Session()
            messages = [{"role":"user", "content":"fix and verify"}]
            responses = [("", [self.call("update_plan", {"steps":self.steps()})], None), KeyboardInterrupt()]
            with patch.object(loop, "_chat", side_effect=responses):
                with self.assertRaises(KeyboardInterrupt):
                    loop.run_task(None, messages, checkpoint=saved.save_state)
            restored = session.Session.load_state(saved.path)
            state = TaskState()
            state.restore_plan(restored)
            self.assertEqual(state.plan, self.steps())
            self.assertFalse(state.evidence)
            restored.append({"role":"user", "content":"继续"})
            finish = {"summary":"fixed", "completed":["fixed"], "remaining":[], "verification_ids":[], "status":"unverified"}
            responses = [("", [self.call("update_plan", {"steps":self.steps("completed")}, "p2")], None), ("", [self.call("finish_task", finish, "done")], None)]
            record = {}
            with patch.object(loop, "_chat", side_effect=responses):
                loop.run_task(None, restored, task_record=record, checkpoint=saved.save_state)
            self.assertEqual(record["status"], "completed_unverified")
            fresh = TaskState()
            fresh.restore_plan(session.Session.load_state(saved.path))
            self.assertEqual(fresh.plan, [])

    def test_compression_keeps_plan_exactly_once(self):
        state = TaskState()
        state.update_plan(self.steps())
        messages = [{"role":"user", "content":"goal"}]
        for i in range(5):
            messages.extend([{"role":"assistant", "content":"x"*2000}, {"role":"user", "content":"history" if i < 4 else "goal"}])
        state.sync_plan(messages)
        original = next(m for m in messages if state.is_plan_message(m))
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="待完成修复"))])
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=Mock(return_value=response))))
        updated = context.compact_running(client, messages)
        state.sync_plan(updated)
        snapshots = [m for m in updated if state.is_plan_message(m)]
        self.assertEqual(snapshots, [original])
        restored = TaskState()
        restored.restore_plan(updated)
        self.assertEqual(restored.plan, self.steps())

if __name__ == "__main__":
    unittest.main()
