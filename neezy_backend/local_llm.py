"""Local model inventory and optional offline inference backends.

GGUF uses llama.cpp with file-backed mmap, CPU-only execution, bounded context,
and small batches. Hugging Face model folders may contain SafeTensors or PyTorch
weights and are loaded with Transformers only when that optional runtime exists.
No model is downloaded, and arbitrary model Python code is never trusted.
"""

from __future__ import annotations

import gc
import json
import math
import secrets
import shutil
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import _atomic_json_write, get_data_dir

_INDEX_VERSION = 1
_CONFIG_LIMIT = 2_000_000
_TOKENIZER_FILES = frozenset(
    {
        "tokenizer.json",
        "tokenizer.model",
        "spiece.model",
        "sentencepiece.bpe.model",
        "vocab.json",
        "vocab.txt",
        "merges.txt",
    }
)
_WEIGHT_SUFFIXES = frozenset({".safetensors", ".bin"})


def _is_transformers_weight_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered == "model.safetensors"
        or (lowered.startswith("model-") and lowered.endswith(".safetensors"))
        or lowered == "pytorch_model.bin"
        or (lowered.startswith("pytorch_model-") and lowered.endswith(".bin"))
    )


class LocalModelError(RuntimeError):
    """A safe, user-facing local-model validation or runtime error."""


@dataclass(frozen=True, slots=True)
class LocalModel:
    """Metadata for a user-selected model; the model files are never copied."""

    model_id: str
    name: str
    format: str
    path: str
    size_bytes: int
    model_type: str
    added_at: str

    @property
    def path_obj(self) -> Path:
        return Path(self.path)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalModelRegistry:
    """A small local index of model paths, avoiding duplicate multi-GB copies."""

    def __init__(self, index_path: Path | str | None = None) -> None:
        self.index_path = (
            Path(index_path) if index_path else get_data_dir() / "local-models.json"
        )
        self._lock = threading.RLock()

    def _read(self) -> list[LocalModel]:
        try:
            document = json.loads(self.index_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise LocalModelError("local model index cannot be read") from error
        if not isinstance(document, dict) or document.get("version") != _INDEX_VERSION:
            raise LocalModelError("local model index has an unsupported format")
        records = document.get("models")
        if not isinstance(records, list):
            raise LocalModelError("local model index is malformed")
        models = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if (
                not isinstance(record.get("model_id"), str)
                or not isinstance(record.get("name"), str)
                or not isinstance(record.get("format"), str)
                or not isinstance(record.get("path"), str)
                or not isinstance(record.get("size_bytes"), int)
                or isinstance(record.get("size_bytes"), bool)
                or not isinstance(record.get("model_type"), str)
                or not isinstance(record.get("added_at"), str)
            ):
                continue
            try:
                models.append(LocalModel(**record))
            except (TypeError, ValueError):
                continue
        return models

    def _write(self, models: Sequence[LocalModel]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json_write(
            self.index_path,
            {"version": _INDEX_VERSION, "models": [item.to_dict() for item in models]},
        )

    @staticmethod
    def _safe_size(files: Sequence[Path]) -> int:
        total = 0
        for file_path in files:
            try:
                total += file_path.stat().st_size
            except OSError as error:
                raise LocalModelError(
                    f"model file is no longer accessible: {file_path.name}"
                ) from error
        return total

    @classmethod
    def _inspect_gguf(cls, path: Path) -> tuple[str, int, str]:
        if not path.is_file() or path.suffix.lower() != ".gguf":
            raise LocalModelError("choose one GGUF model file ending in .gguf")
        try:
            with path.open("rb") as stream:
                header = stream.read(8)
            size = path.stat().st_size
        except OSError as error:
            raise LocalModelError("GGUF file cannot be read") from error
        version = int.from_bytes(header[4:8], "little") if len(header) == 8 else 0
        if header[:4] != b"GGUF" or size < 24 or version not in {1, 2, 3}:
            raise LocalModelError("file does not have a supported GGUF header")
        return "gguf", size, "GGUF"

    @classmethod
    def _inspect_transformers(cls, path: Path) -> tuple[str, int, str, Path]:
        root = path if path.is_dir() else path.parent
        config_path = root / "config.json"
        if not config_path.is_file():
            raise LocalModelError(
                "a Transformers model needs a folder with config.json, tokenizer "
                "files, and model weights"
            )
        try:
            if config_path.stat().st_size > _CONFIG_LIMIT:
                raise LocalModelError("model config.json is unexpectedly large")
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except LocalModelError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise LocalModelError(
                "model config.json is invalid or unreadable"
            ) from error
        if not isinstance(config, dict) or not isinstance(
            config.get("model_type"), str
        ):
            raise LocalModelError("config.json must contain a model_type")

        try:
            names = {item.name for item in root.iterdir() if item.is_file()}
        except OSError as error:
            raise LocalModelError("model directory cannot be read") from error
        if not names.intersection(_TOKENIZER_FILES):
            raise LocalModelError(
                "model folder is missing tokenizer.json, tokenizer.model, or vocab.json"
            )

        index_names = (
            "model.safetensors.index.json",
            "pytorch_model.bin.index.json",
        )
        indexed_weights: list[Path] = []
        for index_name in index_names:
            index_path = root / index_name
            if not index_path.is_file():
                continue
            try:
                if index_path.stat().st_size > _CONFIG_LIMIT:
                    raise LocalModelError("model shard index is unexpectedly large")
                index_data = json.loads(index_path.read_text(encoding="utf-8"))
                weight_map = index_data.get("weight_map", {})
            except LocalModelError:
                raise
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                AttributeError,
            ) as error:
                raise LocalModelError("model shard index is invalid") from error
            if not isinstance(weight_map, dict) or not weight_map:
                raise LocalModelError("model shard index has no weight map")
            shard_names = {str(value) for value in weight_map.values()}
            if any(
                Path(name).name != name or name in {".", ".."} for name in shard_names
            ):
                raise LocalModelError("model shard index contains an unsafe path")
            if any(not _is_transformers_weight_name(name) for name in shard_names):
                raise LocalModelError(
                    "model shard index references unsupported weight files"
                )
            indexed_weights.extend(root / name for name in sorted(shard_names))

        if indexed_weights:
            weight_files = indexed_weights
        else:
            weight_files = [
                root / name
                for name in sorted(names)
                if (
                    Path(name).suffix.lower() in _WEIGHT_SUFFIXES
                    and _is_transformers_weight_name(name)
                )
            ]
        weight_files = list(dict.fromkeys(weight_files))
        if not weight_files or any(not item.is_file() for item in weight_files):
            raise LocalModelError("model folder is missing one or more weight files")
        if path.is_file() and path not in weight_files:
            raise LocalModelError(
                "selected weight file is not part of this model folder"
            )
        fmt = (
            "safetensors"
            if any(item.suffix.lower() == ".safetensors" for item in weight_files)
            else "pytorch"
        )
        size = cls._safe_size([config_path, *weight_files])
        size += sum(
            (root / name).stat().st_size
            for name in _TOKENIZER_FILES
            if (root / name).is_file() and (root / name) not in weight_files
        )
        return fmt, size, config["model_type"], root

    def register(self, path: str | Path, *, name: str | None = None) -> LocalModel:
        """Register a GGUF file or a complete local Transformers model folder."""
        try:
            selected = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise LocalModelError("selected model path does not exist") from error
        if not selected.is_file() and not selected.is_dir():
            raise LocalModelError("selected model path is not a file or folder")
        if selected.is_file() and selected.suffix.lower() == ".gguf":
            model_format, size_bytes, model_type = self._inspect_gguf(selected)
            model_path = selected
        else:
            model_format, size_bytes, model_type, model_path = (
                self._inspect_transformers(selected)
            )
        display_name = name or (selected.stem if selected.is_file() else selected.name)
        display_name = display_name.strip()
        if (
            not display_name
            or len(display_name) > 120
            or any(ord(character) < 32 for character in display_name)
        ):
            raise LocalModelError(
                "model name must contain 1 to 120 printable characters"
            )
        model = LocalModel(
            model_id=secrets.token_hex(8),
            name=display_name,
            format=model_format,
            path=str(model_path),
            size_bytes=size_bytes,
            model_type=model_type,
            added_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with self._lock:
            models = self._read()
            for existing in models:
                if existing.path == model.path and existing.format == model.format:
                    return existing
            self._write([*models, model])
        return model

    def list_models(self) -> list[LocalModel]:
        with self._lock:
            return self._read()

    def get(self, model_id: str) -> LocalModel:
        with self._lock:
            for model in self._read():
                if model.model_id == model_id:
                    if not model.path_obj.exists():
                        raise LocalModelError(
                            f"model path is missing: {model.path_obj}"
                        )
                    return model
        raise LocalModelError(f"no local model is registered as {model_id!r}")

    def remove(self, model_id: str) -> LocalModel:
        """Remove an index entry only; never delete the user's model files."""
        with self._lock:
            models = self._read()
            match = next((item for item in models if item.model_id == model_id), None)
            if match is None:
                raise LocalModelError(f"no local model is registered as {model_id!r}")
            self._write([item for item in models if item.model_id != model_id])
            return match


def runtime_status() -> dict[str, bool]:
    """Report optional inference libraries without importing their heavy runtimes."""
    from importlib.util import find_spec

    def installed(module: str) -> bool:
        try:
            return find_spec(module) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            return False

    return {
        "llama_cpp": installed("llama_cpp"),
        "transformers": installed("transformers"),
        "torch": installed("torch"),
        "safetensors": installed("safetensors"),
        "accelerate": installed("accelerate"),
    }


def _validate_runtime_options(
    context_tokens: int,
    max_tokens: int,
    threads: int,
    batch_size: int,
    cpu_memory_mb: int,
) -> None:
    if not 128 <= context_tokens <= 32768:
        raise ValueError("context size must be between 128 and 32768 tokens")
    if not 1 <= max_tokens <= 8192:
        raise ValueError("maximum output must be between 1 and 8192 tokens")
    if not 1 <= threads <= 16:
        raise ValueError("CPU threads must be between 1 and 16")
    if not 1 <= batch_size <= 1024:
        raise ValueError("batch size must be between 1 and 1024")
    if not 256 <= cpu_memory_mb <= 262144:
        raise ValueError("CPU memory budget must be between 256 and 262144 MB")


def generate_chat(
    model: LocalModel,
    messages: Sequence[Mapping[str, str]],
    *,
    context_tokens: int = 512,
    max_tokens: int = 128,
    threads: int = 1,
    batch_size: int = 32,
    disk_offload: bool = False,
    cpu_memory_mb: int = 512,
    temperature: float = 0.3,
) -> str:
    """Generate one local response, loading only locally stored model files."""
    _validate_runtime_options(
        context_tokens, max_tokens, threads, batch_size, cpu_memory_mb
    )
    if not messages:
        raise ValueError("messages must not be empty")
    safe_messages = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise ValueError("local chat messages need a supported role and text")
        safe_messages.append({"role": role, "content": content})
    raw_temperature = float(temperature)
    if not math.isfinite(raw_temperature):
        raise ValueError("temperature must be finite")
    safe_temperature = min(max(raw_temperature, 0.0), 2.0)
    if model.format == "gguf":
        return _generate_gguf(
            model,
            safe_messages,
            context_tokens=context_tokens,
            max_tokens=max_tokens,
            threads=threads,
            batch_size=batch_size,
            temperature=safe_temperature,
        )
    if model.format in {"safetensors", "pytorch"}:
        return _generate_transformers(
            model,
            safe_messages,
            context_tokens=context_tokens,
            max_tokens=max_tokens,
            threads=threads,
            disk_offload=disk_offload,
            cpu_memory_mb=cpu_memory_mb,
            temperature=safe_temperature,
        )
    raise LocalModelError(f"unsupported local model format {model.format!r}")


def _generate_gguf(
    model: LocalModel,
    messages: list[dict[str, str]],
    *,
    context_tokens: int,
    max_tokens: int,
    threads: int,
    batch_size: int,
    temperature: float,
) -> str:
    try:
        from llama_cpp import Llama
    except ImportError as error:
        raise LocalModelError(
            "GGUF inference needs the optional llama-cpp-python runtime; "
            "see README for installation notes"
        ) from error
    runner = None
    try:
        runner = Llama(
            model_path=model.path,
            n_ctx=context_tokens,
            n_batch=min(batch_size, context_tokens),
            n_threads=threads,
            n_gpu_layers=0,
            use_mmap=True,
            use_mlock=False,
            verbose=False,
        )
        response = runner.create_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choices = response.get("choices", []) if isinstance(response, dict) else []
        if not choices:
            raise LocalModelError("GGUF runtime returned no response choices")
        content = (choices[0].get("message") or {}).get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise LocalModelError("GGUF runtime returned an empty response")
        return content.strip()
    except LocalModelError:
        raise
    except Exception as error:  # noqa: BLE001 - isolate optional native runtimes
        raise LocalModelError(f"GGUF inference failed: {str(error)[:240]}") from None
    finally:
        close = getattr(runner, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - best-effort native cleanup
                pass
        del runner
        gc.collect()


def _generate_transformers(
    model: LocalModel,
    messages: list[dict[str, str]],
    *,
    context_tokens: int,
    max_tokens: int,
    threads: int,
    disk_offload: bool,
    cpu_memory_mb: int,
    temperature: float,
) -> str:
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as error:
        raise LocalModelError(
            "SafeTensors/Transformers inference needs the optional torch and "
            "transformers runtimes; see README for installation notes"
        ) from error
    if disk_offload and not runtime_status()["accelerate"]:
        raise LocalModelError(
            "disk offload for Transformers models requires the optional "
            "accelerate package"
        )
    tokenizer = None
    model_instance = None
    offload_path: Path | None = None
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model.path, local_files_only=True, trust_remote_code=False
        )
        loader_options: dict[str, Any] = {
            "local_files_only": True,
            "trust_remote_code": False,
            "torch_dtype": "auto",
        }
        if model.format == "safetensors":
            loader_options["use_safetensors"] = True
        else:
            # Require Transformers versions that honor PyTorch's restricted
            # weights-only unpickler; never load arbitrary pickle globals.
            loader_options["weights_only"] = True
        if disk_offload:
            offload_root = get_data_dir() / "model-offload"
            offload_root.mkdir(parents=True, exist_ok=True)
            offload_path = Path(tempfile.mkdtemp(prefix="neezy-", dir=offload_root))
            max_memory: dict[int | str, str] = {"cpu": f"{cpu_memory_mb}MiB"}
            if torch.cuda.is_available():
                for device_index in range(torch.cuda.device_count()):
                    max_memory[device_index] = "0GiB"
            loader_options.update(
                {
                    "device_map": "auto",
                    "max_memory": max_memory,
                    "offload_folder": str(offload_path),
                    "offload_state_dict": True,
                    "low_cpu_mem_usage": True,
                }
            )
        model_instance = AutoModelForCausalLM.from_pretrained(
            model.path, **loader_options
        )
        model_instance.eval()
        torch.set_num_threads(threads)
        template = getattr(tokenizer, "apply_chat_template", None)
        if callable(template):
            try:
                prompt = template(messages, tokenize=False, add_generation_prompt=True)
            except (ValueError, TypeError):
                prompt = (
                    "\n".join(
                        f"{item['role'].upper()}: {item['content']}"
                        for item in messages
                    )
                    + "\nASSISTANT:"
                )
        else:
            prompt = (
                "\n".join(
                    f"{item['role'].upper()}: {item['content']}" for item in messages
                )
                + "\nASSISTANT:"
            )
        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=context_tokens,
        )
        input_length = int(inputs["input_ids"].shape[-1])
        # Accelerate disk-offload hooks page modules onto CPU as needed; input
        # tensors stay on CPU because this runtime is deliberately CPU-oriented.
        inputs = {key: value.to("cpu") for key, value in inputs.items()}
        generation_options: dict[str, Any] = {
            "max_new_tokens": min(max_tokens, max(1, context_tokens - input_length)),
            "do_sample": temperature > 0.0,
            "pad_token_id": tokenizer.eos_token_id,
        }
        if temperature > 0.0:
            generation_options["temperature"] = temperature
        with torch.inference_mode():
            output = model_instance.generate(**inputs, **generation_options)
        answer = tokenizer.decode(output[0][input_length:], skip_special_tokens=True)
        if not answer.strip():
            raise LocalModelError("Transformers runtime returned an empty response")
        return answer.strip()
    except LocalModelError:
        raise
    except Exception as error:  # noqa: BLE001 - isolate optional model/runtime errors
        raise LocalModelError(
            f"local Transformers inference failed: {str(error)[:240]}"
        ) from None
    finally:
        del model_instance
        del tokenizer
        gc.collect()
        if offload_path is not None:
            shutil.rmtree(offload_path, ignore_errors=True)
