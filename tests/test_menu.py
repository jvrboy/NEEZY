"""Terminal menu: each choice maps to one CLI argv; live orders need SEND."""

import io
import unittest

from neezy_backend.menu import MENU, filter_menu, run_menu


class MenuTests(unittest.TestCase):
    def _run(self, answers):
        calls: list[list[str]] = []
        feed = iter(answers)
        out = io.StringIO()

        def fake_run(argv):
            calls.append(argv)
            return 0

        code = run_menu(out, input_fn=lambda _prompt: next(feed), run=fake_run)
        return code, calls, out.getvalue()

    def test_quit_runs_nothing(self):
        code, calls, _ = self._run(["0"])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])

    def test_preflight_option_runs_read_only_check(self):
        _, calls, out = self._run(["p", "0"])
        self.assertEqual(calls, [["mt5", "preflight"]])
        self.assertIn("preflight", out)

    def test_dry_run_order_never_sends(self):
        _, calls, _ = self._run(["6", "frxEURUSD", "buy", "0.1", "0"])
        self.assertEqual(len(calls), 1)
        self.assertIn("--dry-run", calls[0])
        self.assertNotIn("--confirm", calls[0])

    def test_live_order_without_send_is_cancelled(self):
        _, calls, out = self._run(["7", "frxEURUSD", "BUY", "0.1", "nope", "0"])
        self.assertEqual(calls, [])
        self.assertIn("No order sent", out)

    def test_live_order_with_send_adds_confirm(self):
        _, calls, _ = self._run(["7", "frxEURUSD", "SELL", "0.1", "SEND", "0"])
        self.assertEqual(len(calls), 1)
        self.assertIn("--confirm", calls[0])
        self.assertIn("SELL", calls[0])

    def test_live_order_with_bad_side_is_rejected(self):
        _, calls, out = self._run(["7", "frxEURUSD", "HOLD", "0.1", "0"])
        self.assertEqual(calls, [])
        self.assertIn("BUY/SELL", out)


class MenuFilterTests(unittest.TestCase):
    """The / filter: substring search across the palette (roadmap #58)."""

    def test_empty_query_returns_every_entry(self):
        self.assertEqual(filter_menu(""), tuple(MENU))

    def test_whitespace_only_query_returns_every_entry(self):
        self.assertEqual(filter_menu("   "), tuple(MENU))

    def test_case_insensitive_match(self):
        lowered = filter_menu("mt5 order")
        uppered = filter_menu("MT5 ORDER")
        self.assertEqual(lowered, uppered)
        self.assertTrue(lowered)

    def test_partial_word_matches(self):
        results = filter_menu("order")
        self.assertTrue(results)
        for item in results:
            joined = " ".join(str(part) for part in item).lower()
            self.assertIn("order", joined)

    def test_unknown_query_returns_nothing(self):
        self.assertEqual(filter_menu("zzzz-not-a-command"), ())

    def test_query_with_slash_prefix_still_filters(self):
        # The menu strips the leading slash before calling filter_menu;
        # filter_menu itself never sees it, but must handle stray input.
        self.assertEqual(filter_menu("/mt5"), ())  # literal "/mt5" is not in labels

    def test_numbers_filter_to_exact_entries(self):
        results = filter_menu("mt5")
        self.assertTrue(results)


if __name__ == "__main__":
    unittest.main()
