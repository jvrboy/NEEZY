"""AI CLI commands: BYOK providers, key pools, chat, and local models."""

from __future__ import annotations

import getpass
import os

from ..ai import (
    PROVIDERS,
    AIClient,
    AIKeyStore,
    free_models,
    resolve_provider,
)
from ..context import chat_messages, format_context, market_snapshot
from ..markets import granularity
from .common import _emit, _open_database, _symbol, _table


def _ai_store() -> AIKeyStore:
    return AIKeyStore()


def _resolve_secret(args, provider: str) -> str:
    if args.key:
        return args.key
    from_env = os.environ.get("NEEZY_AI_KEY", "").strip()
    if from_env:
        return from_env
    return getpass.getpass(f"Paste the {provider} API key (input hidden): ")


def cmd_ai(args, fetch, out) -> int:
    store = _ai_store()
    if args.action == "providers":
        payload = [
            {
                **spec.to_dict(),
                "keys": store.count(spec.key),
                "usable_keys": store.usable_count(spec.key),
            }
            for spec in PROVIDERS.values()
        ]
        if args.json:
            _emit(out, payload)
            return 0
        _table(
            out,
            ["PROVIDER", "MODELS", "KEYS", "USABLE", "BASE URL"],
            [
                (
                    item["label"],
                    len(item["models"]),
                    item["keys"],
                    item["usable_keys"],
                    item["base_url"],
                )
                for item in payload
            ],
        )
        out.write(
            "\nFree models only; add keys with 'neezy-cli ai keys add PROVIDER'.\n"
        )
        return 0
    if args.action == "models":
        spec = resolve_provider(args.provider)
        models = free_models(spec.key)
        if args.json:
            _emit(out, {"provider": spec.key, "models": models})
            return 0
        out.write(f"{spec.label} free models:\n")
        for model in models:
            out.write(f"  {model}\n")
        return 0
    if args.action == "keys":
        if not args.verb:
            summaries = []
            for spec in PROVIDERS.values():
                for status in store.statuses(spec.key):
                    summaries.append({**status.to_dict(), "provider_label": spec.label})
            if args.json:
                _emit(out, summaries)
                return 0
            _table(
                out,
                ["PROVIDER", "ID", "LABEL", "KEY", "USABLE", "USES", "LAST ERROR"],
                [
                    (
                        item["provider_label"],
                        item["id"],
                        item["label"],
                        item["hint"],
                        "yes" if item["usable"] else "no",
                        item["uses"],
                        item["last_error"][:40],
                    )
                    for item in summaries
                ],
            )
            return 0
        if args.verb == "add":
            spec = resolve_provider(args.provider)
            status = store.add(
                spec.key, _resolve_secret(args, spec.label), args.label or ""
            )
            if args.json:
                _emit(out, status.to_dict())
                return 0
            out.write(f"Stored {spec.label} key '{status.label}' ({status.hint}).\n")
            return 0
        if args.verb == "remove":
            spec = resolve_provider(args.provider)
            removed = store.remove(spec.key, args.key_id)
            out.write(
                f"Removed key {args.key_id}\n" if removed else f"No key {args.key_id}\n"
            )
            return 0 if removed else 1
        if args.verb == "reset":
            changed = store.reset(args.provider.lower() if args.provider else None)
            out.write(f"Cleared cooldowns on {changed} key(s).\n")
            return 0
        raise ValueError(f"unknown ai keys action {args.verb!r}")
    if args.action == "chat":
        spec = resolve_provider(args.provider)
        context = ""
        if args.symbol:
            symbol = _symbol(args.symbol)
            try:
                candles = fetch(symbol, granularity(args.timeframe), args.count)
                snapshot = market_snapshot(
                    candles, symbol=symbol, timeframe=args.timeframe
                )
                if snapshot:
                    context = format_context(snapshot)
            except (OSError, RuntimeError, ValueError) as error:
                out.write(f"! market context unavailable: {error}\n")
        messages = chat_messages(args.prompt, context or "No live context supplied.")
        with _open_database() as database:
            client = AIClient(store, recorder=database.record_ai_call)
            result = client.chat(
                spec.key,
                messages,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            )
        if args.json:
            _emit(out, result.to_dict())
            return 0
        out.write(f"{result.text}\n\n")
        out.write(
            f"[{spec.label} · {result.model} · key {result.key_label} · "
            f"{result.latency_ms} ms]\n"
        )
        return 0
    if args.action == "usage":
        with _open_database() as database:
            payload = database.ai_usage(args.limit)
        if args.json:
            _emit(out, payload)
            return 0
        out.write(f"{payload['total']} recent AI calls\n")
        _table(
            out,
            ["PROVIDER", "CALLS"],
            sorted(payload["by_provider"].items()),
        )
        _table(out, ["STATUS", "CALLS"], sorted(payload["by_status"].items()))
        return 0
    if args.action == "reset":
        changed = store.reset()
        out.write(f"Cleared cooldowns on {changed} key(s).\n")
        return 0
    raise ValueError(f"unknown ai action {args.action!r}")


def cmd_local_model(args, fetch, out) -> int:
    """Inspect, register, or run user-supplied local generative models."""
    del fetch
    from ..local_llm import LocalModelRegistry, generate_chat, runtime_status

    registry = LocalModelRegistry()
    if args.action == "runtime":
        payload = runtime_status()
        if args.json:
            _emit(out, payload)
        else:
            for name, available in payload.items():
                out.write(f"{name}: {'available' if available else 'not installed'}\n")
        return 0
    if args.action == "list":
        models = registry.list_models()
        payload = [model.to_dict() for model in models]
        if args.json:
            _emit(out, payload)
        else:
            _table(
                out,
                ["ID", "NAME", "FORMAT", "MODEL TYPE", "SIZE", "PATH"],
                [
                    (
                        model.model_id,
                        model.name,
                        model.format,
                        model.model_type,
                        f"{model.size_bytes / (1024**3):.2f} GiB",
                        model.path,
                    )
                    for model in models
                ],
            )
        return 0
    if args.action == "add":
        model = registry.register(args.path, name=args.name)
        if args.json:
            _emit(out, model.to_dict())
        else:
            out.write(
                f"Registered {model.name} ({model.format}, "
                f"{model.size_bytes / (1024**3):.2f} GiB) as {model.model_id}.\n"
                "Model files were not copied.\n"
            )
        return 0
    if args.action == "remove":
        model = registry.remove(args.model_id)
        if args.json:
            _emit(out, {"removed": model.model_id, "name": model.name})
        else:
            out.write(
                f"Removed {model.name} from NEEZY's index; source files were kept.\n"
            )
        return 0
    if args.action == "chat":
        model = registry.get(args.model_id)
        answer = generate_chat(
            model,
            [{"role": "user", "content": args.prompt}],
            context_tokens=args.context,
            max_tokens=args.max_tokens,
            threads=args.threads,
            batch_size=args.batch_size,
            disk_offload=args.disk_offload,
            cpu_memory_mb=args.cpu_memory_mb,
            temperature=args.temperature,
        )
        if args.json:
            _emit(
                out, {"model_id": model.model_id, "model": model.name, "text": answer}
            )
        else:
            out.write(f"{answer}\n\n[local model · {model.name}]\n")
        return 0
    raise ValueError(f"unknown local-model action {args.action!r}")
