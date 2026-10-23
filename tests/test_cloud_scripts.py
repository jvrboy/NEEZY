from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import cloud_data_pull, cloud_train, promote_model
from tests.cloud_fixtures import candles, model_and_manifest
from tests.test_brain import _candles as research_candles


class CloudCandidateScriptTests(unittest.TestCase):
    def test_training_creates_candidate_without_latest_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                cloud_train, "fetch_history", return_value=research_candles(800)
            ):
                artifact = cloud_train.train_candidate(
                    "frxEURUSD",
                    timeframe="15m",
                    candles=800,
                    epochs=1,
                    horizon=5,
                    min_samples=60,
                    seed=17,
                    minimum_probability=0.60,
                    spread=0.0001,
                    min_backtest_trades=20,
                    output=Path(directory),
                )
            manifest = json.loads(artifact["manifest_content"])
            model = json.loads(artifact["model_content"])
            self.assertEqual(manifest["validation"]["paper_trade"]["passed"], False)
            self.assertEqual(
                manifest["model_sha256"],
                hashlib.sha256(artifact["model_content"]).hexdigest(),
            )
            self.assertEqual(model["symbol"], "frxEURUSD")
            self.assertTrue((artifact["directory"] / "manifest.json").is_file())
            self.assertTrue((artifact["directory"] / "dataset.json").is_file())
            self.assertNotIn("latest/", manifest["model_file"])


class CloudDataScriptTests(unittest.TestCase):
    def test_data_pull_writes_public_dataset_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(cloud_data_pull, "_r2_settings", return_value={}),
                mock.patch.object(
                    cloud_data_pull, "fetch_history", return_value=candles(120)
                ),
            ):
                result = cloud_data_pull.main(
                    [
                        "--symbols",
                        "frxEURUSD",
                        "--timeframe",
                        "15m",
                        "--candles",
                        "120",
                        "--output",
                        directory,
                    ]
                )
            self.assertEqual(result, 0)
            files = list(Path(directory).glob("frxEURUSD/15m/*.json"))
            self.assertEqual(len(files), 1)
            document = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(document["candle_count"], 120)
            self.assertNotIn("HF_TOKEN", document)


class PromotionScriptTests(unittest.TestCase):
    def test_dry_run_promotes_only_after_exact_hash_paper_report(self):
        model, content, manifest = model_and_manifest(paper=False)
        paper = {
            "passed": True,
            "trades": 30,
            "days": 14,
            "model_sha256": manifest["model_sha256"],
        }

        class Downloader:
            def __init__(self, *_args, **_kwargs):
                pass

            def download(self, path, *, max_bytes):
                del max_bytes
                if path == "manifests/candidate.json":
                    return json.dumps(manifest).encode()
                if path == manifest["model_file"]:
                    return content
                raise AssertionError(path)

        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "paper.json"
            output = Path(directory) / "latest.json"
            report.write_text(json.dumps(paper), encoding="utf-8")
            with mock.patch.object(promote_model, "HuggingFaceDownloader", Downloader):
                result = promote_model.main(
                    [
                        "--hf-model-repo",
                        "owner/models",
                        "--candidate",
                        "manifests/candidate.json",
                        "--paper-report",
                        str(report),
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(result, 0)
            promoted = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(promoted["validation"]["paper_trade"]["passed"])
            self.assertEqual(promoted["model_sha256"], manifest["model_sha256"])
            self.assertEqual(model["symbol"], promoted["symbol"])


if __name__ == "__main__":
    unittest.main()
