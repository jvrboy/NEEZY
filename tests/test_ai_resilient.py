import json
import tempfile
import unittest
from pathlib import Path

from neezy_backend.ai import AIError, AIKeyStore, AllKeysFailed
from neezy_backend.ai_resilient import ResilientAIClient
from neezy_backend.resilience import CircuitBreaker

OK = json.dumps(
    {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
).encode()
LONG = [{"role": "user", "content": "x" * 120}]
SHORT = [{"role": "user", "content": "Reply with the single word OK."}]


class Transport:
    def __init__(self, status=200, payload=OK):
        self.calls = 0
        self.status = status
        self.payload = payload

    def __call__(self, url, headers, body, timeout):
        self.calls += 1
        return self.status, self.payload


class ResilientClientTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = AIKeyStore(Path(self._tmp.name) / "keys.json")
        self.store.add("openrouter", "sk-or-1234567890", "main")

    def test_long_prompts_are_cached(self):
        transport = Transport()
        client = ResilientAIClient(self.store, transport=transport)
        first = client.chat("openrouter", LONG)
        second = client.chat("openrouter", LONG)
        self.assertEqual(transport.calls, 1)
        self.assertEqual(first.text, second.text)
        self.assertEqual(second.key_label, "cache")

    def test_short_prompts_always_reach_provider(self):
        transport = Transport()
        client = ResilientAIClient(self.store, transport=transport)
        client.chat("openrouter", SHORT)
        client.chat("openrouter", SHORT)
        self.assertEqual(transport.calls, 2)

    def test_changed_settings_miss_the_cache(self):
        transport = Transport()
        client = ResilientAIClient(self.store, transport=transport)
        client.chat("openrouter", LONG, temperature=0.1)
        client.chat("openrouter", LONG, temperature=0.9)
        self.assertEqual(transport.calls, 2)

    def test_breaker_opens_after_all_keys_fail(self):
        transport = Transport(status=500, payload=b"boom")
        client = ResilientAIClient(
            self.store,
            transport=transport,
            breaker_factory=lambda: CircuitBreaker(1, 60),
        )
        with self.assertRaises(AllKeysFailed):
            client.chat("openrouter", SHORT)
        with self.assertRaisesRegex(AIError, "paused"):
            client.chat("openrouter", SHORT)
        self.assertEqual(transport.calls, 1)

    def test_cache_still_served_while_paused(self):
        transport = Transport()
        client = ResilientAIClient(
            self.store,
            transport=transport,
            breaker_factory=lambda: CircuitBreaker(1, 60),
        )
        client.chat("openrouter", LONG)
        client.breaker("openrouter").record_failure()
        self.assertEqual(client.chat("openrouter", LONG).key_label, "cache")


if __name__ == "__main__":
    unittest.main()
