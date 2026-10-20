"""Bring-your-own-key AI providers with multi-key failover, stored locally.

Supported providers (all talk HTTPS directly from your PC):

* **Google Gemini** — free tier keys from Google AI Studio.
* **Grok (xAI)** — keys from the xAI console.
* **OpenRouter** — free ``:free`` models, one key or many.
* **Ollama Cloud** — OpenAI-compatible endpoint at ``https://ollama.com/v1``.

Each provider may hold **several API keys**. When a key reports a quota or rate
limit it is parked for a cooldown and the next healthy key is used, so a
workspace with three keys keeps answering after the first one runs dry.

Only free models are offered in the picker. Catalogues go stale, so a custom
model id may be typed in the UI/CLI; nothing here is billed by NEEZY, and keys
never leave the machine except in the request to the provider you chose.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .storage import _atomic_json_write, get_data_dir

DEFAULT_SYSTEM_PROMPT = (
    "You are NEEZY, a concise market-analysis copilot inside a desktop app. "
    "Use only the supplied indicator context. Explain the reasoning briefly, "
    "name the indicators involved, and state uncertainty. You are educational "
    "only: never present output as financial advice, a guarantee, or an order "
    "instruction. Keep answers under 220 words unless asked for detail."
)

DEFAULT_MAX_TOKENS = 700


@dataclass(frozen=True, slots=True)
class Provider:
    """Static description of one provider and its free models."""

    key: str
    label: str
    base_url: str
    api_style: str
    models: tuple[str, ...]
    key_url: str
    key_prefix: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "base_url": self.base_url,
            "api_style": self.api_style,
            "models": list(self.models),
            "key_url": self.key_url,
            "key_prefix": self.key_prefix,
            "notes": self.notes,
        }


PROVIDERS: dict[str, Provider] = {
    "gemini": Provider(
        key="gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_style="gemini",
        models=(
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ),
        key_url="https://aistudio.google.com/app/apikey",
        key_prefix="AIza",
        notes="Free tier has per-minute and per-day request limits per key.",
    ),
    "grok": Provider(
        key="grok",
        label="Grok (xAI)",
        base_url="https://api.x.ai/v1",
        api_style="openai",
        models=("grok-3-mini", "grok-4-fast", "grok-code-fast-1"),
        key_url="https://console.x.ai",
        key_prefix="xai-",
        notes="xAI's free allowance is credit based; add several keys to rotate.",
    ),
    "openrouter": Provider(
        key="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_style="openai",
        models=(
            "deepseek/deepseek-r1:free",
            "deepseek/deepseek-chat-v3.1:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen3-235b-a22b:free",
            "moonshotai/kimi-k2:free",
            "mistralai/mistral-small-3.2-24b-instruct:free",
            "z-ai/glm-4.5-air:free",
        ),
        key_url="https://openrouter.ai/keys",
        key_prefix="sk-or-",
        notes="Free models end in ':free'; daily request caps are per key.",
    ),
    "ollama": Provider(
        key="ollama",
        label="Ollama Cloud",
        base_url="https://ollama.com/v1",
        api_style="openai",
        models=(
            "gpt-oss:20b",
            "gpt-oss:120b",
            "qwen3-coder:480b",
            "deepseek-v3.1:671b",
            "kimi-k2:1t",
            "glm-4.6",
        ),
        key_url="https://ollama.com/settings/keys",
        key_prefix="",
        notes="Uses Ollama's OpenAI-compatible endpoint with a cloud API key.",
    ),
}

PROVIDER_ALIASES = {
    "google": "gemini",
    "google gemini": "gemini",
    "xai": "grok",
    "x.ai": "grok",
    "ollama cloud": "ollama",
    "ollama-cloud": "ollama",
    "open router": "openrouter",
}


def resolve_provider(name: str) -> Provider:
    """Case-insensitive provider lookup with a friendly alias map."""
    cleaned = name.strip().lower()
    key = cleaned if cleaned in PROVIDERS else PROVIDER_ALIASES.get(cleaned, cleaned)
    try:
        return PROVIDERS[key]
    except KeyError:
        raise ValueError(
            f"unknown AI provider {name!r}; choose from {', '.join(PROVIDERS)}"
        ) from None


def provider_names() -> list[str]:
    return list(PROVIDERS)


def free_models(provider: str) -> list[str]:
    """Free models offered for a provider, in catalogue order."""
    return list(resolve_provider(provider).models)


def models_with_extra(provider: str, extra: Sequence[str] = ()) -> list[str]:
    """Free models plus any user-typed custom ids (deduplicated, ordered)."""
    catalogue = free_models(provider)
    for model in extra:
        cleaned = model.strip()
        if cleaned and cleaned not in catalogue:
            catalogue.append(cleaned)
    return catalogue


def is_free_model(provider: str, model: str) -> bool:
    """True for a catalogued free model or an OpenRouter ``:free`` variant."""
    spec = resolve_provider(provider)
    cleaned = model.strip()
    return cleaned in spec.models or cleaned.endswith(":free")


def resolve_model(provider: str, model: str | None = None) -> str:
    """Pick a model, defaulting to the first free model of the provider."""
    spec = resolve_provider(provider)
    if model is None or not model.strip():
        return spec.models[0]
    return model.strip()


def validate_secret(provider: str, secret: str) -> str:
    """Trim and sanity-check a key without ever echoing it back."""
    cleaned = (secret or "").strip().strip('"').strip("'")
    if len(cleaned) < 8:
        raise ValueError("API key looks too short; paste the full key")
    if any(character.isspace() for character in cleaned):
        raise ValueError("API key must not contain spaces")
    return cleaned


def mask_secret(secret: str) -> str:
    """Show only the last four characters, never the whole key."""
    if len(secret) <= 4:
        return "*" * len(secret)
    return f"{'*' * min(len(secret) - 4, 12)}{secret[-4:]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class KeyStatus:
    """Public, safe view of one stored key."""

    id: str
    provider: str
    label: str
    hint: str
    enabled: bool
    failures: int
    uses: int
    exhausted_until: str | None
    last_error: str
    last_used: str | None

    def usable(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        if not self.exhausted_until:
            return True
        try:
            until = datetime.fromisoformat(self.exhausted_until)
        except ValueError:
            return True
        return (now or _utc_now()) >= until

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "hint": self.hint,
            "enabled": self.enabled,
            "failures": self.failures,
            "uses": self.uses,
            "exhausted_until": self.exhausted_until,
            "last_error": self.last_error,
            "last_used": self.last_used,
            "usable": self.usable(now),
        }


def _status_from_record(provider: str, record: Mapping[str, Any]) -> KeyStatus:
    return KeyStatus(
        id=str(record.get("id", "")),
        provider=provider,
        label=str(record.get("label") or "key"),
        hint=mask_secret(str(record.get("secret", ""))),
        enabled=bool(record.get("enabled", True)),
        failures=int(record.get("failures", 0)),
        uses=int(record.get("uses", 0)),
        exhausted_until=record.get("exhausted_until"),
        last_error=str(record.get("last_error") or ""),
        last_used=record.get("last_used"),
    )


class AIKeyStore:
    """Local key vault: many keys per provider, with health and cooldown state."""

    VERSION = 1

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else get_data_dir() / "ai-keys.json"
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ internals
    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": self.VERSION, "keys": {}}
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {"version": self.VERSION, "keys": {}}
        if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
            return {"version": self.VERSION, "keys": {}}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json_write(self.path, data)
        try:
            self.path.chmod(0o600)
        except OSError:
            # Windows relies on the per-user ACL of %APPDATA% instead.
            pass

    def _records(self, data: dict[str, Any], provider: str) -> list[dict[str, Any]]:
        entries = data["keys"].get(provider, [])
        return entries if isinstance(entries, list) else []

    # --------------------------------------------------------------------- public
    def providers(self) -> list[str]:
        with self._lock:
            data = self._read()
        return [name for name, entries in data["keys"].items() if entries]

    def add(
        self,
        provider: str,
        secret: str,
        label: str = "",
        *,
        replace_duplicate: bool = True,
    ) -> KeyStatus:
        spec = resolve_provider(provider)
        cleaned = validate_secret(spec.key, secret)
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
            for record in records:
                if record.get("secret") == cleaned:
                    if not replace_duplicate:
                        raise ValueError("this key is already stored for that provider")
                    record["enabled"] = True
                    record["exhausted_until"] = None
                    record["last_error"] = ""
                    self._write(data)
                    return _status_from_record(spec.key, record)
            record = {
                "id": uuid.uuid4().hex[:10],
                "secret": cleaned,
                "label": (label or f"key {len(records) + 1}").strip()[:60],
                "enabled": True,
                "failures": 0,
                "uses": 0,
                "exhausted_until": None,
                "last_error": "",
                "last_used": None,
                "added_at": _utc_now().isoformat(timespec="seconds"),
            }
            records.append(record)
            data["keys"][spec.key] = records
            self._write(data)
        return _status_from_record(spec.key, record)

    def remove(self, provider: str, key_id: str) -> bool:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
            remaining = [record for record in records if record.get("id") != key_id]
            if len(remaining) == len(records):
                return False
            data["keys"][spec.key] = remaining
            self._write(data)
        return True

    def set_enabled(self, provider: str, key_id: str, enabled: bool) -> bool:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            for record in self._records(data, spec.key):
                if record.get("id") == key_id:
                    record["enabled"] = bool(enabled)
                    if enabled:
                        record["exhausted_until"] = None
                    self._write(data)
                    return True
        return False

    def statuses(self, provider: str) -> list[KeyStatus]:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
        return [_status_from_record(spec.key, record) for record in records]

    def secrets(self, provider: str) -> list[tuple[str, str]]:
        """``(key_id, secret)`` pairs in rotation order; never log this output."""
        spec = resolve_provider(provider)
        now = _utc_now()
        with self._lock:
            data = self._read()
            records = self._records(data, spec.key)
            usable = [
                record
                for record in records
                if _status_from_record(spec.key, record).usable(now)
            ]
            usable.sort(key=lambda record: record.get("last_used") or "")
        return [(str(record["id"]), str(record["secret"])) for record in usable]

    def count(self, provider: str) -> int:
        spec = resolve_provider(provider)
        with self._lock:
            return len(self._records(self._read(), spec.key))

    def usable_count(self, provider: str) -> int:
        return len(self.secrets(provider))

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "keys": self.count(name),
                "usable": self.usable_count(name),
            }
            for name in PROVIDERS
        }

    def mark_success(self, provider: str, key_id: str) -> None:
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            for record in self._records(data, spec.key):
                if record.get("id") == key_id:
                    record["failures"] = 0
                    record["uses"] = int(record.get("uses", 0)) + 1
                    record["last_used"] = _utc_now().isoformat(timespec="seconds")
                    record["last_error"] = ""
                    record["exhausted_until"] = None
            self._write(data)

    def mark_failure(
        self,
        provider: str,
        key_id: str,
        reason: str,
        *,
        cooldown_seconds: float,
    ) -> None:
        """Park a key for a cooldown after a quota, auth, or network failure."""
        spec = resolve_provider(provider)
        with self._lock:
            data = self._read()
            for record in self._records(data, spec.key):
                if record.get("id") != key_id:
                    continue
                record["failures"] = int(record.get("failures", 0)) + 1
                record["last_error"] = str(reason)[:200]
                until = _utc_now() + timedelta(seconds=max(0.0, cooldown_seconds))
                record["exhausted_until"] = until.isoformat(timespec="seconds")
            self._write(data)

    def reset(self, provider: str | None = None) -> int:
        """Clear cooldowns and failure counters (keys themselves are kept)."""
        with self._lock:
            data = self._read()
            targets = [provider] if provider else list(data["keys"])
            changed = 0
            for name in targets:
                for record in self._records(data, name):
                    record["failures"] = 0
                    record["exhausted_until"] = None
                    record["last_error"] = ""
                    changed += 1
            self._write(data)
        return changed


@dataclass(frozen=True, slots=True)
class AIResult:
    """Successful completion plus the rotation trace."""

    text: str
    provider: str
    model: str
    key_id: str
    key_label: str
    latency_ms: int
    attempts: tuple[dict[str, Any], ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "key_id": self.key_id,
            "key_label": self.key_label,
            "latency_ms": self.latency_ms,
            "attempts": list(self.attempts),
            "usage": self.usage,
        }


class AIError(RuntimeError):
    """Base class for provider problems."""


class NoAPIKeys(AIError):
    """No usable key is configured for the requested provider."""


class AllKeysFailed(AIError):
    """Every key was tried and none completed the request."""

    def __init__(self, message: str, attempts: Sequence[Mapping[str, Any]]) -> None:
        super().__init__(message)
        self.attempts = [dict(attempt) for attempt in attempts]


Transport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]


def _http_post(
    url: str, headers: Mapping[str, str], body: bytes, timeout: float
) -> tuple[int, bytes]:
    """POST JSON with stdlib only; HTTP errors are returned, not raised."""
    request = urllib.request.Request(
        url, data=body, headers=dict(headers), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        try:
            payload = error.read()
        except OSError:
            payload = b""
        return int(error.code), payload
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return 0, str(error).encode("utf-8")


def _error_detail(payload: bytes) -> str:
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeError):
        return payload.decode("utf-8", "replace")[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:300]
        if isinstance(error, str):
            return error[:300]
        if data.get("message"):
            return str(data["message"])[:300]
    return json.dumps(data)[:300]


def build_request(
    provider: str | Provider,
    secret: str,
    model: str,
    messages: Sequence[Mapping[str, str]],
    *,
    temperature: float = 0.3,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    system_prompt: str | None = None,
    base_url: str | None = None,
) -> tuple[str, dict[str, str], bytes]:
    """Build ``(url, headers, body)`` for a provider without sending it."""
    spec = provider if isinstance(provider, Provider) else resolve_provider(provider)
    base = (base_url or spec.base_url).rstrip("/")
    instruction = (system_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    if spec.api_style == "gemini":
        url = f"{base}/models/{model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": secret}
        contents = [
            {
                "role": "model" if message.get("role") == "assistant" else "user",
                "parts": [{"text": str(message.get("content", ""))}],
            }
            for message in messages
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": max(0.0, min(float(temperature), 2.0)),
                "maxOutputTokens": int(max_tokens),
            },
        }
        if instruction:
            payload["systemInstruction"] = {"parts": [{"text": instruction}]}
        return url, headers, json.dumps(payload).encode("utf-8")

    url = f"{base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {secret}",
    }
    if spec.key == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/jvrboy/NEEZY"
        headers["X-Title"] = "NEEZY"
    chat: list[dict[str, str]] = []
    if instruction:
        chat.append({"role": "system", "content": instruction})
    chat.extend(
        {
            "role": "assistant" if message.get("role") == "assistant" else "user",
            "content": str(message.get("content", "")),
        }
        for message in messages
    )
    body = {
        "model": model,
        "messages": chat,
        "temperature": max(0.0, min(float(temperature), 2.0)),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    return url, headers, json.dumps(body).encode("utf-8")


def parse_response(
    provider: str | Provider, payload: bytes
) -> tuple[str, dict[str, Any]]:
    """Extract assistant text and token usage from a provider response."""
    spec = provider if isinstance(provider, Provider) else resolve_provider(provider)
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise AIError(f"provider returned non-JSON output: {error}") from error
    if not isinstance(data, dict):
        raise AIError("provider returned an unexpected response shape")
    if spec.api_style == "gemini":
        candidates = data.get("candidates") or []
        if not candidates:
            raise AIError(
                "Gemini returned no candidate; the prompt may have been blocked"
            )
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts).strip()
        usage = data.get("usageMetadata") or {}
        return text, {
            "prompt_tokens": usage.get("promptTokenCount"),
            "completion_tokens": usage.get("candidatesTokenCount"),
        }
    choices = data.get("choices") or []
    if not choices:
        raise AIError("provider returned no choices")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):
        text = "".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        ).strip()
    else:
        text = str(content or "").strip()
    usage = data.get("usage") or {}
    return text, {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }


class AIClient:
    """Key-rotating chat client for one key store."""

    def __init__(
        self,
        store: AIKeyStore,
        *,
        transport: Transport | None = None,
        recorder: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        quota_cooldown: float = 900.0,
        auth_cooldown: float = 86_400.0,
        transient_cooldown: float = 60.0,
    ) -> None:
        self.store = store
        self.transport = transport or _http_post
        self.recorder = recorder
        self.clock = clock
        self.quota_cooldown = quota_cooldown
        self.auth_cooldown = auth_cooldown
        self.transient_cooldown = transient_cooldown

    def _record(self, **kwargs: Any) -> None:
        if self.recorder is None:
            return
        try:
            self.recorder(**kwargs)
        except Exception:  # noqa: BLE001 - telemetry must never break a chat
            return

    def chat(
        self,
        provider: str,
        messages: Sequence[Mapping[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: float = 45.0,
        base_url: str | None = None,
        system_prompt: str | None = None,
    ) -> AIResult:
        spec = resolve_provider(provider)
        chosen_model = resolve_model(spec.key, model)
        if not messages:
            raise ValueError("messages must not be empty")
        secrets = self.store.secrets(spec.key)
        if not secrets:
            raise NoAPIKeys(
                f"No usable {spec.label} key. Add one in Settings → AI providers."
            )
        prompt_chars = sum(len(str(message.get("content", ""))) for message in messages)
        attempts: list[dict[str, Any]] = []
        for key_id, secret in secrets:
            status = next(
                (item for item in self.store.statuses(spec.key) if item.id == key_id),
                None,
            )
            label = status.label if status else "key"
            url, headers, body = build_request(
                spec,
                secret,
                chosen_model,
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                base_url=base_url,
            )
            started = self.clock()
            try:
                http_status, payload = self.transport(url, headers, body, timeout)
            except Exception as error:  # noqa: BLE001 - transport is injected
                http_status, payload = 0, str(error).encode("utf-8")
            elapsed_ms = max(0, int((self.clock() - started) * 1000))

            if http_status == 200:
                try:
                    text, usage = parse_response(spec, payload)
                except AIError as error:
                    self.store.mark_failure(
                        spec.key, key_id, str(error), cooldown_seconds=0
                    )
                    attempts.append(
                        {"key": label, "status": "bad-response", "detail": str(error)}
                    )
                    self._record(
                        provider=spec.key,
                        model=chosen_model,
                        key_label=label,
                        status="bad-response",
                        latency_ms=elapsed_ms,
                        prompt_chars=prompt_chars,
                        detail=str(error),
                    )
                    continue
                self.store.mark_success(spec.key, key_id)
                attempts.append({"key": label, "status": "ok", "detail": ""})
                self._record(
                    provider=spec.key,
                    model=chosen_model,
                    key_label=label,
                    status="ok",
                    latency_ms=elapsed_ms,
                    prompt_chars=prompt_chars,
                    response_chars=len(text),
                )
                return AIResult(
                    text=text,
                    provider=spec.key,
                    model=chosen_model,
                    key_id=key_id,
                    key_label=label,
                    latency_ms=elapsed_ms,
                    attempts=tuple(attempts),
                    usage=usage,
                )

            detail = _error_detail(payload) or f"HTTP {http_status}"
            if http_status in {401, 403}:
                bucket, cooldown = "auth", self.auth_cooldown
            elif http_status in {402, 429}:
                bucket, cooldown = "quota", self.quota_cooldown
            elif http_status == 0 or http_status >= 500:
                bucket, cooldown = "transient", self.transient_cooldown
            elif http_status in {400, 404, 422}:
                # A bad model id or malformed request will fail on every key.
                self._record(
                    provider=spec.key,
                    model=chosen_model,
                    key_label=label,
                    status="request-error",
                    latency_ms=elapsed_ms,
                    prompt_chars=prompt_chars,
                    detail=detail,
                )
                raise AIError(f"{spec.label} rejected the request: {detail}")
            else:
                bucket, cooldown = "transient", self.transient_cooldown
            self.store.mark_failure(spec.key, key_id, detail, cooldown_seconds=cooldown)
            attempts.append(
                {"key": label, "status": bucket, "detail": detail, "http": http_status}
            )
            self._record(
                provider=spec.key,
                model=chosen_model,
                key_label=label,
                status=bucket,
                latency_ms=elapsed_ms,
                prompt_chars=prompt_chars,
                detail=f"HTTP {http_status}: {detail}",
            )

        tried = ", ".join(
            f"{attempt['key']} ({attempt['status']})" for attempt in attempts
        )
        raise AllKeysFailed(
            f"All {spec.label} keys are cooling down or failed: {tried}. "
            "Add another key in Settings → AI providers.",
            attempts,
        )


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_SYSTEM_PROMPT",
    "PROVIDERS",
    "AIClient",
    "AIError",
    "AIKeyStore",
    "AIResult",
    "AllKeysFailed",
    "KeyStatus",
    "NoAPIKeys",
    "Provider",
    "build_request",
    "free_models",
    "is_free_model",
    "mask_secret",
    "models_with_extra",
    "parse_response",
    "provider_names",
    "resolve_model",
    "resolve_provider",
    "validate_secret",
]
