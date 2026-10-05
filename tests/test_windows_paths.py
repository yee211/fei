import os
import unittest
from pathlib import Path
from fei.tools._paths import resolve

@unittest.skipUnless(os.name == "nt", "Windows path semantics")
class WindowsPathsTests(unittest.TestCase):
    def test_git_bash_drive_matches_windows_path(self):
        for drive in ("c", "d", "C"):
            self.assertEqual(resolve("/" + drive + "/Users/1/Desktop/ye/HelloWorld.java"), Path(drive.upper() + ":/Users/1/Desktop/ye/HelloWorld.java"))
        self.assertEqual(resolve("/c"), Path("C:/"))

    def test_ambiguous_root_relative_path_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve("/Users/1/Desktop/ye")

    def test_home_expansion(self):
        self.assertEqual(resolve("~/Desktop/ye"), Path.home() / "Desktop" / "ye")

if __name__ == "__main__":
    unittest.main()
