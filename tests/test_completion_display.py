import json
import unittest
from unittest.mock import Mock, patch
from fei import cli, loop

class CompletionDisplayTests(unittest.TestCase):
    def test_stream_completion_text_keeps_structured_record(self):
        completion = {"summary":"已写入 hello.py。", "completed":["written"], "remaining":[], "verification_ids":[], "status":"unverified"}
        call = {"id":"finish", "function":{"name":"finish_task", "arguments":json.dumps(completion)}}
        stream = Mock()
        display = Mock()
        record = {}
        with patch.object(loop, "_chat", return_value=("", [call], None)):
            result = loop.run_task(None, [], on_text=stream, on_completion=display, task_record=record)
        stream.assert_not_called()
        display.assert_called_once_with(completion)
        self.assertEqual(json.loads(result), completion)
        self.assertEqual(record["completion"], completion)
        text = cli.format_completion(completion)
        self.assertIn("hello.py", text)
        self.assertNotIn("verification_ids", text)
        self.assertIn("未确认通过", text)

if __name__ == "__main__":
    unittest.main()
