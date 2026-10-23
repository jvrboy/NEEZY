"""The installed command defaults to portable CLI and keeps desktop explicit."""

import contextlib
import io
import sys
import unittest
from unittest import mock

from neezy_app import launcher


class LauncherTests(unittest.TestCase):
    @mock.patch("neezy_backend.menu.run_menu", return_value=0)
    def test_no_arguments_launch_terminal_without_desktop(self, run_menu):
        with mock.patch.object(launcher, "_run_desktop") as desktop:
            self.assertEqual(launcher.main([]), 0)
        desktop.assert_not_called()
        run_menu.assert_called_once_with(sys.stdout)

    @mock.patch("neezy_backend.menu.run_menu", return_value=0)
    def test_explicit_plain_terminal_route(self, run_menu):
        self.assertEqual(launcher.main(["--plain"]), 0)
        run_menu.assert_called_once_with(sys.stdout, color=False)

    @mock.patch.object(launcher, "_run_desktop", return_value=0)
    @mock.patch("neezy_backend.menu.run_menu")
    def test_explicit_desktop_route(self, run_menu, desktop):
        self.assertEqual(launcher.main(["--desktop"]), 0)
        desktop.assert_called_once_with()
        run_menu.assert_not_called()

    def test_help_describes_both_routes_without_importing_tk(self):
        output = io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            self.assertRaises(SystemExit) as raised,
        ):
            launcher.main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("terminal by default", output.getvalue())
        self.assertIn("--desktop", output.getvalue())


if __name__ == "__main__":
    unittest.main()
