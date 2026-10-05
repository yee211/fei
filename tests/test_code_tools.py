import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fei import config
from fei.tools import REGISTRY
from fei.tools.edit import _edit_file
from fei.tools.search import _search_code

class CodeToolsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workdir = patch.object(config, "WORKDIR", self.root)
        self.workdir.start()
        self.addCleanup(self.workdir.stop)

    def test_exact_edit_preserves_other_content(self):
        p = self.root / "main.py"
        p.write_bytes(b"before\nvalue = 1\nafter\n")
        _edit_file("main.py", "value = 1", "value = 2")
        self.assertEqual(p.read_bytes(), b"before\nvalue = 2\nafter\n")

    def test_ambiguous_or_missing_match_leaves_file_unchanged(self):
        p = self.root / "main.py"
        p.write_bytes(b"foo foo")
        for old in ("foo", "missing", ""):
            with self.assertRaises(ValueError):
                _edit_file("main.py", old, "bar")
            self.assertEqual(p.read_bytes(), b"foo foo")

    def test_replace_all_and_delete(self):
        p = self.root / "main.py"
        p.write_text("foo foo", encoding="utf-8")
        _edit_file("main.py", "foo", "bar", replace_all=True)
        _edit_file("main.py", "bar ", "")
        self.assertEqual(p.read_text(), "bar")

    def test_preserves_bom_crlf_without_final_newline(self):
        p = self.root / "main.py"
        p.write_bytes(b"\xef\xbb\xbfhello\r\nworld")
        _edit_file("main.py", "hello\nworld", "hello\nearth")
        self.assertEqual(p.read_bytes(), b"\xef\xbb\xbfhello\r\nearth")

    def test_binary_and_large_files_rejected(self):
        p = self.root / "data"
        p.write_bytes(b"a\x00b")
        with self.assertRaises(ValueError):
            _edit_file("data", "a", "c")
        p.write_bytes(b"abc")
        with patch("fei.tools.edit.MAX_EDIT_BYTES", 2), self.assertRaises(ValueError):
            _edit_file("data", "a", "c")

    def test_literal_regex_and_glob_search(self):
        (self.root / "one.py").write_text("a.b\naxb\n", encoding="utf-8")
        (self.root / "two.txt").write_text("a.b\n", encoding="utf-8")
        literal = _search_code("a.b", glob="*.py")
        self.assertIn("one.py:1:a.b", literal)
        self.assertNotIn("axb", literal)
        self.assertNotIn("two.txt", literal)
        self.assertIn("one.py:2:axb", _search_code("a.b", regex=True))

    def test_no_matches_invalid_regex_and_missing_rg(self):
        (self.root / "one.py").write_text("hello", encoding="utf-8")
        self.assertIn("No matches", _search_code("absent"))
        with self.assertRaises(RuntimeError):
            _search_code("[", regex=True)
        with patch("fei.tools.search.shutil.which", return_value=None), self.assertRaises(RuntimeError):
            _search_code("hello")

    def test_output_truncated_and_pattern_not_an_option(self):
        (self.root / "one.py").write_text("--help " + "x" * 10000, encoding="utf-8")
        result = _search_code("--help")
        self.assertIn("one.py:1:--help", result)
        self.assertGreater(len(result), config.MAX_TOOL_OUTPUT)  # Loop offloads the complete result.

    def test_tools_registered(self):
        self.assertIn("edit_file", REGISTRY)
        self.assertIn("search_code", REGISTRY)

if __name__ == "__main__":
    unittest.main()
