"""Key-rotating chat client with cooldown-aware failover."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .errors import AIError, AIResult, AllKeysFailed, NoAPIKeys
from .keystore import AIKeyStore
from .prompts import DEFAULT_MAX_TOKENS
from .providers import resolve_model, resolve_provider
from .transport import (
    Transport,
    _error_detail,
    _http_post,
    build_request,
    parse_response,
)


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
