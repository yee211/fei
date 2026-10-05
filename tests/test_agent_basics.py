import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
try:
    import httpx2 as httpx
except ImportError:
    import httpx
from openai import OpenAI, APIStatusError
from fei import config, llm, loop, session, cli
from fei.permission import permission_request
from fei.tools import REGISTRY
from fei.tools.base import Tool

class AgentBasicsTests(unittest.TestCase):
    def test_permissions_inside_outside_and_write(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "WORKDIR", Path(folder)):
            self.assertIsNone(permission_request(REGISTRY["read_file"], {"path": "a.py"}))
            self.assertIsNotNone(permission_request(REGISTRY["read_file"], {"path": "../outside.py"}))
            request = permission_request(REGISTRY["edit_file"], {"path": "a.py", "old_text": "old", "new_text": "new"})
            self.assertIn("old", request)
            self.assertIn("new", request)
            self.assertIsNotNone(permission_request(REGISTRY["run_bash"], {"command": "echo hello"}))

    def test_denied_write_records_error_without_execution(self):
        calls = [{"id": "c", "function": {"name": "write_file", "arguments": '{"path":"a.py","content":"x"}'}}]
        record = {}
        with patch.object(loop, "_chat", side_effect=[("", calls, None), ("cannot proceed", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, [], task_record=record)
            execute.assert_not_called()
        self.assertEqual(record["status"], "returned")
        self.assertEqual(record["tool_calls"][0]["status"], "error")

    def test_client_explicit_timeout_and_retries(self):
        with patch.object(config, "API_KEY", "test"), patch.object(llm, "OpenAI") as constructor:
            llm.make_client()
        self.assertEqual(constructor.call_args.kwargs["timeout"], config.REQUEST_TIMEOUT)
        self.assertEqual(constructor.call_args.kwargs["max_retries"], config.REQUEST_RETRIES)

    def test_sdk_retries_request_but_executes_tool_once(self):
        count = 0
        def transport(request):
            nonlocal count
            count += 1
            if count == 1:
                return httpx.Response(500, json={"error": {"message": "temporary"}})
            message = {"role": "assistant", "content": "done"}
            if count == 2:
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "type": "function", "function": {"name": "probe", "arguments": "{}"}}]}
            return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": "test", "choices": [{"index": 0, "message": message, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        handler = Mock(return_value="evidence")
        tool = Tool("probe", "test", {"type": "object", "properties": {}}, handler)
        with OpenAI(api_key="test", base_url="https://offline.invalid/v1", max_retries=1, http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client, patch("openai._base_client.time.sleep"), patch.dict(loop.REGISTRY, {"probe": tool}):
            record = {}
            self.assertEqual(loop.run_task(client, [], confirm=lambda *args: True, task_record=record), "done")
        handler.assert_called_once_with()
        self.assertEqual(count, 3)
        self.assertEqual(record["tool_calls"][0]["result"], "evidence")

    def test_nonretryable_error_is_not_replayed(self):
        transport = Mock(return_value=httpx.Response(400, json={"error": {"message": "bad request"}}))
        with OpenAI(api_key="test", base_url="https://offline.invalid/v1", max_retries=2, http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client, patch.object(loop, "_execute") as execute:
            with self.assertRaises(APIStatusError):
                loop.run_task(client, [])
            execute.assert_not_called()
        self.assertEqual(transport.call_count, 1)

    def test_stream_failure_is_not_replayed(self):
        def broken_stream():
            yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content="partial", tool_calls=[]))], usage=None)
            raise RuntimeError("stream interrupted")
        create = Mock(return_value=broken_stream())
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        output = []
        with self.assertRaises(RuntimeError):
            loop.run_task(client, [], on_text=output.append)
        create.assert_called_once()
        self.assertEqual(output, ["partial"])

    def test_cli_task_record_persisted_on_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)), patch.object(cli.llm, "make_client", return_value=None), patch.object(cli, "run_task", side_effect=RuntimeError("offline")), patch("builtins.input", side_effect=["goal", "/exit"]), patch("sys.stdout", new_callable=io.StringIO):
            cli.main()
            record = json.loads(next(Path(folder).glob("*.tasks.jsonl")).read_text(encoding="utf-8"))
            self.assertEqual(record["goal"], "goal")
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["verification"], "not_independently_verified")
            self.assertIn("finished_at", record)

if __name__ == "__main__":
    unittest.main()
