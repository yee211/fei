import unittest
from unittest.mock import patch
from fei.hooks import HookRegistry, HookRejected
from fei import loop
from fei.tools.base import Tool

class HookTests(unittest.TestCase):
    def test_order_remove_and_snapshot_isolation(self):
        hooks = HookRegistry()
        seen = []
        def first(event):
            seen.append(1)
            event.data["arguments"]["x"] = 9
        remove = hooks.register("after_tool", first)
        hooks.register("after_tool", lambda event: seen.append(event.data["arguments"]["x"]))
        args = {"x": 2}
        hooks.emit("after_tool", arguments=args)
        self.assertEqual(seen, [1, 2])
        self.assertEqual(args, {"x": 2})
        remove()
        hooks.emit("after_tool", arguments=args)
        self.assertEqual(seen, [1, 2, 2])

    def test_observer_failure_logged_and_next_handler_runs(self):
        errors, seen = [], []
        hooks = HookRegistry(on_error=errors.append)
        def broken(event):
            raise RuntimeError("broken")
        hooks.register("after_model", broken)
        hooks.register("after_model", lambda event: seen.append("continued"))
        hooks.emit("after_model")
        self.assertEqual(seen, ["continued"])
        self.assertEqual(len(errors), 1)

    def test_guard_failure_and_critical_storage_fail_closed(self):
        def broken(event):
            raise RuntimeError("broken")
        for name, critical in [("before_tool", False), ("message", True)]:
            hooks = HookRegistry()
            hooks.register(name, broken, critical=critical)
            with self.assertRaises(HookRejected):
                hooks.emit(name)

    def test_guard_denial_becomes_tool_result(self):
        hooks = HookRegistry()
        hooks.register("before_tool", lambda event: "denied by policy")
        calls = [{"id": "c", "function": {"name": "write_file", "arguments": '{"path":"x","content":"x"}'}}]
        messages = []
        with patch.object(loop, "_chat", side_effect=[("", calls, None), ("done", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, messages, hooks=hooks, confirm=lambda *args: True)
            execute.assert_not_called()
        self.assertIn("denied by policy", messages[1]["content"])

    def test_hook_mutation_cannot_bypass_builtin_guard(self):
        hooks = HookRegistry()
        def mutate(event):
            event.data["arguments"]["command"] = "echo safe"
        hooks.register("before_tool", mutate)
        calls = [{"id": "c", "function": {"name": "run_bash", "arguments": '{"command":"rm -rf /"}'}}]
        with patch.object(loop, "_chat", side_effect=[("", calls, None), ("done", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, [], hooks=hooks, confirm=lambda *args: True)
            execute.assert_not_called()

    def test_task_end_fires_on_model_failure(self):
        hooks, seen = HookRegistry(), []
        hooks.register("task_end", lambda event: seen.append(event.data["status"]))
        with patch.object(loop, "_chat", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError):
                loop.run_task(None, [], hooks=hooks)
        self.assertEqual(seen, ["failed"])

    def test_registry_reuse_does_not_duplicate_callbacks(self):
        hooks, seen, messages = HookRegistry(), [], []
        hooks.register("task_start", lambda event: seen.append("start"))
        with patch.object(loop, "_chat", return_value=("done", [], None)):
            for _ in range(2):
                loop.run_task(None, [], hooks=hooks, on_message=messages.append)
        self.assertEqual(seen, ["start", "start"])
        self.assertEqual(len(messages), 2)

if __name__ == "__main__":
    unittest.main()
