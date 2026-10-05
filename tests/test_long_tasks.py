import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import config, context, loop, session
from fei.output import prepare_output
from fei.tools.base import Tool
from fei.tools.read import _read_file
from fei.tools.bash import _run

def task_block(number, text="result"):
    call = {"id": f"c{number}", "function": {"name": "probe", "arguments": "{}"}}
    return [{"role": "assistant", "content": "", "tool_calls": [call]}, {"role": "tool", "tool_call_id": call["id"], "content": text}]

class LongTaskTests(unittest.TestCase):
    def client(self, summary="修改 main.py；验证失败，仍待修复；不要声称通过。"):
        response = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=summary))])
        from unittest.mock import Mock
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=Mock(return_value=response))))

    def test_split_preserves_multi_tool_call_group(self):
        calls = [{"id": "a"}, {"id": "b"}]
        messages = [{"role": "assistant", "tool_calls": calls}, {"role": "tool", "tool_call_id": "b"}, {"role": "tool", "tool_call_id": "a"}]
        self.assertEqual(context.complete_blocks(messages), [messages])
        with self.assertRaises(ValueError):
            context.complete_blocks(messages[:-1])

    def test_compaction_keeps_exact_goal_and_recent_pairs(self):
        goal = {"role": "user", "content": "修复 main.py，不能修改 public API"}
        messages = [{"role": "system", "content": "system"}, goal]
        for number in range(5):
            messages.extend(task_block(number, "x" * 2500))
        original = copy.deepcopy(messages)
        updated = context.compact_running(self.client(), messages)
        self.assertEqual(next(m for m in updated if m.get("content") == goal["content"]), goal)
        self.assertEqual(updated[-4:], original[-4:])
        context.complete_blocks(updated)
        self.assertTrue(any("待修复" in str(m.get("content", "")) for m in updated))
        self.assertEqual(messages, original)
        self.assertLess(context.estimate_tokens(updated), context.estimate_tokens(original))

    def test_empty_summary_does_not_mutate_context(self):
        messages = [{"role": "user", "content": "goal"}]
        for number in range(4):
            messages.extend(task_block(number, "x" * 2000))
        original = copy.deepcopy(messages)
        with self.assertRaises(ValueError):
            context.compact_running(self.client(""), messages)
        self.assertEqual(messages, original)

    def test_large_summary_input_folded_in_bounded_chunks(self):
        messages = [{"role": "user", "content": "goal"}]
        for number in range(5):
            messages.extend(task_block(number, "x" * 15000))
        client = self.client()
        context.compact_running(client, messages)
        self.assertGreater(client.chat.completions.create.call_count, 1)
        for call in client.chat.completions.create.call_args_list:
            self.assertLess(len(call.kwargs["messages"][1]["content"]), 15000)

    def test_full_output_saved_and_head_tail_retained(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)):
            saved = session.Session()
            original = "HEAD" + "x" * 20000 + "TAIL: validation failed"
            preview, path = prepare_output(original, saved.store_output)
            self.assertEqual(Path(path).read_text(encoding="utf-8"), original)
            self.assertIn("HEAD", preview)
            self.assertIn("TAIL: validation failed", preview)
            self.assertIn(path, preview)
            self.assertLessEqual(len(preview), config.MAX_TOOL_OUTPUT)
            self.assertIn("validation failed", _read_file(path, offset=1, limit=1))

    def test_command_error_no_longer_discards_tail(self):
        proc = types.SimpleNamespace(stdout="x" * 20000, stderr="TAIL_ERROR", returncode=1)
        with patch("fei.tools.bash.run_command", return_value=proc):
            with self.assertRaisesRegex(RuntimeError, "TAIL_ERROR"):
                _run("test")

    def test_multiround_task_compacts_and_can_restore(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)):
            saved = session.Session()
            goal = {"role": "user", "content": "fix, test, retry; do not change public API"}
            messages = [{"role": "system", "content": "s"}, goal]
            for message in messages:
                saved.append(message)
            record = {}
            responses = []
            for number in range(5):
                responses.append(("", task_block(number)[0]["tool_calls"], types.SimpleNamespace(prompt_tokens=10)))
            responses.append(("done; tests still need verification", [], types.SimpleNamespace(prompt_tokens=10)))
            requests = []
            def chat(client, active, **kwargs):
                context.complete_blocks(active)
                requests.append(copy.deepcopy(active))
                response = responses.pop(0)
                return response[:2] + (types.SimpleNamespace(prompt_tokens=context.estimate_tokens(active, loop.schemas())),)
            tool = Tool("probe", "probe", {"type": "object"}, lambda: "failure evidence " + "x" * 6000)
            threshold = context.estimate_tokens(messages, loop.schemas()) + 15000
            with patch.object(config, "REPEAT_LIMIT", 10), patch.dict(loop.REGISTRY, {"probe": tool}), patch.object(config, "COMPACT_TOKENS", threshold), patch.object(loop, "_chat", side_effect=chat):
                result = loop.run_task(self.client(), messages, confirm=lambda *args: True, task_record=record, on_message=saved.append, checkpoint=saved.save_state, output_writer=saved.store_output)
            saved.save_state(messages)
            self.assertIn("verification", result)
            self.assertTrue(record["context_compactions"])
            self.assertEqual(len(record["tool_calls"]), 5)
            self.assertEqual(next(m for m in messages if m.get("content") == goal["content"]), goal)
            self.assertEqual(session.Session.load_state(saved.path), messages)
            history = session.Session.load(saved.path)
            self.assertEqual(len([m for m in history if m["role"] == "tool"]), 5)
            self.assertGreater(len(history), len(messages))

    def test_uncompressible_request_stops_before_model_call(self):
        from unittest.mock import Mock
        client = self.client()
        messages = [{"role": "user", "content": "x" * 10000}]
        with patch.object(config, "COMPACT_TOKENS", 100), patch.object(loop, "_chat") as chat:
            with self.assertRaisesRegex(RuntimeError, "budget"):
                loop.run_task(client, messages)
            chat.assert_not_called()

if __name__ == "__main__":
    unittest.main()
