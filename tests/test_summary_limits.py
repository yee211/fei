import copy
import types
import unittest
from unittest.mock import Mock
from fei.context import compact_running

class SummaryLimitTests(unittest.TestCase):
    def messages(self):
        return [{"role":"user","content":"Preserve constraints"}]+[{"role":"assistant","content":"x"*1000} for _ in range(5)]
    def response(self,text,reason):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text),finish_reason=reason)])
    def client(self,responses):
        create=Mock(side_effect=responses)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    def test_truncated_nonempty_summary_is_retried(self):
        client=self.client([self.response("partial","length"),self.response("Complete memo","stop")])
        updated=compact_running(client,self.messages())
        self.assertIn("Complete memo",updated[0]["content"])
        self.assertEqual(client.chat.completions.create.call_count,2)
        budgets=[call.kwargs["max_tokens"] for call in client.chat.completions.create.call_args_list]
        self.assertEqual(budgets,[4096,8192])
    def test_empty_summary_retry_can_recover(self):
        client=self.client([self.response("","length"),self.response("Recovered memo","stop")])
        self.assertIn("Recovered memo",compact_running(client,self.messages())[0]["content"])
    def test_prior_history_only_keeps_current_user_last(self):
        messages=[{"role":"user","content":"old task"},{"role":"assistant","content":"x"*4000},{"role":"user","content":"current goal"}]
        client=self.client([self.response("prior task memo","stop")])
        updated=compact_running(client,messages)
        self.assertEqual(updated[-1],{"role":"user","content":"current goal"})
        self.assertEqual(updated[-2]["role"],"user")

    def test_repeated_truncation_preserves_original(self):
        original=self.messages();snapshot=copy.deepcopy(original)
        client=self.client([self.response("partial","length")]*2)
        with self.assertRaises(ValueError):compact_running(client,original)
        self.assertEqual(original,snapshot)

if __name__=="__main__":unittest.main()
