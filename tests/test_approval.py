import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fei import config, loop, session
from fei.approval import ApprovalService
from fei.permission import permission_request
from fei.tools import REGISTRY

class ApprovalTests(unittest.TestCase):
    def authorize(self, service, name, args):
        tool = REGISTRY[name]
        return service.authorize(tool, args, permission_request(tool, args))

    def test_auto_workspace_write_and_read_mode_blocks_it(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "WORKDIR", Path(folder)):
            service = ApprovalService()
            self.assertTrue(self.authorize(service, "write_file", {"path":"a.py", "content":"a"}))
            service.set_mode("read")
            self.assertFalse(self.authorize(service, "write_file", {"path":"a.py", "content":"a"}))
            self.assertFalse(self.authorize(service, "run_bash", {"command":"echo hi"}))
            self.assertTrue(self.authorize(service, "read_file", {"path":"a.py"}))

    def test_once_session_reset_and_delete(self):
        ask = Mock(side_effect=["once", "session", "denied", "denied"])
        service = ApprovalService(ask)
        args = {"command":"echo hi"}
        self.assertTrue(self.authorize(service, "run_bash", args))
        self.assertTrue(self.authorize(service, "run_bash", args))
        self.assertTrue(self.authorize(service, "run_bash", {"command":"javac Main.java"}))
        self.assertEqual(ask.call_count, 2)
        self.assertFalse(self.authorize(service, "run_bash", {"command":"rm -rf ./output"}))
        service.reset()
        self.assertFalse(self.authorize(service, "run_bash", args))

    def test_directory_grant_read_does_not_allow_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(config, "WORKDIR", root / "workspace"):
                ask = Mock(side_effect=["session", "denied", "session"])
                service = ApprovalService(ask)
                self.assertTrue(self.authorize(service, "read_file", {"path":str(root / "outside/a.py")}))
                self.assertFalse(self.authorize(service, "write_file", {"path":str(root / "outside/b.py"), "content":"x"}))
                self.assertTrue(self.authorize(service, "write_file", {"path":str(root / "outside/b.py"), "content":"x"}))
                self.assertTrue(self.authorize(service, "write_file", {"path":str(root / "outside/sub/c.py"), "content":"x"}))
                self.assertTrue(self.authorize(service, "read_file", {"path":str(root / "outside/sub/c.py")}))
                self.assertEqual(ask.call_count, 3)

    def test_missing_or_failed_ui_denies(self):
        for ask in [None, Mock(side_effect=RuntimeError("offline")), Mock(side_effect=KeyboardInterrupt)]:
            self.assertFalse(self.authorize(ApprovalService(ask), "run_bash", {"command":"echo hi"}))

    def test_full_does_not_bypass_guard_or_hook(self):
        service = ApprovalService(mode="full")
        call = {"id":"bad", "function":{"name":"run_bash", "arguments":json.dumps({"command":"rm -rf /"})}}
        with patch.dict("os.environ", {"FEI_ALLOW_DANGEROUS":"0"}), patch.object(loop, "_chat", side_effect=[("", [call], None), ("blocked", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, [], permission_policy=service)
            execute.assert_not_called()

    def test_mcp_exact_tool_scope_and_read_denial(self):
        from fei.tools.base import Tool
        tool = Tool("external", "test", {}, lambda: "ok", source="server")
        other = Tool("other", "test", {}, lambda: "ok", source="server")
        ask = Mock(side_effect=["session", "denied"])
        service = ApprovalService(ask)
        self.assertTrue(service.authorize(tool, {}, "external"))
        self.assertTrue(service.authorize(tool, {}, "external"))
        self.assertFalse(service.authorize(other, {}, "other"))
        service.set_mode("read")
        self.assertFalse(service.authorize(tool, {}, "external"))

    def test_cli_reuses_session_then_clear_revokes(self):
        from fei import cli
        import io
        results = []
        def run(client, messages, **kwargs):
            service = kwargs["permission_policy"]
            results.append(self.authorize(service, "run_bash", {"command":"echo hi"}))
            return "done"
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)), patch.object(cli.llm, "make_client", return_value=None), patch.object(cli, "STREAM", False), patch.object(cli, "run_task", side_effect=run), patch("builtins.input", side_effect=["task1", "s", "task2", "/clear", "task3", "n", "/permission read", "/permission", "/exit"]), patch("sys.stdout", new_callable=io.StringIO):
            cli._interactive_main()
        self.assertEqual(results, [True, True, False])

    def test_audit_separate_from_messages_and_mode_revokes(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(session, "SESSIONS_DIR", Path(folder)):
            saved = session.Session()
            service = ApprovalService(Mock(return_value="session"), saved.append_permission)
            self.authorize(service, "run_bash", {"command":"echo hi"})
            records = session.Session.load(saved.path.with_suffix(".permissions.jsonl"))
            self.assertEqual([r["event"] for r in records], ["permission.asked", "permission.decided"])
            service.set_mode("read")
            self.assertFalse(service.grants)
            self.assertFalse(saved.path.exists())

if __name__ == "__main__":
    unittest.main()
