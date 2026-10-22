"""Tests for storage.sanitize_path as the thin wrapper over sandbox.resolve_within.

Roadmap #4: one traversal guard. These tests pin the wrapper contract:
same jail semantics as resolve_within, plus expanduser and the explicit
allow_absolute escape hatch.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neezy_backend.sandbox import PathNotAllowedError
from neezy_backend.storage import get_data_dir, sanitize_path


class SanitizePathWrapperTests(unittest.TestCase):
    """sanitize_path delegates its jail check to sandbox.resolve_within."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)

    def test_relative_path_lands_inside_root(self) -> None:
        target = sanitize_path("data/file.txt", base_dir=self.root)
        self.assertEqual(target, self.root / "data" / "file.txt")

    def test_dotdot_traversal_is_blocked(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_path("../../etc/passwd", base_dir=self.root)

    def test_absolute_outside_path_is_blocked(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_path("/etc/passwd", base_dir=self.root)

    def test_blocked_message_names_the_root(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            sanitize_path("../escape.txt", base_dir=self.root)
        self.assertIn("Path traversal blocked", str(ctx.exception))
        self.assertIn(str(self.root), str(ctx.exception))

    def test_null_byte_is_rejected_even_with_escape_hatch(self) -> None:
        with self.assertRaises(PathNotAllowedError):
            sanitize_path("bad\0name", base_dir=self.root)
        with self.assertRaises(PathNotAllowedError):
            sanitize_path("bad\0name", base_dir=self.root, allow_absolute=True)

    def test_allow_absolute_escape_hatch_returns_resolved_path(self) -> None:
        outside = self.root.parent / "elsewhere.txt"
        target = sanitize_path(outside, base_dir=self.root, allow_absolute=True)
        self.assertEqual(target, outside.resolve())

    def test_allow_absolute_hatch_also_covers_relative_traversal(self) -> None:
        # Matches the original semantics: the hatch trusts the caller fully,
        # so a relative "../x" resolves outside the root instead of raising.
        target = sanitize_path("../x", base_dir=self.root, allow_absolute=True)
        self.assertEqual(target, (self.root.parent / "x").resolve())

    def test_symlink_escape_is_blocked(self) -> None:
        import shutil

        outside_dir = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, outside_dir, ignore_errors=True)
        (outside_dir / "secret.txt").write_text("s", encoding="utf-8")
        link = self.root / "link"
        link.symlink_to(outside_dir, target_is_directory=True)
        with self.assertRaises(ValueError):
            sanitize_path("link/secret.txt", base_dir=self.root)

    def test_expanduser_is_applied_then_jailed(self) -> None:
        # "~" expands BEFORE the jail check: inside the home root it works...
        target = sanitize_path("~/neezy-test-file", base_dir=Path.home())
        self.assertEqual(target, (Path.home() / "neezy-test-file").resolve())
        # ...and against another root the expanded path is still blocked.
        with self.assertRaises(ValueError):
            sanitize_path("~/neezy-test-file", base_dir=self.root)

    def test_default_root_is_the_data_dir(self) -> None:
        target = sanitize_path("settings.json")
        self.assertEqual(target, get_data_dir() / "settings.json")

    def test_root_itself_is_allowed(self) -> None:
        self.assertEqual(sanitize_path(".", base_dir=self.root), self.root)


if __name__ == "__main__":
    unittest.main()
