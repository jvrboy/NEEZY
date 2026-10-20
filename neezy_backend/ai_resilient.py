"""AI client with answer caching and per-provider circuit breaking.

Drop-in replacement for :class:`~neezy_backend.ai.AIClient`:

* Identical long prompts (market context + question) are answered from a short
  TTL cache instead of spending provider quota. Short prompts such as the
  connectivity test are never cached, so "Test" always reaches the provider.
* After repeated all-keys-failed errors a provider is paused for a cool-down,
  so the UI fails fast instead of waiting on timeouts.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .ai import (
    DEFAULT_MAX_TOKENS,
    AIClient,
    AIError,
    AIKeyStore,
    AIResult,
    AllKeysFailed,
    resolve_model,
    resolve_provider,
)
from .ai_cache import AnswerCache
from .resilience import CircuitBreaker


class ResilientAIClient(AIClient):
    """Key-rotating chat client plus answer cache and circuit breaker."""

    def __init__(
        self,
        store: AIKeyStore,
        *,
        cache: AnswerCache | None = None,
        breaker_factory: Callable[[], CircuitBreaker] = CircuitBreaker,
        min_cache_chars: int = 80,
        **kwargs: Any,
    ) -> None:
        super().__init__(store, **kwargs)
        self.cache = cache or AnswerCache()
        self.min_cache_chars = min_cache_chars
        self._breaker_factory = breaker_factory
        self._breakers: dict[str, CircuitBreaker] = {}
        self._breaker_lock = threading.Lock()

    def breaker(self, provider_key: str) -> CircuitBreaker:
        with self._breaker_lock:
            if provider_key not in self._breakers:
                self._breakers[provider_key] = self._breaker_factory()
            return self._breakers[provider_key]

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
        chosen = resolve_model(spec.key, model)
        size = sum(len(str(message.get("content", ""))) for message in messages)
        cacheable = size >= self.min_cache_chars
        key = AnswerCache.make_key(
            spec.key,
            chosen,
            [dict(message) for message in messages],
            f"{system_prompt or ''}|{base_url or ''}|{max_tokens}",
            temperature,
        )
        if cacheable:
            hit = self._from_cache(key, spec.key, chosen)
            if hit is not None:
                return hit
        breaker = self.breaker(spec.key)
        if not breaker.allow():
            raise AIError(
                f"{spec.label} is paused after repeated failures; retrying shortly."
            )
        try:
            result = super().chat(
                provider,
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                base_url=base_url,
                system_prompt=system_prompt,
            )
        except AllKeysFailed:
            breaker.record_failure()
            raise
        breaker.record_success()
        if cacheable and result.text:
            blob = json.dumps({"text": result.text, "usage": result.usage})
            self.cache.put(key, blob)
        return result

    def _from_cache(self, key: str, provider_key: str, model: str) -> AIResult | None:
        cached = self.cache.get(key)
        if cached is None:
            return None
        try:
            data = json.loads(cached)
            text = str(data["text"])
        except (ValueError, KeyError, TypeError):
            return None
        return AIResult(
            text=text,
            provider=provider_key,
            model=model,
            key_id="cache",
            key_label="cache",
            latency_ms=0,
            attempts=({"key": "cache", "status": "cache-hit", "detail": ""},),
            usage=data.get("usage") or {},
        )
