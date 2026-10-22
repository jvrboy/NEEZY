"""Provider HTTP failure matrix tests (roadmap update #54).

Every failure shape a provider can produce must surface as a typed
`ProviderError` whose message never contains the API key.
"""

import io
import unittest
import unittest.mock
from urllib.error import HTTPError, URLError

from neezy_backend.providers import (
    ProviderError,
    _check_candles,
    _http_get,
    resolve_provider,
)


def _fake_urlopen_factory(
    status: int | None = None,
    body: bytes = b"{}",
    error: Exception | None = None,
    delay: float = 0.0,
):
    response_status = 200 if status is None else status

    class _Response(io.BytesIO):
        pass

    def fake_urlopen(request, timeout=None):
        import time

        if delay:
            time.sleep(delay)
        if error is not None:
            raise error
        response = _Response(body)
        response.status = response_status
        return response

    return fake_urlopen


class HttpGetFailureMatrixTests(unittest.TestCase):
    def _patch(self, **kwargs):
        return unittest.mock.patch(
            "urllib.request.urlopen", _fake_urlopen_factory(**kwargs)
        )

    def test_http_4xx_maps_to_provider_error(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                error = HTTPError(
                    "https://api.example.com/data?apikey=SECRET",
                    status,
                    "reason",
                    None,
                    None,
                )
                with self._patch(error=error):
                    with self.assertRaises(ProviderError) as raised:
                        _http_get("https://api.example.com/data?apikey=SECRET")
                self.assertNotIn("SECRET", str(raised.exception))

    def test_network_failure_maps_to_provider_error(self):
        with self._patch(error=URLError("connection refused")):
            with self.assertRaises(ProviderError) as raised:
                _http_get("https://api.example.com/x")
        self.assertIn("failed", str(raised.exception))

    def test_timeout_maps_to_provider_error(self):

        with self._patch(error=TimeoutError("timed out")):
            with self.assertRaises(ProviderError):
                _http_get("https://api.example.com/x", timeout=0.2)

    def test_key_never_leaks_into_error_message(self):
        url = "https://api.example.com/v1/candles?apikey=SUPERSECRET&symbol=X"
        with self._patch(error=URLError("reset by peer")):
            with self.assertRaises(ProviderError) as raised:
                _http_get(url)
        self.assertNotIn("SUPERSECRET", str(raised.exception))
        self.assertNotIn("apikey", str(raised.exception))

    def test_non_200_status_is_an_error(self):
        error = HTTPError("https://api.example.com/x", 500, "boom", None, None)
        with self._patch(error=error):
            with self.assertRaises(ProviderError):
                _http_get("https://api.example.com/x")


class CandleValidationMatrixTests(unittest.TestCase):
    def test_non_list_payload_is_refused(self):
        for bad in ("string", 42, {"a": 1}, None):
            with self.subTest(bad=bad):
                with self.assertRaises(ProviderError):
                    _check_candles(bad, "test")

    def test_malformed_rows_are_refused(self):
        for bad in (
            [[1, 2]],  # short row
            [["a", 2, 3, 4, 5]],  # non-numeric epoch
            [[0, 1, 2, 3, 4]],  # zero epoch
            [[1, 0, 2, 3, 4]],  # zero open
            [[1, 4, 2, 3, 4]],  # low > high
            [[1, 2, 3, 4, "close"]],  # non-numeric close
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ProviderError):
                    _check_candles([list(bad[0])], "test")

    def test_empty_list_is_valid_empty(self):
        self.assertEqual(_check_candles([], "test"), [])

    def test_valid_row_passes(self):
        candles = _check_candles([[1700000000, 1.1, 1.2, 1.0, 1.15]], "test")
        self.assertEqual(len(candles), 1)


class UnknownProviderTests(unittest.TestCase):
    def test_unknown_provider_name_is_refused(self):
        with self.assertRaises(ValueError):
            resolve_provider("nope")


if __name__ == "__main__":
    unittest.main()
