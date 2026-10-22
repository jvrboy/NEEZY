"""Static provider catalogue: endpoints, free models, aliases, key checks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


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
