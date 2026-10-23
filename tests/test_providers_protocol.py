"""Tests for standard Provider protocol compliance in neezy_backend.providers."""

from __future__ import annotations

import unittest
from unittest import mock

from neezy_backend.providers import (
    PROVIDERS,
    Provider,
    ProviderKeyStore,
    resolve_provider,
)


class ProviderProtocolTests(unittest.TestCase):
    def test_providers_conform_to_provider_protocol(self) -> None:
        for name, spec in PROVIDERS.items():
            self.assertTrue(
                isinstance(spec, Provider),
                f"ProviderSpec {name} does not satisfy Provider Protocol",
            )

    def test_resolve_provider_returns_provider_protocol(self) -> None:
        provider = resolve_provider("binance")
        self.assertTrue(isinstance(provider, Provider))
        self.assertEqual(provider.key, "binance")

    def test_provider_health_check_ok(self) -> None:
        provider = resolve_provider("binance")
        canned_binance_response = (
            '[[1700000000, "100.0", "105.0", "95.0", "102.0", "1000"]]'
        )
        health = provider.health(
            "frxBTCUSD",
            "15m",
            fetcher=lambda _url: canned_binance_response,
        )
        self.assertTrue(health["ok"])
        self.assertEqual(health["provider"], "binance")
        self.assertEqual(health["candle_count"], 1)

    def test_provider_health_check_missing_key(self) -> None:
        provider = resolve_provider("finnhub")
        keystore = mock.Mock(spec=ProviderKeyStore)
        keystore.get.return_value = ""
        health = provider.health(keystore=keystore)
        self.assertFalse(health["ok"])
        self.assertIn("API key", health["error"])

    def test_provider_fetch_candles_via_protocol(self) -> None:
        provider = resolve_provider("binance")
        canned_binance_response = (
            '[[1700000000, "100.0", "105.0", "95.0", "102.0", "1000"]]'
        )
        candles = provider.fetch_candles(
            "frxBTCUSD",
            "15m",
            count=10,
            fetcher=lambda _url: canned_binance_response,
        )
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0][0], 1700000000)


if __name__ == "__main__":
    unittest.main()
