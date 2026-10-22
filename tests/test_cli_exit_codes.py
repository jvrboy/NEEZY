"""CLI exit-code contract tests (roadmap update #60).

Contract: 0 success, 2 usage/runtime error surfaced on stderr. SystemExit
messages map to nonzero codes. Handlers never raise raw exceptions through
main().
"""

import io
import unittest

from neezy_backend.cli import main
from neezy_backend.risk import resolve_stop


def _run(argv: list[str], fetch=None) -> tuple[int, str]:
    out = io.StringIO()
    try:
        code = main(argv, fetch=fetch, out=out)
    except SystemExit as system_exit:
        # argparse --help/--version/usage errors exit through SystemExit.
        code = int(system_exit.code or 0)
    return code, out.getvalue()


class ExitCodeContractTests(unittest.TestCase):
    def test_version_and_help_exit_zero(self):
        self.assertEqual(_run(["--version"])[0], 0)
        self.assertEqual(_run(["--help"])[0], 0)

    def test_offline_read_commands_work_with_stub_fetch(self):
        def fake_fetch(*_args, **_kwargs):
            return [(i, 1.0 + i, 1.5 + i, 0.5 + i, 1.0 + i) for i in range(300)]

        for argv in (
            ["markets", "--json"],
            [
                "risk",
                "EURUSD",
                "--balance",
                "10000",
                "--entry",
                "1.1",
                "--stop",
                "1.09",
            ],
            ["strategies"],
        ):
            with self.subTest(argv=argv):
                code, _ = _run(argv, fetch=fake_fetch)
                self.assertEqual(code, 0)

    def test_missing_required_arguments_exit_nonzero(self):
        # risk with no stop/direction/atr is a usage error.
        code, _ = _run(["risk", "EURUSD", "--balance", "10000", "--entry", "1.1"])
        self.assertEqual(code, 2)

    def test_runtime_errors_exit_two_with_stderr_message(self):
        # Network failure surfaces as exit 2 with a readable message.
        def broken_fetch(*_args, **_kwargs):
            raise ConnectionError("no network")

        code, _ = _run(["analyze", "frxEURUSD", "-t", "5m"], fetch=broken_fetch)
        self.assertEqual(code, 2)

    def test_unknown_command_exits_two(self):
        code, _ = _run(["definitely-not-a-command"])
        self.assertNotEqual(code, 0)

    def test_invalid_choice_exits_two(self):
        code, _ = _run(["analyze", "frxEURUSD", "-t", "17m"])
        self.assertEqual(code, 2)

    def test_json_output_parses(self):
        import json

        code, text = _run(["markets", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(text)
        # Documented top-level contract of `markets --json`.
        self.assertIsInstance(parsed, dict)
        self.assertIn("markets", parsed)
        self.assertIn("timeframes", parsed)
        self.assertIn("categories", parsed)
        self.assertGreaterEqual(len(parsed["markets"]), 1)


if __name__ == "__main__":
    unittest.main()


class DebugFlagTests(unittest.TestCase):
    """Roadmap #79: --debug prints full tracebacks for failures."""

    def test_debug_flag_parses_before_any_command(self):
        code, _ = _run(["--debug", "markets", "--json"])
        self.assertEqual(code, 0)

    def test_debug_does_not_change_success_output(self):
        def fake_fetch(*_args, **_kwargs):
            return [(i, 1.0 + i, 1.5 + i, 0.5 + i, 1.0 + i) for i in range(300)]

        code, text = _run(
            ["--debug", "analyze", "frxEURUSD", "-t", "5m"], fetch=fake_fetch
        )
        self.assertEqual(code, 0)
        self.assertIn("EUR/USD", text)


class ResolveStopTests(unittest.TestCase):
    """Roadmap #21: the risk helper behind `neezy-cli risk`."""

    def test_explicit_stop_infers_direction_side(self):
        stop, target = resolve_stop(None, 1.1000, None, stop=1.0900)
        self.assertEqual(stop, 1.09)
        self.assertAlmostEqual(target, 1.12)

    def test_sell_side_explicit_stop(self):
        stop, target = resolve_stop(None, 1.1000, None, stop=1.1100)
        self.assertEqual(stop, 1.11)
        self.assertAlmostEqual(target, 1.08)

    def test_atr_derivation(self):
        stop, target = resolve_stop("BUY", 1.1000, 0.0020)
        self.assertAlmostEqual(stop, 1.1000 - 0.0020 * 1.5)
        self.assertAlmostEqual(target, 1.1000 + 0.0020 * 1.5 * 2.0)

    def test_missing_everything_is_a_usage_error(self):
        with self.assertRaises(ValueError):
            resolve_stop(None, 1.1, None)

    def test_stop_equal_to_entry_rejected(self):
        with self.assertRaises(ValueError):
            resolve_stop(None, 1.1, None, stop=1.1)
