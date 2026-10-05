import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import config
from fei.changes import apply_change, get_change, show_changes, revert_change
from fei.permission import permission_request
from fei.tools import REGISTRY

class ChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.object(config, "WORKDIR", self.root)
        patcher.start(); self.addCleanup(patcher.stop)

    def test_diff_and_exact_byte_restore(self):
        p = self.root / "a.py"
        original = b"\xef\xbb\xbfvalue = 1\r\n"
        p.write_bytes(original)
        change = apply_change(p, b"value = 2\n")
        self.assertIn("value = 2", show_changes(change))
        revert_change(change)
        self.assertEqual(p.read_bytes(), original)
        self.assertEqual(get_change(change)["status"], "reverted")

    def test_new_file_undo_and_repeat_rejected(self):
        p = self.root / "new.py"
        change = apply_change(p, b"new")
        revert_change(change)
        self.assertFalse(p.exists())
        with self.assertRaises(ValueError): revert_change(change)

    def test_external_edit_never_overwritten(self):
        p = self.root / "a.py";p.write_bytes(b"original")
        change = apply_change(p, b"agent")
        p.write_bytes(b"human edit")
        with self.assertRaises(RuntimeError): revert_change(change)
        self.assertEqual(p.read_bytes(), b"human edit")

    def test_reverse_order_revert(self):
        p = self.root / "a.py";p.write_bytes(b"one")
        first = apply_change(p, b"two")
        second = apply_change(p, b"three")
        with self.assertRaises(RuntimeError): revert_change(first)
        revert_change(second);revert_change(first)
        self.assertEqual(p.read_bytes(), b"one")

    def test_noop_expected_content_and_bad_id(self):
        p = self.root / "a.py";p.write_bytes(b"one")
        self.assertIsNone(apply_change(p, b"one"))
        with self.assertRaises(RuntimeError): apply_change(p, b"two", expected=b"stale")
        with self.assertRaises(ValueError): get_change("../a")
        self.assertEqual(show_changes(), "No tracked changes")

    def test_permissions_show_readonly_revert_confirmed(self):
        p = self.root / "a.py";p.write_bytes(b"one")
        change = apply_change(p, b"two")
        self.assertIsNone(permission_request(REGISTRY["show_changes"], {}))
        request = permission_request(REGISTRY["revert_change"], {"change_id": change})
        self.assertIn(str(p), request)
        self.assertIn(change, request)

if __name__ == "__main__": unittest.main()
