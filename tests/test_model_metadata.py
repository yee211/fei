import types
import unittest
from unittest.mock import Mock,patch
from fei import loop

class ModelMetadataTests(unittest.TestCase):
    def test_nonstream_model_metadata_preserved(self):
        message=types.SimpleNamespace(content="answer",tool_calls=[],reasoning_content="provider metadata")
        response=types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)],usage=None)
        client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=Mock(return_value=response))))
        messages=[];loop.run_task(client,messages)
        self.assertEqual(messages[-1]["reasoning_content"],"provider metadata")
    def test_stream_metadata_not_printed_as_answer(self):
        delta=types.SimpleNamespace(content="answer",tool_calls=[],reasoning_content="provider metadata")
        chunk=types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)],usage=None)
        client=types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=Mock(return_value=iter([chunk])))))
        messages=[];printed=[];loop.run_task(client,messages,on_text=printed.append)
        self.assertEqual(printed,["answer"])
        self.assertEqual(messages[-1]["reasoning_content"],"provider metadata")

if __name__=="__main__":unittest.main()
