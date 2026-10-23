from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from neezy_backend.executor_config import ExecutorConfig, load_executor_config

ROOT = Path(__file__).resolve().parents[1]


class ExecutorConfigTests(unittest.TestCase):
    def test_defaults_are_observer_only_and_loopback(self):
        config = ExecutorConfig()
        self.assertFalse(config.execution_enabled)
        self.assertEqual(config.status_host, "127.0.0.1")
        self.assertGreaterEqual(config.min_paper_days, 14)

    def test_public_bind_and_weakened_paper_gate_are_rejected(self):
        with self.assertRaises(ValueError):
            ExecutorConfig(status_host="0.0.0.0")
        with self.assertRaises(ValueError):
            ExecutorConfig(min_paper_days=1)
        with self.assertRaises(ValueError):
            ExecutorConfig.from_dict({"execution_enabld": True})

    def test_paper_mode_is_explicit_no_order_and_costed(self):
        with self.assertRaises(ValueError):
            ExecutorConfig(
                hf_repo_id="owner/models",
                paper_candidate="manifests/candidate.json",
                paper_spread=0.0001,
                execution_enabled=True,
            )
        with self.assertRaises(ValueError):
            ExecutorConfig(
                hf_repo_id="owner/models",
                paper_candidate="manifests/candidate.json",
            )
        config = ExecutorConfig(
            hf_repo_id="owner/models",
            paper_candidate="manifests/candidate.json",
            paper_spread=0.0001,
        )
        self.assertFalse(config.execution_enabled)

    def test_missing_default_is_safe_but_missing_explicit_path_is_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_executor_config(missing)

    def test_main_check_config_does_not_connect_to_broker(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executor.json"
            path.write_text(json.dumps({"execution_enabled": False}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "main.py", "--config", str(path), "--check-config"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["execution_enabled"])

    def test_runtime_requirements_exclude_training_libraries(self):
        runtime_lines = (
            (ROOT / "requirements-runtime.txt")
            .read_text(encoding="utf-8")
            .lower()
            .splitlines()
        )
        runtime = "\n".join(
            line for line in runtime_lines if not line.lstrip().startswith("#")
        )
        for name in ("torch", "transformers", "pandas", "tensorflow"):
            self.assertNotIn(name, runtime)
        training = (ROOT / "requirements-training.txt").read_text(encoding="utf-8")
        self.assertIn("huggingface_hub", training)


if __name__ == "__main__":
    unittest.main()
