import copy
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fei import config, loop
from fei.commands import run_command
from fei.instructions import ProjectInstructions
from fei.task_state import TaskState
from fei.validation import validate
from fei.tools import REGISTRY

class RuntimeFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.object(config, "WORKDIR", self.root)
        patcher.start(); self.addCleanup(patcher.stop)
    def call(self, name, args, id):
        return {"id": id, "function": {"name": name, "arguments": json.dumps(args)}}
    def finish(self, status="verified", ids=None):
        return self.call("finish_task", {"summary": "done", "completed": ["fixed"], "remaining": [], "verification_ids": ["verify"] if ids is None else ids, "status": status}, "finish")
    def test_parameter_types_bounds_missing_unknown(self):
        for args in ({"path": "a", "limit": -1}, {"path": "a", "offset": True}, {"path": "a", "extra": 1}, {}):
            with self.assertRaises(ValueError): validate(args, REGISTRY["read_file"].parameters)
        validate({"path": "a", "limit": 1}, REGISTRY["read_file"].parameters)
        with self.assertRaises(ValueError): validate({"command": "echo", "timeout": float("nan")}, REGISTRY["run_bash"].parameters)
    def test_invalid_parameters_never_confirm_or_execute(self):
        confirm = Mock(return_value=True)
        with patch.object(loop, "_chat", side_effect=[("", [self.call("write_file", {"path": "a", "content": 3}, "c")], None), ("done", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, [], confirm=confirm)
            execute.assert_not_called(); confirm.assert_not_called()
    def test_scoped_instructions_refresh_and_removed(self):
        (self.root / "AGENTS.md").write_text("root rule", encoding="utf-8")
        sub = self.root / "src";sub.mkdir()
        (sub / "AGENTS.md").write_text("nested rule", encoding="utf-8")
        manager = ProjectInstructions();messages = [{"role": "user", "content": "goal"}]
        manager.refresh(messages)
        self.assertIn("root rule", next(m["content"] for m in reversed(messages) if m["role"] == "system"))
        self.assertNotIn("nested rule", next(m["content"] for m in reversed(messages) if m["role"] == "system"))
        manager.add_path(sub / "main.py");manager.refresh(messages)
        self.assertIn("nested rule", next(m["content"] for m in reversed(messages) if m["role"] == "system"))
        (sub / "AGENTS.md").write_text("changed nested instruction", encoding="utf-8")
        manager.refresh(messages)
        self.assertIn("changed nested", next(m["content"] for m in reversed(messages) if m["role"] == "system"))
        (sub / "AGENTS.md").unlink(); manager.refresh(messages)
        self.assertNotIn("changed nested", next(m["content"] for m in reversed(messages) if m["role"] == "system"))
        from fei.state_messages import compact_system_messages
        self.assertEqual(len(compact_system_messages(messages)), 1)
    def test_outside_instructions_not_loaded(self):
        manager = ProjectInstructions()
        self.assertFalse(manager.add_path(self.root.parent / "outside" / "file.py"))
        self.assertEqual(manager.directories, {self.root})
    def test_nested_rule_requires_model_review_before_edit(self):
        sub = self.root / "src";sub.mkdir()
        (sub / "AGENTS.md").write_text("Use existing style", encoding="utf-8")
        (sub / "main.py").write_text("old", encoding="utf-8")
        call = self.call("edit_file", {"path": "src/main.py", "old_text": "old", "new_text": "new"}, "edit")
        messages = [{"role": "user", "content": "fix"}]
        with patch.object(loop, "_chat", side_effect=[("", [call], None), ("read rules", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, messages, confirm=lambda *args: True)
            execute.assert_not_called()
        self.assertIn("Use existing style", next(m["content"] for m in reversed(messages) if m["role"] == "system"))
    def test_finish_requires_real_successful_recent_verification(self):
        state = TaskState()
        with self.assertRaises(ValueError): state.finish("done", [], [], ["fake"], "verified")
        with self.assertRaises(ValueError): state.finish("done", [], [], [], "verified")
        state.evidence["v"] = {"name": "run_bash", "arguments": {"purpose": "verification"}, "error": None, "sequence": 1}
        state.last_change = 2
        with self.assertRaises(ValueError): state.finish("done", [], [], ["v"], "verified")
        state.evidence["v"]["sequence"] = 3;state.evidence["v"]["error"] = "failed"
        with self.assertRaises(ValueError): state.finish("done", [], [], ["v"], "verified")
        state.evidence["v"]["error"] = None
        self.assertIn("verified", state.finish("done", [], [], ["v"], "verified"))
    def test_finish_unverified_allowed_without_tests(self):
        self.assertIn("unverified", TaskState().finish("changed", ["changed"], [], [], "unverified"))
    def test_finish_full_loop_and_record(self):
        calls = [self.call("write_file", {"path": "a.py", "content": "x"}, "edit")]
        verify = self.call("run_bash", {"command": "test", "purpose": "verification"}, "verify")
        record = {}
        from fei.tools.finish import _finish_task
        def execute(tool, args):
            if tool.name == "finish_task": return _finish_task(**args), None
            return "changed" if tool.name == "write_file" else "tests passed", None
        with patch.object(loop, "_chat", side_effect=[("", calls, None), ("", [verify], None), ("", [self.finish()], None)]), patch.object(loop, "_execute", side_effect=execute):
            reply = loop.run_task(None, [], confirm=lambda *args: True, task_record=record)
        self.assertIn("verified", reply)
        self.assertEqual(record["status"], "completed_verified")
        self.assertEqual(record["verification"], "verified")
    def test_bare_answer_after_change_does_not_claim_completion(self):
        call = self.call("write_file", {"path": "a", "content": "x"}, "edit")
        with patch.object(loop, "_chat", side_effect=[("", [call], None)] + [("done", [], None)] * 3), patch.object(loop, "_execute", return_value=("changed", None)):
            record = {};loop.run_task(None, [], confirm=lambda *args: True, task_record=record)
        self.assertEqual(record["status"], "incomplete")
    def test_finish_cannot_share_batch_with_mutation(self):
        messages = []
        with patch.object(loop, "_chat", side_effect=[("", [self.finish("unverified", []), self.call("read_file", {"path": "missing"}, "read")], None), ("done", [], None)]):
            loop.run_task(None, messages)
        self.assertIn("only tool call", messages[1]["content"])
    def test_real_command_output_and_progress(self):
        notices = []
        process = run_command([sys.executable, "-u", "-c", "import time; print('start',flush=True); time.sleep(2.1); print('end')"], cwd=self.root, progress=notices.append, timeout=5)
        self.assertEqual(process.returncode, 0)
        self.assertIn("start", process.stdout);self.assertIn("end", process.stdout)
        self.assertGreaterEqual(len(notices), 2)
        self.assertTrue(list((self.root / ".fei-results").glob("*.log")))
    def alive(self, pid):
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle: return False
            code = ctypes.c_uint32();kernel.GetExitCodeProcess(handle, ctypes.byref(code));kernel.CloseHandle(handle)
            return code.value == 259
        try: os.kill(pid, 0);return True
        except ProcessLookupError: return False
    def test_timeout_stops_spawned_child(self):
        pidfile = self.root / "child.pid"
        script = "import subprocess,sys,time,pathlib; time.sleep(.3); child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            run_command([sys.executable, "-u", "-c", script, str(pidfile)], cwd=self.root, timeout=1.5)
        self.assertTrue(pidfile.exists())
        self.assertFalse(self.alive(int(pidfile.read_text())))
    def test_interrupt_stops_process(self):
        pidfile = self.root / "parent.pid"
        script = "import os,pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)"
        def interrupt(message):
            time.sleep(.2)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            run_command([sys.executable, "-u", "-c", script, str(pidfile)], cwd=self.root, timeout=5, progress=interrupt)
        if pidfile.exists(): self.assertFalse(self.alive(int(pidfile.read_text())))

if __name__ == "__main__": unittest.main()
