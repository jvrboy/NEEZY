"""HTTP transports and wire formats for the supported AI providers.

``build_request`` turns a chat into ``(url, headers, body)`` per provider API
style; ``parse_response`` turns a 200 payload back into text and usage. The
``Transport`` callable is injected so tests and the resilient client can
swap the network layer.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .errors import AIError
from .prompts import DEFAULT_MAX_TOKENS, DEFAULT_SYSTEM_PROMPT
from .providers import Provider, resolve_provider

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
