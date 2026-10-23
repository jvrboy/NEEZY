"""Hash-verified Hugging Face model promotion and atomic PC activation.

Only JSON weights are accepted: no pickle, custom code, or training runtime is
installed on the executor. A candidate is activated only when its held-out
backtest and exact-hash paper-trading evidence pass local policy checks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .brain import validate_model

MANIFEST_SCHEMA = 1
MAX_MANIFEST_BYTES = 256_000
MAX_MODEL_BYTES = 8_000_000
_MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPO_ID = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


class ModelUpdateError(RuntimeError):
    """A sanitized download, integrity, or activation failure."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def model_json_bytes(model: dict[str, Any]) -> bytes:
    """Serialize a model deterministically and reject NaN/infinity."""
    validate_model(model)
    return (json.dumps(model, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def safe_repo_path(path: str) -> str:
    if not isinstance(path, str) or not path or "\\" in path or path.startswith("/"):
        raise ValueError("model path must be a relative repository path")
    parts = path.split("/")
    if any(
        not part or part in {".", ".."} or not _SAFE_PART.fullmatch(part)
        for part in parts
    ):
        raise ValueError("model path contains unsafe characters")
    return path


def latest_manifest_path(symbol: str, timeframe: str) -> str:
    return safe_repo_path(f"latest/{symbol}/{timeframe}.json")


def new_model_id(
    model: dict[str, Any], model_sha256: str, *, now: datetime | None = None
) -> str:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    symbol = re.sub(r"[^a-z0-9.-]", "-", str(model.get("symbol", "model")).lower())
    timeframe = re.sub(
        r"[^a-z0-9.-]", "-", str(model.get("timeframe", "unknown")).lower()
    )
    model_id = (
        f"{symbol}-{timeframe}-{stamp.strftime('%Y%m%dt%H%M%Sz')}-{model_sha256[:12]}"
    )
    if not _MODEL_ID.fullmatch(model_id):
        raise ValueError("could not create a safe model id")
    return model_id


def build_candidate_manifest(
    model: dict[str, Any],
    *,
    model_file: str,
    model_content: bytes,
    backtest: dict[str, Any],
    model_id: str,
) -> dict[str, Any]:
    """Build a non-promoted manifest; paper evidence is added separately."""
    validate_model(model)
    if not _MODEL_ID.fullmatch(model_id):
        raise ValueError("model id is invalid")
    digest = sha256_bytes(model_content)
    evidence = copy.deepcopy(backtest)
    evidence["model_sha256"] = digest
    return {
        "schema": MANIFEST_SCHEMA,
        "model_id": model_id,
        "model_file": safe_repo_path(model_file),
        "model_sha256": digest,
        "symbol": model.get("symbol"),
        "timeframe": model.get("timeframe"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "validation": {
            "backtest": evidence,
            "paper_trade": {
                "passed": False,
                "trades": 0,
                "days": 0,
                "model_sha256": digest,
                "note": "Candidate only; exact-hash paper evidence is required.",
            },
        },
    }


def attach_paper_evidence(
    manifest: dict[str, Any], paper_report: dict[str, Any]
) -> dict[str, Any]:
    """Return a copy with paper evidence bound to the candidate's exact hash."""
    if paper_report.get("model_sha256") != manifest.get("model_sha256"):
        raise ValueError("paper report is not bound to the candidate model hash")
    promoted = copy.deepcopy(manifest)
    evidence = copy.deepcopy(paper_report)
    promoted.setdefault("validation", {})["paper_trade"] = evidence
    return promoted


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def evaluate_model_gate(
    model: dict[str, Any],
    manifest: dict[str, Any],
    *,
    symbol: str,
    timeframe: str,
    min_test_samples: int = 50,
    min_balanced_accuracy: float = 0.55,
    min_backtest_trades: int = 20,
    min_paper_trades: int = 20,
    min_paper_days: int = 14,
    require_paper: bool = True,
) -> list[str]:
    """Return gate failures; paper mode alone may defer only paper evidence."""
    issues: list[str] = []
    try:
        validate_model(model)
    except (TypeError, ValueError) as error:
        return [f"invalid model: {error}"]
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        return ["unsupported model manifest schema"]
    model_id = manifest.get("model_id")
    if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
        issues.append("manifest model id is invalid")
    digest = manifest.get("model_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        issues.append("manifest model hash is invalid")
        digest = ""
    try:
        safe_repo_path(manifest.get("model_file", ""))
    except ValueError as error:
        issues.append(str(error))
    if manifest.get("symbol") != symbol or model.get("symbol") != symbol:
        issues.append(f"model is not for {symbol}")
    if manifest.get("timeframe") != timeframe or model.get("timeframe") != timeframe:
        issues.append(f"model is not for timeframe {timeframe}")
    if not model.get("deployment_ready", False):
        issues.append("model is marked research-only")

    metrics = model.get("test_metrics")
    if not isinstance(metrics, dict):
        issues.append("held-out metrics are missing")
        metrics = {}
    samples = _integer(metrics.get("samples"))
    if samples is None or samples < min_test_samples:
        issues.append(f"held-out samples must be at least {min_test_samples}")
    balanced = _number(metrics.get("balanced_accuracy"))
    if balanced is None or balanced < min_balanced_accuracy:
        issues.append(
            f"held-out balanced accuracy must be at least {min_balanced_accuracy:.2f}"
        )
    accuracy = _number(metrics.get("accuracy"))
    baseline = _number(metrics.get("baseline_accuracy"))
    if accuracy is None or baseline is None or accuracy < baseline:
        issues.append("held-out accuracy does not beat its class baseline")

    validation = manifest.get("validation")
    if not isinstance(validation, dict):
        validation = {}
    backtest = validation.get("backtest")
    if not isinstance(backtest, dict):
        backtest = {}
    if backtest.get("passed") is not True:
        issues.append("held-out trade backtest has not passed")
    if backtest.get("model_sha256") != digest:
        issues.append("backtest evidence is not bound to this model hash")
    if backtest.get("method") != "chronological_held_out_trade_backtest_v1":
        issues.append("held-out trade backtest method is missing or unsupported")
    backtest_trades = _integer(backtest.get("trades"))
    if backtest_trades is None or backtest_trades < min_backtest_trades:
        issues.append(f"backtest needs at least {min_backtest_trades} closed trades")
    expectancy = _number(backtest.get("expectancy_r"))
    if expectancy is None or expectancy <= 0:
        issues.append("backtest expectancy must be positive after assumed costs")

    if require_paper:
        paper = validation.get("paper_trade")
        if not isinstance(paper, dict):
            paper = {}
        if paper.get("passed") is not True:
            issues.append("paper-trading validation has not passed")
        if paper.get("model_sha256") != digest:
            issues.append("paper evidence is not bound to this model hash")
        paper_trades = _integer(paper.get("trades"))
        if paper_trades is None or paper_trades < min_paper_trades:
            issues.append(f"paper validation needs at least {min_paper_trades} trades")
        paper_days = _integer(paper.get("days"))
        if paper_days is None or paper_days < min_paper_days:
            issues.append(f"paper validation needs at least {min_paper_days} days")
    return issues


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward an HF bearer token to a different redirect host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlsplit(req.full_url).netloc.lower()
        new_host = urllib.parse.urlsplit(newurl).netloc.lower()
        if old_host != new_host and redirected.has_header("Authorization"):
            redirected.remove_header("Authorization")
        return redirected


class HuggingFaceDownloader:
    """Small bounded downloader for JSON artifacts from one HF model repo."""

    def __init__(
        self,
        repo_id: str,
        *,
        revision: str = "main",
        token: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not _REPO_ID.fullmatch(repo_id):
            raise ValueError("HF repo id must look like 'owner/repository'")
        if not revision or "/" in revision or not _SAFE_PART.fullmatch(revision):
            raise ValueError("HF revision must be a branch name or commit hash")
        self.repo_id = repo_id
        self.revision = revision
        self._token = token or None
        self.timeout = float(timeout)

    def url_for(self, path: str) -> str:
        safe_path = safe_repo_path(path)
        repo = "/".join(urllib.parse.quote(part) for part in self.repo_id.split("/"))
        revision = urllib.parse.quote(self.revision, safe="")
        encoded = "/".join(urllib.parse.quote(part) for part in safe_path.split("/"))
        return f"https://huggingface.co/{repo}/resolve/{revision}/{encoded}"

    def download(self, path: str, *, max_bytes: int = MAX_MODEL_BYTES) -> bytes:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        headers = {"User-Agent": "NEEZY-executor/1.0"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(self.url_for(path), headers=headers)
        opener = urllib.request.build_opener(_SafeRedirectHandler())
        try:
            with opener.open(request, timeout=self.timeout) as response:
                content = response.read(max_bytes + 1)
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise ModelUpdateError(f"Hugging Face download failed: {reason}") from error
        if len(content) > max_bytes:
            raise ModelUpdateError("Hugging Face artifact exceeds the size limit")
        return content


def _json_document(content: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelUpdateError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ModelUpdateError(f"{label} must contain a JSON object")
    return document


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


class ModelUpdateManager:
    """Keep one symbol/timeframe model active and never swap on failure."""

    def __init__(
        self,
        root: Path,
        *,
        symbol: str,
        timeframe: str,
        downloader: HuggingFaceDownloader,
        min_test_samples: int = 50,
        min_balanced_accuracy: float = 0.55,
        min_backtest_trades: int = 20,
        min_paper_trades: int = 20,
        min_paper_days: int = 14,
    ) -> None:
        self.symbol = safe_repo_path(symbol)
        self.timeframe = safe_repo_path(timeframe)
        self.directory = root / self.symbol / self.timeframe
        self.pointer = self.directory / "active.json"
        self.downloader = downloader
        self.gate = {
            "min_test_samples": min_test_samples,
            "min_balanced_accuracy": min_balanced_accuracy,
            "min_backtest_trades": min_backtest_trades,
            "min_paper_trades": min_paper_trades,
            "min_paper_days": min_paper_days,
        }

    @property
    def manifest_path(self) -> str:
        return latest_manifest_path(self.symbol, self.timeframe)

    def _validate(self, model: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
        return evaluate_model_gate(
            model,
            manifest,
            symbol=self.symbol,
            timeframe=self.timeframe,
            **self.gate,
        )

    def load_active(self) -> dict[str, Any] | None:
        if not self.pointer.exists():
            return None
        try:
            pointer = _json_document(self.pointer.read_bytes(), "active model pointer")
            if pointer.get("schema") != MANIFEST_SCHEMA:
                raise ModelUpdateError("active model pointer schema is unsupported")
            filename = pointer.get("filename")
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or not _MODEL_ID.fullmatch(Path(filename).stem)
            ):
                raise ModelUpdateError("active model filename is unsafe")
            content = (self.directory / "released" / filename).read_bytes()
            if len(content) > MAX_MODEL_BYTES:
                raise ModelUpdateError("active model exceeds the size limit")
            manifest = pointer.get("manifest")
            if not isinstance(manifest, dict):
                raise ModelUpdateError("active model manifest is missing")
            if sha256_bytes(content) != manifest.get("model_sha256"):
                raise ModelUpdateError("active model hash does not match its manifest")
            model = _json_document(content, "active model")
            issues = self._validate(model, manifest)
            if issues:
                raise ModelUpdateError(
                    "active model no longer passes policy: " + "; ".join(issues)
                )
            return {"model": model, "manifest": manifest, "content": content}
        except (OSError, ValueError) as error:
            raise ModelUpdateError(f"could not load active model: {error}") from error

    def check_for_update(self) -> dict[str, Any]:
        """Download, validate, then atomically activate; old model survives errors."""
        active_id = None
        try:
            active = self.load_active()
            if active:
                active_id = active["manifest"].get("model_id")
        except ModelUpdateError:
            # A valid promoted artifact can repair a damaged local installation.
            active = None

        manifest_content = self.downloader.download(
            self.manifest_path, max_bytes=MAX_MANIFEST_BYTES
        )
        manifest = _json_document(manifest_content, "model manifest")
        model_id = manifest.get("model_id")
        if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
            raise ModelUpdateError("model manifest has an invalid model id")
        if model_id == active_id:
            return {"status": "unchanged", "model_id": model_id}
        try:
            model_path = safe_repo_path(manifest.get("model_file", ""))
        except ValueError as error:
            raise ModelUpdateError(str(error)) from error
        content = self.downloader.download(model_path, max_bytes=MAX_MODEL_BYTES)
        if sha256_bytes(content) != manifest.get("model_sha256"):
            return {
                "status": "rejected",
                "model_id": model_id,
                "issues": ["downloaded model hash does not match manifest"],
                "active_model_id": active_id,
            }
        model = _json_document(content, "downloaded model")
        issues = self._validate(model, manifest)
        if issues:
            return {
                "status": "rejected",
                "model_id": model_id,
                "issues": issues,
                "active_model_id": active_id,
            }

        filename = f"{model_id}.json"
        released = self.directory / "released" / filename
        if released.exists() and sha256_bytes(released.read_bytes()) != sha256_bytes(
            content
        ):
            raise ModelUpdateError("model id collision with different local content")
        _atomic_write(released, content)
        pointer_content = (
            json.dumps(
                {
                    "schema": MANIFEST_SCHEMA,
                    "filename": filename,
                    "manifest": manifest,
                },
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        _atomic_write(self.pointer, pointer_content)
        return {
            "status": "activated",
            "model_id": model_id,
            "previous_model_id": active_id,
        }

    def status(self) -> dict[str, Any]:
        try:
            active = self.load_active()
        except ModelUpdateError as error:
            return {"active": False, "error": str(error)}
        if active is None:
            return {"active": False}
        manifest = active["manifest"]
        return {
            "active": True,
            "model_id": manifest.get("model_id"),
            "created_at": manifest.get("created_at"),
            "model_sha256": manifest.get("model_sha256"),
        }
