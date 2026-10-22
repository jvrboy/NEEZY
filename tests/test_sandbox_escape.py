"""Sandbox escape test suite (roadmap update #61).

Adversarial inputs against resolve_within/resolve_within_any: traversal
chains, absolute paths, null bytes, and symlink hops. Symlink tests run
where the filesystem supports them.
"""

import os
import tempfile
import unittest
from pathlib import Path

from neezy_backend.sandbox import (
    PathNotAllowedError,
    resolve_within,
    resolve_within_any,
)


class SandboxEscapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def test_plain_relative_path_resolves_inside(self):
        target = resolve_within(self.root, "data/file.txt")
        self.assertEqual(target, self.root / "data" / "file.txt")

    def test_dotdot_chain_is_blocked(self):
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "../../etc/passwd")

    def test_nested_dotdot_is_blocked(self):
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "logs/../../../etc/passwd")

    def test_absolute_path_outside_is_blocked(self):
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "/etc/passwd")

    def test_absolute_path_inside_is_allowed(self):
        inside = self.root / "allowed.txt"
        target = resolve_within(self.root, str(inside))
        self.assertEqual(target, inside)

    def test_root_itself_is_allowed(self):
        self.assertEqual(resolve_within(self.root, "."), self.root)

    def test_null_byte_is_rejected_before_any_filesystem_call(self):
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "file\u0000.txt")

    def test_home_tilde_is_not_expanded_to_escape(self):
        # expanduser is NOT applied by resolve_within; "~" stays a literal
        # child name inside the root.
        target = resolve_within(self.root, "~")
        self.assertEqual(target, self.root / "~")

    def test_symlink_escape_is_blocked(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable on this platform")
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(outside.rmdir)
        link = self.root / "escape"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        with self.assertRaises(PathNotAllowedError):
            resolve_within(self.root, "escape/secret.txt")
        link.unlink()

    def test_symlink_to_inside_target_is_allowed(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable on this platform")
        real_dir = self.root / "real"
        real_dir.mkdir()
        link = self.root / "alias"
        try:
            link.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        target = resolve_within(self.root, "alias/file.txt")
        self.assertEqual(target, real_dir / "file.txt")
        link.unlink()

    def test_resolve_within_any_accepts_second_root(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(other.rmdir)
        # A plain name is valid under whichever root claims it first.
        target = resolve_within_any([self.root, other], "only-here.txt")
        self.assertIn(target, (self.root / "only-here.txt", other / "only-here.txt"))
        # A traversal that escapes BOTH roots must be blocked.
        with self.assertRaises(PathNotAllowedError):
            resolve_within_any([self.root, other], "../../x")

    def test_resolve_within_any_blocks_all_roots(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(other.rmdir)
        with self.assertRaises(PathNotAllowedError):
            resolve_within_any([self.root, other], "/definitely/outside")

    def test_windows_style_paths_are_treated_as_names(self):
        # On POSIX, a "C:\\Windows" string is a relative filename, not a drive.
        target = resolve_within(self.root, "C:\\Windows\\system32")
        self.assertTrue(str(target).startswith(str(self.root)))


if __name__ == "__main__":
    unittest.main()
