import unittest

from neezy_backend.catalog import (
    Instrument,
    by_market,
    instrument,
    instruments,
    markets,
)
from neezy_backend.config import AppSettings
from neezy_backend.markets import (
    DEFAULT_WATCHLIST,
    SYMBOLS,
    format_price,
    pip_size,
    price_decimals,
    watchlist,
)


class CatalogTests(unittest.TestCase):
    def test_bundled_snapshot_loads_every_instrument(self) -> None:
        catalogue = instruments()
        self.assertEqual(len(catalogue), 89)
        self.assertEqual(set(SYMBOLS), set(catalogue))
        self.assertEqual(SYMBOLS["R_100"], catalogue["R_100"].name)

    def test_categories_and_lookup(self) -> None:
        self.assertIn("synthetic_index", markets())
        self.assertIn("forex", markets())
        self.assertTrue(all(item.market == "forex" for item in by_market("forex")))
        self.assertIsNone(instrument("NOT_A_SYMBOL"))
        step = instrument("stpRNG")
        self.assertIsNotNone(step)
        self.assertEqual(step.submarket, "step_index")

    def test_decimals_come_from_tick_size(self) -> None:
        self.assertEqual(Instrument("x", "x", "m", "s", 0.00001, True).decimals, 5)
        self.assertEqual(Instrument("x", "x", "m", "s", 0.1, True).decimals, 1)
        self.assertEqual(Instrument("x", "x", "m", "s", 0.001, True).decimals, 3)

    def test_precision_and_pip_rules(self) -> None:
        self.assertEqual(price_decimals("frxEURUSD"), 5)
        self.assertEqual(price_decimals("frxUSDJPY"), 3)
        self.assertEqual(price_decimals("R_100"), 2)
        self.assertEqual(price_decimals("R_10"), 3)
        self.assertEqual(price_decimals("frxUSDMXN"), 4)
        self.assertEqual(format_price("R_10", 1234.5678), "1234.568")
        self.assertEqual(pip_size("frxEURUSD"), 0.0001)
        self.assertEqual(pip_size("frxUSDJPY"), 0.01)
        self.assertEqual(pip_size("R_100"), 0.01)
        self.assertEqual(pip_size("RB100"), 0.1)
        self.assertEqual(pip_size("frxXAUUSD"), 0.01)

    def test_unknown_symbol_keeps_legacy_rules(self) -> None:
        self.assertEqual(price_decimals("ZZZ"), 5)
        self.assertEqual(pip_size("ZZZ"), 0.0001)


class WatchlistTests(unittest.TestCase):
    def test_default_watchlist_is_the_original_eleven(self) -> None:
        self.assertEqual(len(DEFAULT_WATCHLIST), 11)
        self.assertTrue(set(DEFAULT_WATCHLIST) <= set(SYMBOLS))
        self.assertEqual(list(watchlist()), list(DEFAULT_WATCHLIST))

    def test_extras_are_appended_once(self) -> None:
        extras = watchlist("R_10, CRASH500, frxEURUSD,")
        self.assertEqual(list(extras)[-2:], ["R_10", "CRASH500"])
        self.assertEqual(len(extras), len(DEFAULT_WATCHLIST) + 2)

    def test_unknown_extra_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            watchlist("NOPE")

    def test_settings_validate_extra_markets(self) -> None:
        self.assertEqual(AppSettings().watchlist_extra, "")
        self.assertEqual(
            AppSettings(watchlist_extra="R_10,JD25").watchlist_extra, "R_10,JD25"
        )
        with self.assertRaises(ValueError):
            AppSettings(watchlist_extra="R_10,BOGUS")
        with self.assertRaises(TypeError):
            AppSettings(watchlist_extra=["R_10"])


if __name__ == "__main__":
    unittest.main()
