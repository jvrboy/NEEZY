"""Fuzz tests for the websocket boundary parsers (roadmap #38).

Seeded random mutation of valid candle and history payloads: every mutant
must fail as a ``ValueError`` or ``RuntimeError`` — never an arbitrary
``KeyError``, ``TypeError``, ``AttributeError``, or a silent wrong answer.
Deterministic: fixed seeds, no network, well under a second per test.
"""

from __future__ import annotations

import math
import random
import unittest

from neezy_backend.stream import parse_candle, parse_history_response

ALLOWED_EXCEPTIONS = (ValueError, RuntimeError)
SEEDS = range(1, 26)

_BAD_VALUES = [
    None,
    "",
    "abc",
    "1.2.3",
    [],
    {},
    True,
    -1,
    0,
    -0.0,
    float("nan"),
    float("inf"),
    -float("inf"),
    1e308 * 10,  # overflow to inf via multiplication
    "1e999",
]

# Values that can never coerce into a valid candle (bools coerce: True -> 1.0).
_STRICTLY_INVALID = [value for value in _BAD_VALUES if value is not True]


def valid_candle(rng: random.Random) -> dict[str, object]:
    """A random but structurally valid Deriv candle payload."""
    open_ = round(rng.uniform(0.5, 2.0), 5)
    close = round(open_ + rng.uniform(-0.01, 0.01), 5)
    high = round(max(open_, close) + rng.uniform(0.0001, 0.005), 5)
    low = round(min(open_, close) - rng.uniform(0.0001, 0.005), 5)
    return {
        "epoch": rng.randrange(1_600_000_000, 1_800_000_000),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }


class ParseCandleFuzzTests(unittest.TestCase):
    """Mutated candles must raise ValueError, never anything else."""

    def test_valid_candles_always_parse(self) -> None:
        """Sanity: the generator itself produces accepted rows."""
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(200):
                row = valid_candle(rng)
                parsed = parse_candle(row)
                self.assertEqual(len(parsed), 5)
                self.assertGreater(parsed[1], 0)

    def test_field_value_mutations_never_corrupt_the_parser(self) -> None:
        """Junk field values either raise or coerce to a still-valid row.

        Python coerces some junk (``True`` -> ``1.0``, ``1`` -> ``1.0``), so
        the contract is: ``parse_candle`` raises ``ValueError``/``RuntimeError``
        OR returns a row that is finite, positive, and internally consistent.
        Anything else (OverflowError, TypeError, a corrupt row) is a bug.
        """
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(120):
                row = valid_candle(rng)
                key = rng.choice(("epoch", "open", "high", "low", "close"))
                row[key] = rng.choice(_BAD_VALUES)
                with self.subTest(seed=seed, row=row):
                    try:
                        parsed = parse_candle(row)
                    except ALLOWED_EXCEPTIONS:
                        continue
                    self.assertEqual(len(parsed), 5)
                    _, o, h, low_v, c = parsed
                    self.assertTrue(
                        all(math.isfinite(v) and v > 0 for v in (o, h, low_v, c)),
                        f"non-finite/non-positive row accepted: {parsed!r}",
                    )
                    self.assertGreaterEqual(h, max(o, c))
                    self.assertLessEqual(low_v, min(o, c))
                    self.assertLessEqual(low_v, h)

    def test_missing_fields_raise_value_error(self) -> None:
        """Dropping any required key must raise ValueError, not KeyError."""
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(120):
                row = valid_candle(rng)
                key = rng.choice(("epoch", "open", "high", "low", "close"))
                del row[key]
                with self.subTest(seed=seed, missing=key):
                    with self.assertRaises(ValueError):
                        parse_candle(row)

    def test_structure_mutations_raise_value_error(self) -> None:
        """Non-mapping candles and wrong-typed shapes must fail cleanly."""
        mutants: list[object] = [
            None,
            42,
            "candle",
            [],
            [1, 2, 3, 4, 5],
            (),
            set(),
            b"bytes",
        ]
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(40):
                mutants.append(valid_candle(rng) | {"open": [1.0]})
        for mutant in mutants:
            with self.subTest(mutant=repr(mutant)[:60]):
                with self.assertRaises(ValueError):
                    parse_candle(mutant)  # type: ignore[arg-type]

    def test_ohlc_consistency_mutations_raise_value_error(self) -> None:
        """Swapping/scaling fields must never yield a silently wrong row."""
        for seed in SEEDS:
            rng = random.Random(seed)
            for _ in range(120):
                row = valid_candle(rng)
                mutation = rng.randrange(4)
                if mutation == 0:
                    row["high"], row["low"] = row["low"], row["high"]
                elif mutation == 1:
                    row["high"] = row["low"]
                elif mutation == 2:
                    row["low"] = row["high"] = row["close"] = row["open"] * 1.0000001
                else:
                    row["close"] = (row["high"] + row["low"]) * 2
                try:
                    parsed = parse_candle(row)
                except ALLOWED_EXCEPTIONS:
                    continue
                # If it parsed, it must still be internally consistent.
                _, o, h, low_v, c = parsed
                self.assertGreaterEqual(h, max(o, c))
                self.assertLessEqual(low_v, min(o, c))
                self.assertLessEqual(low_v, h)
                self.assertTrue(
                    all(math.isfinite(v) and v > 0 for v in (o, h, low_v, c))
                )


class ParseHistoryResponseFuzzTests(unittest.TestCase):
    """Mutated history payloads must raise ValueError/RuntimeError."""

    def _payload(self, rng: random.Random, count: int = 5) -> dict[str, object]:
        return {"candles": [valid_candle(rng) for _ in range(count)]}

    def test_valid_payloads_parse(self) -> None:
        """Sanity: generated payloads are accepted and sorted by epoch."""
        for seed in SEEDS:
            rng = random.Random(seed)
            rows = parse_history_response(self._payload(rng, 20))
            self.assertEqual(len(rows), 20)
            self.assertEqual(rows, sorted(rows))

    def test_top_level_mutations_raise(self) -> None:
        """Non-object payloads and broken candles lists fail cleanly."""
        mutants: list[object] = [
            None,
            [],
            "x",
            7,
            {},
            {"candles": None},
            {"candles": {}},
            {"candles": "rows"},
            {"candles": 5},
        ]
        for mutant in mutants:
            with self.subTest(mutant=repr(mutant)[:40]):
                with self.assertRaises(ALLOWED_EXCEPTIONS):
                    parse_history_response(mutant)  # type: ignore[arg-type]

    def test_one_corrupt_candle_fails_the_whole_payload(self) -> None:
        """All-or-nothing: any strictly-corrupt row rejects the payload."""
        for seed in SEEDS:
            rng = random.Random(seed)
            payload = self._payload(rng, 8)
            assert isinstance(payload["candles"], list)
            victim = rng.randrange(len(payload["candles"]))
            payload["candles"][victim] = rng.choice(_STRICTLY_INVALID)  # type: ignore[index]
            with self.subTest(seed=seed, victim=victim):
                with self.assertRaises(ALLOWED_EXCEPTIONS):
                    parse_history_response(payload)

    def test_error_object_shapes_raise_allowed(self) -> None:
        """API error shapes fail within the allowed exception set.

        Truthy error objects map to ``RuntimeError`` (Deriv API error);
        falsy ones (``{}``, ``None``, ``[]``) fall through to the
        missing-candles ``ValueError`` — pinned current behaviour.
        """
        truthy = [
            {"error": {"message": "rate limited"}},
            {"error": "plain failure"},
            {"error": {"code": "InvalidSymbol"}},
        ]
        for shape in truthy:
            with self.subTest(shape=repr(shape)[:40]):
                with self.assertRaises(RuntimeError):
                    parse_history_response(shape)
        falsy = [{"error": {}}, {"error": None}, {"error": []}]
        for shape in falsy:
            with self.subTest(shape=repr(shape)[:40]):
                with self.assertRaises(ValueError):
                    parse_history_response(shape)

    def test_duplicate_epochs_collapse_deterministically(self) -> None:
        """Duplicate epochs dedupe to one row (pinned current behavior)."""
        rng = random.Random(99)
        row = valid_candle(rng)
        twin = dict(row) | {"close": row["close"]}  # same epoch, same values
        rows = parse_history_response({"candles": [dict(row), twin]})
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
