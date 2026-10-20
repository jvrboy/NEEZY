import unittest

from neezy_backend.ai_cache import AnswerCache
from neezy_backend.resilience import CircuitBreaker, backoff_delay


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class AnswerCacheTest(unittest.TestCase):
    def test_key_changes_with_any_input(self):
        msgs = [{"role": "user", "content": "hi"}]
        base = AnswerCache.make_key("groq", "m1", msgs)
        self.assertEqual(base, AnswerCache.make_key("groq", "m1", msgs))
        self.assertNotEqual(base, AnswerCache.make_key("groq", "m2", msgs))
        self.assertNotEqual(base, AnswerCache.make_key("groq", "m1", msgs, "sys"))

    def test_hit_miss_and_ttl(self):
        clock = FakeClock()
        cache = AnswerCache(ttl_seconds=10, clock=clock)
        self.assertIsNone(cache.get("k"))
        cache.put("k", "answer")
        self.assertEqual(cache.get("k"), "answer")
        clock.now = 11
        self.assertIsNone(cache.get("k"))
        self.assertEqual(cache.stats(), {"size": 0, "hits": 1, "misses": 2})

    def test_lru_eviction(self):
        cache = AnswerCache(max_items=2)
        cache.put("a", "1")
        cache.put("b", "2")
        cache.get("a")
        cache.put("c", "3")
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), "1")

    def test_invalid_settings(self):
        with self.assertRaises(ValueError):
            AnswerCache(max_items=0)
        with self.assertRaises(ValueError):
            AnswerCache(ttl_seconds=0)


class CircuitBreakerTest(unittest.TestCase):
    def test_opens_after_threshold_then_half_opens(self):
        clock = FakeClock()
        breaker = CircuitBreaker(2, 30, clock=clock)
        breaker.record_failure()
        self.assertTrue(breaker.allow())
        breaker.record_failure()
        self.assertEqual(breaker.state, "open")
        self.assertFalse(breaker.allow())
        clock.now = 31
        self.assertEqual(breaker.state, "half_open")
        self.assertTrue(breaker.allow())

    def test_half_open_failure_reopens_and_success_closes(self):
        clock = FakeClock()
        breaker = CircuitBreaker(1, 10, clock=clock)
        breaker.record_failure()
        clock.now = 11
        breaker.record_failure()
        self.assertEqual(breaker.state, "open")
        clock.now = 22
        breaker.record_success()
        self.assertEqual(breaker.state, "closed")

    def test_invalid_settings(self):
        with self.assertRaises(ValueError):
            CircuitBreaker(0)
        with self.assertRaises(ValueError):
            CircuitBreaker(1, 0)


class BackoffTest(unittest.TestCase):
    def test_grows_and_caps(self):
        mid = lambda: 0.5  # noqa: E731
        delays = [backoff_delay(n, rng=mid) for n in range(8)]
        self.assertEqual(delays[:3], [0.5, 1.0, 2.0])
        self.assertEqual(delays[-1], 30.0)

    def test_jitter_bounds(self):
        low = backoff_delay(2, rng=lambda: 0.0)
        high = backoff_delay(2, rng=lambda: 1.0)
        self.assertAlmostEqual(low, 2.0 * 0.8)
        self.assertAlmostEqual(high, 2.0 * 1.2)

    def test_negative_attempt(self):
        with self.assertRaises(ValueError):
            backoff_delay(-1)


if __name__ == "__main__":
    unittest.main()
