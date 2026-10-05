import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import cli, session

class MultilineInputTests(unittest.TestCase):
    def test_paste_keeps_indent_and_blank_lines(self):
        with patch('builtins.input',side_effect=['task', '', 'def add(a, b):','    return a - b','/end']),patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(cli.collect_paste(),'task\n\ndef add(a, b):\n    return a - b')
    def test_cancel_and_oversize_never_return_partial_task(self):
        with patch('builtins.input',side_effect=['task','/cancel']),patch('sys.stdout',new_callable=io.StringIO):
            self.assertIsNone(cli.collect_paste())
        with patch('builtins.input',side_effect=['x'*(cli.MAX_TASK_BYTES+1),'ignored','/end']),patch('sys.stdout',new_callable=io.StringIO):
            with self.assertRaises(ValueError):cli.collect_paste()
    def test_cli_dispatches_whole_paste_once(self):
        goals=[]
        def run(client,messages,**kwargs):
            goals.append(messages[-1]['content']);return 'done'
        with tempfile.TemporaryDirectory() as folder,patch.object(session,'SESSIONS_DIR',Path(folder)),patch.object(cli.llm,'make_client',return_value=None),patch.object(cli,'STREAM',False),patch.object(cli,'run_task',side_effect=run),patch('builtins.input',side_effect=['/paste','task','', '    code','/end','/paste','discard','/cancel','/exit']),patch('sys.stdout',new_callable=io.StringIO):
            cli._interactive_main()
        self.assertEqual(goals,['task\n\n    code'])
    def test_taskfile_preserves_utf8_bom_and_indentation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'task.txt';path.write_text('任务\n    code',encoding='utf-8-sig')
            self.assertEqual(cli.load_task_file(path),'任务\n    code')
            path.write_text(' ')
            with self.assertRaises(ValueError):cli.load_task_file(path)

if __name__=='__main__':unittest.main()
