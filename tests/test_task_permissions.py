import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from fei import config, loop
from fei.permission import TaskPermissions, permission_request
from fei.tools import REGISTRY

class TaskPermissionsTests(unittest.TestCase):
    def test_commands_share_task_grant_but_delete_prompts(self):
        ask = Mock(return_value=True)
        permissions = TaskPermissions(ask)
        self.assertTrue(permissions("run_bash", "命令：javac HelloWorld.java"))
        self.assertTrue(permissions("run_bash", "命令：java HelloWorld"))
        self.assertEqual(ask.call_count, 1)
        self.assertIn("当前用户权限", ask.call_args.args[1])
        permissions("run_bash", "命令：rm -f HelloWorld.class")
        permissions("run_bash", "命令：git reset --hard")
        self.assertEqual(ask.call_count, 3)
        TaskPermissions(ask)("run_bash", "命令：java HelloWorld")
        self.assertEqual(ask.call_count, 4)

    def test_denied_or_destructive_first_call_grants_nothing(self):
        ask = Mock(side_effect=[False, True, True])
        permissions = TaskPermissions(ask)
        self.assertFalse(permissions("run_bash", "命令：echo hello"))
        self.assertTrue(permissions("run_bash", "命令：rm -f artifact"))
        self.assertTrue(permissions("run_bash", "命令：echo hello"))
        self.assertEqual(ask.call_count, 3)

    def test_writes_share_exact_parent_only(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(config, "WORKDIR", Path(folder)):
            ask = Mock(return_value=True)
            permissions = TaskPermissions(ask)
            for name, args in [("write_file", {"path":"src/a.py", "content":"a"}), ("edit_file", {"path":"src/a.py", "old_text":"a", "new_text":"b"}), ("write_file", {"path":"other/b.py", "content":"b"})]:
                permissions(name, permission_request(REGISTRY[name], args))
            self.assertEqual(ask.call_count, 2)

    def test_external_and_verification_calls_do_not_share(self):
        ask = Mock(return_value=True)
        permissions = TaskPermissions(ask)
        for _ in range(2):
            permissions("verify_project", "checks")
            permissions("revert_change", "change")
        self.assertEqual(ask.call_count, 4)

    def test_hard_guard_runs_before_cached_permission(self):
        import json
        ask = Mock(return_value=True)
        permissions = TaskPermissions(ask)
        permissions("run_bash", "命令：echo hello")
        call = {"id":"bad", "function":{"name":"run_bash", "arguments":json.dumps({"command":"rm -rf /"})}}
        with patch.dict("os.environ", {"FEI_ALLOW_DANGEROUS":"0"}), patch.object(loop, "_chat", side_effect=[("", [call], None), ("blocked", [], None)]), patch.object(loop, "_execute") as execute:
            loop.run_task(None, [], confirm=permissions)
            execute.assert_not_called()
        self.assertEqual(ask.call_count, 1)

if __name__ == "__main__":
    unittest.main()
