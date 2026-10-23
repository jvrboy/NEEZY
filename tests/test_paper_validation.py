from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from neezy_backend.model_hub import (
    ModelUpdateError,
    attach_paper_evidence,
    evaluate_model_gate,
)
from neezy_backend.paper_validation import PaperValidator, load_paper_candidate
from tests.cloud_fixtures import candles, model_and_manifest, valid_model


def next_rows(rows):
    last = rows[-1]
    open_ = last[4]
    close = open_ + 0.0002
    following = (
        int(last[0]) + 900,
        open_,
        max(open_, close) + 0.0002,
        min(open_, close) - 0.0002,
        close,
    )
    return [*rows[1:], following]


class FakeDownloader:
    def __init__(self, files):
        self.files = files

    def download(self, path, *, max_bytes):
        content = self.files[path]
        if len(content) > max_bytes:
            raise ModelUpdateError("too large")
        return content


class PaperCandidateLoadTests(unittest.TestCase):
    def test_unpromoted_candidate_passes_only_nonpaper_gates(self):
        _model, content, manifest = model_and_manifest(paper=False)
        path = f"manifests/{manifest['model_id']}.json"
        downloader = FakeDownloader(
            {path: json.dumps(manifest).encode(), manifest["model_file"]: content}
        )
        artifact = load_paper_candidate(downloader, path, timeframe="15m")
        self.assertEqual(artifact["manifest"]["model_id"], manifest["model_id"])

        downloader.files[manifest["model_file"]] = content + b"tampered"
        with self.assertRaisesRegex(ModelUpdateError, "hash"):
            load_paper_candidate(downloader, path, timeframe="15m")


class PaperValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        model = valid_model()
        model["horizon"] = 1
        self.model, self.content, self.manifest = model_and_manifest(
            paper=False, model=model
        )

    def tearDown(self):
        self.temporary.cleanup()

    def validator(self, *, min_trades=2, min_days=14):
        return PaperValidator(
            self.model,
            self.manifest,
            state_path=self.root / "paper-state.json",
            report_path=self.root / "paper-report.json",
            minimum_probability=0.60,
            spread=0.00001,
            stop_atr_multiple=1.5,
            reward_to_risk=2.0,
            min_trades=min_trades,
            min_days=min_days,
            clock=lambda: self.now,
        )

    def test_exact_hash_report_becomes_promotable_only_after_thresholds(self):
        validator = self.validator()
        rows = candles()
        first = validator.update(rows)
        self.assertEqual(first["trades"], 0)
        self.assertFalse(first["passed"])
        self.assertTrue(first["open_simulation"])

        second = validator.update(next_rows(rows))
        self.assertEqual(second["trades"], 1)
        self.assertFalse(second["passed"])
        self.now += timedelta(days=14)
        third = validator.update(next_rows(next_rows(rows)))
        self.assertEqual(third["days"], 14)
        self.assertEqual(third["trades"], 2)
        self.assertGreater(third["expectancy_r"], 0)
        self.assertTrue(third["passed"])

        saved = json.loads((self.root / "paper-report.json").read_text())
        self.assertEqual(saved["model_sha256"], self.manifest["model_sha256"])
        promoted = attach_paper_evidence(self.manifest, saved)
        self.assertEqual(
            evaluate_model_gate(
                self.model,
                promoted,
                symbol="frxEURUSD",
                timeframe="15m",
                min_paper_trades=2,
            ),
            [],
        )

    def test_restart_deduplicates_candles_and_preserves_open_simulation(self):
        rows = candles()
        validator = self.validator()
        validator.update(rows)
        restored = self.validator()
        unchanged = restored.update(rows)
        self.assertEqual(unchanged["trades"], 0)
        self.assertTrue(unchanged["open_simulation"])

        advanced = next_rows(rows)
        closed = restored.update(advanced)
        self.assertEqual(closed["trades"], 1)
        self.assertEqual(restored.update(advanced)["trades"], 1)

    def test_missing_candle_window_fails_instead_of_fabricating_outcomes(self):
        validator = self.validator()
        rows = candles()
        validator.update(rows)
        far_future = [(row[0] + 1_000_000, *row[1:]) for row in rows]
        with self.assertRaisesRegex(ValueError, "gap"):
            validator.update(far_future)

    def test_corrupt_or_different_candidate_state_is_not_reset(self):
        validator = self.validator()
        validator.update(candles())
        (self.root / "paper-state.json").write_text("not-json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "refusing to reset"):
            self.validator()

        (self.root / "paper-state.json").unlink()
        validator = self.validator()
        validator.update(candles())
        other_model = valid_model(bias_out=19.0)
        other_model["horizon"] = 1
        _model, _content, other_manifest = model_and_manifest(
            model_id="frxeurusd-15m-20261024t000000z-123456abcdef",
            paper=False,
            model=other_model,
        )
        with self.assertRaisesRegex(ValueError, "another candidate"):
            PaperValidator(
                other_model,
                other_manifest,
                state_path=self.root / "paper-state.json",
                report_path=self.root / "other-report.json",
                minimum_probability=0.60,
                spread=0.00001,
                stop_atr_multiple=1.5,
                reward_to_risk=2.0,
                min_trades=2,
                min_days=14,
                clock=lambda: self.now,
            )


if __name__ == "__main__":
    unittest.main()
