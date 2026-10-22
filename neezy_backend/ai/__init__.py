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

Package layout (roadmap #12 — transport separated from prompt logic):

- ``errors``     result type + exception hierarchy (dependency-free)
- ``prompts``    system prompt and default token budget
- ``providers``  static provider catalogue, aliases, model and secret helpers
- ``keystore``   local multi-key vault with health and cooldown state
- ``transport``  HTTP POST, request building, response parsing (injectable)
- ``client``     key-rotating failover client

Sibling modules ``neezy_backend.ai_cache`` (answer cache) and
``neezy_backend.ai_resilient`` (retry wrapper) build on this package.
This ``__init__`` re-exports the historical public surface of the former
``ai.py`` monolith, so ``from neezy_backend.ai import AIClient`` (and every
other pre-existing name) keeps working unchanged.
"""

from __future__ import annotations

from .client import AIClient
from .errors import AIError, AIResult, AllKeysFailed, NoAPIKeys
from .keystore import AIKeyStore, KeyStatus
from .prompts import DEFAULT_MAX_TOKENS, DEFAULT_SYSTEM_PROMPT
from .providers import (
    PROVIDERS,
    Provider,
    free_models,
    is_free_model,
    mask_secret,
    models_with_extra,
    provider_names,
    resolve_model,
    resolve_provider,
    validate_secret,
)
from .transport import Transport, build_request, parse_response

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
    "Transport",
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
