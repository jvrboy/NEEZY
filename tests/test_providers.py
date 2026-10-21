import json
import unittest

from neezy_backend.providers import (
    PROVIDERS,
    ProviderError,
    ProviderKeyStore,
    get_candles,
    provider_key_issues,
    resolve_provider,
)


class AlphaVantagePayload:
    """A canned fake document shaped like the real FX_INTRADAY response."""

    @staticmethod
    def text() -> str:
        rows = []
        for index in range(10):
            rows.append(
                (
                    f"2026-10-20 10:{index:02d}:00",
                    {
                        "1. open": "1.0800",
                        "2. high": "1.0810",
                        "3. low": "1.0790",
                        "4. close": "1.0805",
                    },
                )
            )
        document = {"Time Series FX (5min)": dict(reversed(rows))}
        return json.dumps(document)


class ProviderCatalogTest(unittest.TestCase):
    def test_all_expected_providers_registered(self):
        self.assertEqual(
            list(PROVIDERS),
            ["deriv", "alpha_vantage", "finnhub", "binance", "twelve_data"],
        )

    def test_unknown_provider_raises_value_error(self):
        with self.assertRaises(ValueError):
            resolve_provider("nope")

    def test_symbol_translation(self):
        self.assertEqual(PROVIDERS["alpha_vantage"].translate("frxEURUSD"), "EUR/USD")
        self.assertEqual(PROVIDERS["finnhub"].translate("frxUSDJPY"), "OANDA:USD_JPY")
        self.assertEqual(PROVIDERS["twelve_data"].translate("frxEURGBP"), "EUR/GBP")
        self.assertIsNone(PROVIDERS["alpha_vantage"].translate("R_100"))
        self.assertIsNone(PROVIDERS["finnhub"].translate("1HZ100V"))

    def test_interval_mapping(self):
        self.assertEqual(PROVIDERS["binance"].interval(300), "5m")
        self.assertEqual(PROVIDERS["finnhub"].interval(3600), "60")
        self.assertEqual(PROVIDERS["alpha_vantage"].interval(900), "15min")
        with self.assertRaises(ProviderError):
            PROVIDERS["binance"].interval(60 * 2)


class PayloadParsingTest(unittest.TestCase):
    def _rows(self, payload, provider):
        spec = resolve_provider(provider)
        return spec.parse(payload)

    def test_alpha_vantage_parse(self):
        rows = self._rows(AlphaVantagePayload.text(), "alpha_vantage")
        self.assertEqual(len(rows), 10)
        _epoch, open_, high, low, close = rows[0]
        self.assertEqual((open_, high, low, close), (1.08, 1.081, 1.079, 1.0805))
        self.assertLess(rows[0][0], rows[-1][0])

    def test_alpha_vantage_note_is_an_error(self):
        payload = json.dumps({"Note": "Thank you for using Alpha Vantage!"})
        with self.assertRaisesRegex(ProviderError, "refused"):
            self._rows(payload, "alpha_vantage")

    def test_finnhub_parse(self):
        payload = json.dumps(
            {
                "s": "ok",
                "t": [1500000000, 1500000300],
                "o": [1.0, 1.1],
                "h": [1.2, 1.3],
                "l": [0.9, 1.0],
                "c": [1.05, 1.15],
            }
        )
        rows = self._rows(payload, "finnhub")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][4], 1.15)

    def test_finnhub_error_status(self):
        payload = json.dumps({"s": "no_data"})
        with self.assertRaisesRegex(ProviderError, "no candles"):
            self._rows(payload, "finnhub")

    def test_binance_parse_and_sort(self):
        payload = json.dumps(
            [
                [1500000300, "2.0", "2.1", "1.9", "2.05", "1", 0, 0, 0, 0, 0],
                [1500000000, "2.0", "2.1", "1.9", "2.05", "1", 0, 0, 0, 0, 0],
            ]
        )
        rows = self._rows(payload, "binance")
        self.assertEqual([row[0] for row in rows], [1500000000, 1500000300])

    def test_binance_dict_payload_is_refusal(self):
        payload = json.dumps({"code": -1121, "msg": "Invalid symbol."})
        with self.assertRaises(ProviderError):
            self._rows(payload, "binance")

    def test_twelve_data_parse(self):
        payload = json.dumps(
            {
                "values": [
                    {
                        "datetime": "2026-10-20 10:00:00",
                        "open": "1.1",
                        "high": "1.2",
                        "low": "1.0",
                        "close": "1.15",
                    }
                ]
            }
        )
        rows = self._rows(payload, "twelve_data")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], 1.15)

    def test_twelve_data_message_is_error(self):
        payload = json.dumps({"status": "error", "message": "missing api key"})
        with self.assertRaisesRegex(ProviderError, "refused"):
            self._rows(payload, "twelve_data")

    def test_inconsistent_ohlc_rejected(self):
        payload = json.dumps(
            [
                [1500000000, "1.0", "0.5", "1.5", "1.1"],
            ]
        )
        with self.assertRaises(ProviderError):
            self._rows(payload, "binance")


class PipelineTest(unittest.TestCase):
    def test_no_key_for_keyed_provider(self):
        store = ProviderKeyStore(
            path=ProviderKeyStore().path.parent / "definitely-absent.json"
        )
        with self.assertRaisesRegex(ProviderError, "needs an API key"):
            get_candles(
                "alpha_vantage",
                "frxEURUSD",
                "5m",
                100,
                keystore=store,
                fetcher=lambda _url: "{}",
            )

    def test_unsupported_symbol_message(self):
        with self.assertRaisesRegex(ProviderError, "does not cover"):
            get_candles(
                "binance",
                "frxEURUSD",
                "5m",
                100,
                fetcher=lambda _url: "[]",
            )

    def test_keyed_provider_sends_key_and_parses(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            store = ProviderKeyStore(path=Path(folder) / "provider-keys.json")
            store.set("alpha_vantage", "KEY123")
            captured = {}

            def fetcher(url: str) -> str:
                captured["url"] = url
                return AlphaVantagePayload.text()

            rows = get_candles(
                "alpha_vantage",
                "frxEURUSD",
                "5m",
                5,
                keystore=store,
                fetcher=fetcher,
            )
            self.assertEqual(len(rows), 5)
            self.assertEqual(captured["url"].count("apikey=KEY123"), 1)

    def test_provider_key_issues(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            store = ProviderKeyStore(path=Path(folder) / "provider-keys.json")
            self.assertIn("missing an API key", provider_key_issues("finnhub", store))
            store.set("finnhub", "tok")
            self.assertIsNone(provider_key_issues("finnhub", store))
            self.assertIsNone(provider_key_issues("binance", store))


if __name__ == "__main__":
    unittest.main()
