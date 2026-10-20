import tempfile
import unittest
from pathlib import Path

from neezy_backend.sandbox import (
    PathNotAllowedError,
    resolve_within,
    resolve_within_any,
)


class SandboxTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "root"
        self.root.mkdir()
        self.other = Path(self._tmp.name) / "other"
        self.other.mkdir()

    def test_relative_path_inside_root(self):
        target = resolve_within(self.root, "data/file.txt")
        self.assertEqual(target, self.root.resolve() / "data" / "file.txt")

    def test_root_itself_is_allowed(self):
        self.assertEqual(resolve_within(self.root, "."), self.root.resolve())

    def test_parent_traversal_rejected(self):
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "../other/secret.txt")

    def test_absolute_path_outside_rejected(self):
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, self.other / "secret.txt")

    def test_sibling_with_shared_prefix_rejected(self):
        sibling = Path(self._tmp.name) / "root-evil"
        sibling.mkdir()
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, sibling / "x")

    def test_symlink_escape_rejected(self):
        link = self.root / "link"
        try:
            link.symlink_to(self.other, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this platform")
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "link/secret.txt")

    def test_null_byte_rejected(self):
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "bad\0name")

    def test_any_root(self):
        target = resolve_within_any([self.root, self.other], self.other / "a.txt")
        self.assertEqual(target, self.other.resolve() / "a.txt")
        with self.assertRaises(PathNotAllowedError):
            resolve_within_any([self.root], self.other / "a.txt")


if __name__ == "__main__":
    unittest.main()
