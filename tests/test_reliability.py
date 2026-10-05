"""Offline regression tests for tool failures and session recovery."""
import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import cli, context, loop, session
from fei.tools import bash
from fei.tools.base import Tool

class ReliabilityTests(unittest.TestCase):
    def test_command_failure_and_workdir(self):
        proc = types.SimpleNamespace(stdout="out", stderr="err", returncode=2)
        with patch.object(bash, "run_command", return_value=proc) as run:
            with self.assertRaisesRegex(RuntimeError, "2"):
                bash._run("false")
        self.assertEqual(run.call_args.kwargs["cwd"], bash.config.WORKDIR)

    def test_bad_arguments_never_execute(self):
        for arguments in ("{bad", "[]", "null"):
            messages = [{"role": "user", "content": "task"}]
            calls = [{"id": "c", "function": {"name": "write_file", "arguments": arguments}}]
            with patch.object(loop, "_chat", side_effect=[("", calls, None), ("done", [], None)]), patch.object(loop, "_execute") as execute:
                loop.run_task(None, messages)
                execute.assert_not_called()
            self.assertEqual(messages[2]["role"], "tool")

    def test_permission_without_callback_denies(self):
        tool = Tool("protected", "", {}, lambda: "executed", needs_permission=True)
        calls = [{"id": "c", "function": {"name": "protected", "arguments": "{}"}}]
        messages = []
        with patch.dict(loop.REGISTRY, {"protected": tool}), patch.object(loop, "_chat", side_effect=[("", calls, None), ("done", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, messages)
            execute.assert_not_called()

    def test_turn_limit_is_recorded_and_streamed(self):
        calls = [{"id": "c", "function": {"name": "unknown", "arguments": "{}"}}]
        messages, output = [], []
        with patch.object(loop, "MAX_TURNS", 1), patch.object(loop, "_chat", return_value=("", calls, None)):
            result = loop.run_task(None, messages, on_text=output.append)
        self.assertEqual(messages[-1]["content"], result)
        self.assertEqual(output, [result])
        self.assertEqual(messages[-2]["role"], "tool")

    def test_summary_retains_arguments(self):
        text = context.render([{"role": "assistant", "content": "why", "tool_calls": [{"function": {"name": "read_file", "arguments": '{"path":"main.py"}'}}]}])
        self.assertIn("main.py", text)
        self.assertIn("why", text)

    def test_session_snapshot_and_pair_validation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)):
            first, second = session.Session(), session.Session()
            self.assertNotEqual(first.path, second.path)
            messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "summary + task"}]
            first.save_state(messages)
            self.assertEqual(session.Session.load_state(first.path), messages)
            first.save_state([{"role": "assistant", "tool_calls": [{"id": "c"}]}])
            with self.assertRaises(ValueError):
                session.Session.load_state(first.path)

    def test_cli_recovers_from_partial_tool_failure(self):
        def failing(client, messages, **kwargs):
            messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": "c"}]})
            raise RuntimeError("network unavailable")
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)), patch.object(cli.llm, "make_client", return_value=None), patch.object(cli, "run_task", side_effect=failing), patch("builtins.input", side_effect=["task", "/exit"]), patch("sys.stdout", new_callable=io.StringIO):
            cli.main()
            state = next(Path(folder).glob("*.state.json"))
            messages = session.Session.load_state(state)
            self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant"])
            self.assertIn("network unavailable", messages[-1]["content"])

if __name__ == "__main__":
    unittest.main()
