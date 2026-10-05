import unittest
from unittest.mock import patch
from fei import loop, context
from fei.tools import REGISTRY
from fei.hooks import HookRegistry, HookRejected

class CompactToolTests(unittest.TestCase):
    def call(self, name="compact_context", arguments="{}", id="compact"):
        return {"id": id, "function": {"name": name, "arguments": arguments}}
    def history(self):
        return [{"role": "user", "content": "original goal"}] + [{"role": "assistant", "content": "old " + "x" * 1000} for _ in range(4)]
    def test_registered_and_no_history_skips_without_permission(self):
        messages = [{"role": "user", "content": "goal"}]
        with patch.object(loop, "_chat", side_effect=[("", [self.call()], None), ("done", [], None)]):
            loop.run_task(None, messages)
        self.assertIn("跳过", messages[-2]["content"])
        self.assertIn("compact_context", REGISTRY)

    def test_batch_finishes_before_compaction(self):
        messages = self.history()
        hooks, seen = HookRegistry(), []
        hooks.register("after_compact", lambda event: seen.append(event.data["source"]))
        def compact(client, active):
            context.complete_blocks(active)
            self.assertEqual(active[-1]["tool_call_id"], "read")
            return [active[0], {"role": "assistant", "content": "[任务备忘] work"}, *active[-3:]]
        calls = [self.call(), self.call("read_file", '{"path":"missing"}', "read")]
        with patch.object(loop, "_chat", side_effect=[("", calls, None), ("done", [], None)]), patch.object(loop, "compact_running", side_effect=compact):
            loop.run_task(None, messages, hooks=hooks)
        self.assertEqual(seen, ["tool"])
        self.assertIn("成功", messages[-2]["content"])
        context.complete_blocks(messages)

    def test_summary_failure_reported_and_task_continues(self):
        messages = self.history()
        with patch.object(loop, "_chat", side_effect=[("", [self.call()], None), ("done", [], None)]), patch.object(loop, "compact_running", side_effect=RuntimeError("summary unavailable")):
            self.assertEqual(loop.run_task(None, messages), "done")
        self.assertIn("summary unavailable", messages[-2]["content"])
        self.assertIn("old", messages[1]["content"])

    def test_hook_rejection_does_not_run_summarizer(self):
        hooks = HookRegistry()
        hooks.register("before_compact", lambda event: "disabled")
        messages = self.history()
        with patch.object(loop, "_chat", side_effect=[("", [self.call()], None), ("done", [], None)]), patch.object(loop, "compact_running") as compact:
            loop.run_task(None, messages, hooks=hooks)
            compact.assert_not_called()
        self.assertIn("disabled", messages[-2]["content"])

    def test_duplicate_requests_compress_once(self):
        messages = self.history()
        with patch.object(loop, "_chat", side_effect=[("", [self.call(id="a"), self.call(id="b")], None), ("done", [], None)]), patch.object(loop, "compact_running", side_effect=lambda client, active: active) as compact:
            loop.run_task(None, messages)
            self.assertEqual(compact.call_count, 1)

    def test_invalid_reason_does_not_trigger_compaction(self):
        with patch.object(loop, "_chat", side_effect=[("", [self.call(arguments='{"reason":42}')], None), ("done", [], None)]), patch.object(loop, "compact_running") as compact:
            loop.run_task(None, [])
            compact.assert_not_called()

if __name__ == "__main__":
    unittest.main()
