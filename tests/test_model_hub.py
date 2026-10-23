from __future__ import annotations

import copy
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from neezy_backend.model_hub import (
    HuggingFaceDownloader,
    ModelUpdateError,
    ModelUpdateManager,
    _SafeRedirectHandler,
    attach_paper_evidence,
    evaluate_model_gate,
    latest_manifest_path,
    safe_repo_path,
)
from tests.cloud_fixtures import model_and_manifest


class FakeDownloader:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def download(self, path, *, max_bytes):
        self.calls.append(path)
        content = self.files[path]
        if len(content) > max_bytes:
            raise ModelUpdateError("too large")
        return content


def encoded(document):
    return json.dumps(document, allow_nan=False).encode()


class ModelGateTests(unittest.TestCase):
    def test_candidate_is_not_promotable_without_paper_evidence(self):
        model, _content, manifest = model_and_manifest(paper=False)
        issues = evaluate_model_gate(
            model, manifest, symbol="frxEURUSD", timeframe="15m"
        )
        self.assertTrue(any("paper-trading" in issue for issue in issues))

    def test_paper_mode_defers_only_paper_not_backtest_or_metric_gates(self):
        model, _content, manifest = model_and_manifest(paper=False)
        self.assertEqual(
            evaluate_model_gate(
                model,
                manifest,
                symbol="frxEURUSD",
                timeframe="15m",
                require_paper=False,
            ),
            [],
        )
        manifest["validation"]["backtest"]["passed"] = False
        issues = evaluate_model_gate(
            model,
            manifest,
            symbol="frxEURUSD",
            timeframe="15m",
            require_paper=False,
        )
        self.assertIn("held-out trade backtest has not passed", issues)

    def test_exact_hash_backtest_and_paper_evidence_passes(self):
        model, _content, manifest = model_and_manifest()
        self.assertEqual(
            evaluate_model_gate(model, manifest, symbol="frxEURUSD", timeframe="15m"),
            [],
        )

    def test_paper_report_for_another_model_is_rejected(self):
        _model, _content, manifest = model_and_manifest(paper=False)
        with self.assertRaisesRegex(ValueError, "different|hash"):
            attach_paper_evidence(
                manifest,
                {"passed": True, "trades": 30, "days": 20, "model_sha256": "0" * 64},
            )

    def test_wrong_symbol_and_weak_metrics_fail_closed(self):
        model, _content, manifest = model_and_manifest()
        broken = copy.deepcopy(model)
        broken["symbol"] = "frxGBPUSD"
        broken["test_metrics"]["balanced_accuracy"] = 0.51
        issues = evaluate_model_gate(
            broken, manifest, symbol="frxEURUSD", timeframe="15m"
        )
        self.assertTrue(any("not for frxEURUSD" in issue for issue in issues))
        self.assertTrue(any("balanced accuracy" in issue for issue in issues))

    def test_nonpositive_backtest_expectancy_is_rejected(self):
        model, _content, manifest = model_and_manifest()
        manifest["validation"]["backtest"]["expectancy_r"] = 0
        issues = evaluate_model_gate(
            model, manifest, symbol="frxEURUSD", timeframe="15m"
        )
        self.assertIn(
            "backtest expectancy must be positive after assumed costs", issues
        )

    def test_repository_paths_cannot_traverse(self):
        for path in ("../secret", "/tmp/model", "models/..\\x", "models//x"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_repo_path(path)
        self.assertEqual(
            latest_manifest_path("frxEURUSD", "15m"), "latest/frxEURUSD/15m.json"
        )


class HuggingFaceDownloaderTests(unittest.TestCase):
    def test_url_is_fixed_to_hf_and_does_not_contain_token(self):
        downloader = HuggingFaceDownloader("owner/models", token="secret-token")
        url = downloader.url_for("latest/frxEURUSD/15m.json")
        self.assertEqual(
            url,
            "https://huggingface.co/owner/models/resolve/main/latest/frxEURUSD/15m.json",
        )
        self.assertNotIn("secret-token", url)

    def test_cross_host_redirect_strips_authorization(self):
        request = urllib.request.Request(
            "https://huggingface.co/owner/models/resolve/main/model.json",
            headers={"Authorization": "Bearer secret-token"},
        )
        redirected = _SafeRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://cdn.example.test/signed-model",
        )
        self.assertIsNone(redirected.get_header("Authorization"))


class ModelUpdateManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def manager(self, files):
        return ModelUpdateManager(
            self.root,
            symbol="frxEURUSD",
            timeframe="15m",
            downloader=FakeDownloader(files),
        )

    def test_valid_update_activates_and_survives_reload(self):
        _model, content, manifest = model_and_manifest()
        manager = self.manager(
            {manager_path(manifest): encoded(manifest), manifest["model_file"]: content}
        )
        result = manager.check_for_update()
        self.assertEqual(result["status"], "activated")
        active = manager.load_active()
        self.assertEqual(active["manifest"]["model_id"], manifest["model_id"])
        self.assertEqual(manager.check_for_update()["status"], "unchanged")

    def test_rejected_candidate_preserves_previous_model(self):
        first = model_and_manifest()
        second = model_and_manifest(
            model_id="frxeurusd-15m-20261024t000000z-123456abcdef",
            paper=False,
        )
        path = latest_manifest_path("frxEURUSD", "15m")
        manager = self.manager(
            {path: encoded(first[2]), first[2]["model_file"]: first[1]}
        )
        self.assertEqual(manager.check_for_update()["status"], "activated")

        manager.downloader.files = {
            path: encoded(second[2]),
            second[2]["model_file"]: second[1],
        }
        result = manager.check_for_update()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(manager.load_active()["manifest"], first[2])

    def test_hash_mismatch_preserves_previous_model(self):
        first = model_and_manifest()
        second = model_and_manifest(
            model_id="frxeurusd-15m-20261024t000000z-123456abcdef"
        )
        path = latest_manifest_path("frxEURUSD", "15m")
        manager = self.manager(
            {path: encoded(first[2]), first[2]["model_file"]: first[1]}
        )
        manager.check_for_update()
        manager.downloader.files = {
            path: encoded(second[2]),
            second[2]["model_file"]: second[1] + b"tampered",
        }
        result = manager.check_for_update()
        self.assertEqual(result["status"], "rejected")
        self.assertIn("hash", result["issues"][0])
        self.assertEqual(manager.load_active()["manifest"], first[2])

    def test_malformed_new_manifest_does_not_delete_active_file(self):
        _model, content, manifest = model_and_manifest()
        path = latest_manifest_path("frxEURUSD", "15m")
        manager = self.manager(
            {path: encoded(manifest), manifest["model_file"]: content}
        )
        manager.check_for_update()
        active_path = manager.directory / "released" / f"{manifest['model_id']}.json"
        before = active_path.read_bytes()
        manager.downloader.files = {path: b"not-json"}
        with self.assertRaises(ModelUpdateError):
            manager.check_for_update()
        self.assertEqual(active_path.read_bytes(), before)
        self.assertEqual(manager.load_active()["content"], content)


def manager_path(_manifest):
    return latest_manifest_path("frxEURUSD", "15m")


if __name__ == "__main__":
    unittest.main()
