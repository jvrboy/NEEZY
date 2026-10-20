"""Tests for local model inventory and bounded, optional inference runtimes."""

from __future__ import annotations

import contextlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend.local_llm import (
    LocalModel,
    LocalModelError,
    LocalModelRegistry,
    generate_chat,
)


class LocalModelRegistryTests(unittest.TestCase):
    def test_registers_gguf_by_reference_and_removes_index_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weights = root / "tiny.gguf"
            weights.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(64))
            registry = LocalModelRegistry(root / "index.json")

            first = registry.register(weights)
            duplicate = registry.register(weights)
            self.assertEqual(first, duplicate)
            self.assertEqual(first.format, "gguf")
            self.assertEqual(first.size_bytes, weights.stat().st_size)
            self.assertEqual(registry.list_models(), [first])

            removed = registry.remove(first.model_id)
            self.assertEqual(removed, first)
            self.assertTrue(weights.is_file())
            self.assertEqual(registry.list_models(), [])

    def test_registers_complete_safetensors_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text(
                json.dumps({"model_type": "tiny-test"}), encoding="utf-8"
            )
            (root / "tokenizer.json").write_text("{}", encoding="utf-8")
            (root / "model.safetensors").write_bytes(b"safe-weights")
            registry = LocalModelRegistry(root / "index.json")

            model = registry.register(root)
            self.assertEqual(model.format, "safetensors")
            self.assertEqual(model.model_type, "tiny-test")
            self.assertEqual(model.path, str(root.resolve()))
            self.assertEqual(registry.get(model.model_id), model)

    def test_rejects_bad_gguf_and_incomplete_transformers_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bad_file = root / "bad.gguf"
            bad_file.write_bytes(b"nope")
            registry = LocalModelRegistry(root / "index.json")
            with self.assertRaises(LocalModelError):
                registry.register(bad_file)

            model_dir = root / "incomplete"
            model_dir.mkdir()
            (model_dir / "config.json").write_text(
                '{"model_type":"tiny"}', encoding="utf-8"
            )
            with self.assertRaises(LocalModelError):
                registry.register(model_dir)

    def test_rejects_unsafe_or_missing_indexed_weight_shards(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config.json").write_text('{"model_type":"tiny"}', encoding="utf-8")
            (root / "tokenizer.model").write_bytes(b"tokenizer")
            index = root / "model.safetensors.index.json"
            index.write_text(
                json.dumps({"weight_map": {"weight": "../outside.safetensors"}}),
                encoding="utf-8",
            )
            registry = LocalModelRegistry(root / "registry.json")
            with self.assertRaises(LocalModelError):
                registry.register(root)

    def test_missing_registered_model_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "model.gguf"
            model_path.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(16))
            registry = LocalModelRegistry(root / "index.json")
            model = registry.register(model_path)
            model_path.unlink()
            with self.assertRaisesRegex(LocalModelError, "path is missing"):
                registry.get(model.model_id)


class LocalInferenceTests(unittest.TestCase):
    def test_gguf_runtime_uses_mmap_and_cpu_and_closes_runner(self) -> None:
        calls = {}

        class FakeRunner:
            def __init__(self, **kwargs):
                calls["options"] = kwargs
                calls["closed"] = False

            def create_chat_completion(self, **kwargs):
                calls["messages"] = kwargs["messages"]
                return {"choices": [{"message": {"content": "  Offline reply.  "}}]}

            def close(self):
                calls["closed"] = True

        fake_module = types.ModuleType("llama_cpp")
        fake_module.Llama = FakeRunner
        model = LocalModel(
            model_id="1234567890abcdef",
            name="Test model",
            format="gguf",
            path="/tmp/model.gguf",
            size_bytes=64,
            model_type="GGUF",
            added_at="2026-01-01T00:00:00+00:00",
        )
        with mock.patch.dict("sys.modules", {"llama_cpp": fake_module}):
            result = generate_chat(
                model,
                [{"role": "user", "content": "Say hello"}],
                context_tokens=256,
                max_tokens=32,
                threads=2,
                batch_size=16,
            )
        self.assertEqual(result, "Offline reply.")
        self.assertTrue(calls["options"]["use_mmap"])
        self.assertEqual(calls["options"]["n_gpu_layers"], 0)
        self.assertEqual(calls["options"]["n_threads"], 2)
        self.assertTrue(calls["closed"])

    def test_transformers_runtime_is_local_only_and_cpu_bounded(self) -> None:
        calls = {}

        class FakeTensor:
            shape = (1, 4)

            def to(self, device):
                calls["input_device"] = device
                return self

            def __getitem__(self, _key):
                return self

        class FakeTokenizer:
            eos_token_id = 0

            @classmethod
            def from_pretrained(cls, path, **kwargs):
                calls["tokenizer"] = (path, kwargs)
                return cls()

            def apply_chat_template(self, messages, **_kwargs):
                return messages[-1]["content"]

            def __call__(self, prompt, **kwargs):
                calls["prompt"] = prompt
                return {"input_ids": FakeTensor()}

            def decode(self, _output, **_kwargs):
                return "Transformers reply"

        class FakeModel:
            @classmethod
            def from_pretrained(cls, path, **kwargs):
                calls["model"] = (path, kwargs)
                return cls()

            def eval(self):
                return None

            def generate(self, **kwargs):
                calls["generation"] = kwargs
                return FakeTensor()

        fake_torch = types.ModuleType("torch")
        fake_torch.set_num_threads = lambda count: calls.setdefault("threads", count)
        fake_torch.inference_mode = contextlib.nullcontext
        fake_transformers = types.ModuleType("transformers")
        fake_transformers.AutoTokenizer = FakeTokenizer
        fake_transformers.AutoModelForCausalLM = FakeModel
        model = LocalModel(
            model_id="fedcba0987654321",
            name="Safe local model",
            format="safetensors",
            path="/models/safe",
            size_bytes=4096,
            model_type="tiny-test",
            added_at="2026-01-01T00:00:00+00:00",
        )
        with mock.patch.dict(
            "sys.modules", {"torch": fake_torch, "transformers": fake_transformers}
        ):
            result = generate_chat(
                model,
                [{"role": "user", "content": "hello"}],
                context_tokens=128,
                max_tokens=16,
                threads=2,
            )
        self.assertEqual(result, "Transformers reply")
        self.assertTrue(calls["tokenizer"][1]["local_files_only"])
        self.assertFalse(calls["tokenizer"][1]["trust_remote_code"])
        self.assertTrue(calls["model"][1]["local_files_only"])
        self.assertTrue(calls["model"][1]["use_safetensors"])
        self.assertEqual(calls["input_device"], "cpu")
        self.assertEqual(calls["threads"], 2)
        self.assertEqual(calls["generation"]["max_new_tokens"], 16)

    def test_bad_runtime_limits_are_rejected_before_optional_import(self) -> None:
        model = LocalModel(
            model_id="1234567890abcdef",
            name="Test model",
            format="gguf",
            path="/tmp/model.gguf",
            size_bytes=64,
            model_type="GGUF",
            added_at="2026-01-01T00:00:00+00:00",
        )
        with self.assertRaises(ValueError):
            generate_chat(
                model,
                [{"role": "user", "content": "hello"}],
                context_tokens=32,
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            generate_chat(
                model,
                [{"role": "user", "content": "hello"}],
                temperature=float("nan"),
            )


if __name__ == "__main__":
    unittest.main()
