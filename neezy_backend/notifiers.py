"""Notification ports/adapters (roadmap #13).

Unifies :mod:`telegram` and :mod:`dm` (and future Discord/email) under a single
``Notifier`` protocol with a fan-out ``CompositeNotifier``.  UI and
``alerts`` talk only to the interface so adding a sink never touches caller
code and tests can intercept notifications via ``MemoryNotifier``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Notification:
    """One portable notification."""

    title: str
    body: str
    level: str = "info"  # info | warning | error
    fields: dict[str, Any] | None = None
    source: str = ""


class Notifier(Protocol):
    """Port for outbound notifications."""

    def send(
        self, notification: Notification
    ) -> dict[str, Any]:  # pragma: no cover - protocol
        ...

    def health(self) -> dict[str, Any]:  # pragma: no cover - protocol
        ...


class TelegramNotifier:
    """Adapter over :mod:`neezy_backend.telegram`."""

    def __init__(self, chat_ids: list[str] | None = None) -> None:
        self._chat_ids = list(chat_ids or [])

    def send(self, notification: Notification) -> dict[str, Any]:
        from .telegram import TelegramNotifier as _Base  # lazy import

        try:
            base = _Base()
            text = notification.body
            if notification.fields:
                text += "\n" + "\n".join(
                    f"{k}: {v}" for k, v in notification.fields.items()
                )
            return base.send_message(text)  # type: ignore[no-untyped-call]
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - network
            return {"success": False, "error": str(exc)}

    def health(self) -> dict[str, Any]:
        return {"notifier": "telegram", "configured": bool(self._chat_ids)}


class WebhookNotifier:
    """Adapter over :mod:`neezy_backend.dm` webhooks (Discord/Slack/generic)."""

    def __init__(
        self,
        webhook_url: str = "",
        *,
        webhook_format: str = "auto",
        https_only: bool = False,
    ) -> None:
        self.webhook_url = webhook_url
        self.webhook_format = webhook_format
        self.https_only = https_only

    def send(self, notification: Notification) -> dict[str, Any]:
        from .dm import send_dm_notification  # lazy

        return send_dm_notification(
            self.webhook_url,
            notification.title,
            notification.body,
            level=notification.level,
            fields=notification.fields,
            webhook_format=self.webhook_format,
            https_only=self.https_only,
        )

    def health(self) -> dict[str, Any]:
        return {
            "notifier": "webhook",
            "configured": bool(self.webhook_url),
            "format": self.webhook_format,
        }


class MemoryNotifier:
    """In-memory sink for tests."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> dict[str, Any]:
        self.sent.append(notification)
        return {"success": True, "notifier": "memory"}

    def health(self) -> dict[str, Any]:
        return {"notifier": "memory", "sent": len(self.sent)}


class CompositeNotifier:
    """Fan-out: send to every child; aggregate results."""

    def __init__(self, notifiers: list[Notifier] | None = None) -> None:
        self.notifiers: list[Notifier] = list(notifiers or [])

    def add(self, notifier: Notifier) -> None:
        self.notifiers.append(notifier)

    def send(self, notification: Notification) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for channel in self.notifiers:
            try:
                results.append(channel.send(notification))
            except Exception as exc:  # noqa: BLE001  # pragma: no cover
                results.append(
                    {"success": False, "error": str(exc), "notifier": repr(channel)}
                )
        ok = all(r.get("success") for r in results) if results else True
        return {"success": ok, "results": results, "count": len(results)}

    def health(self) -> dict[str, Any]:
        return {
            "notifier": "composite",
            "channels": len(self.notifiers),
            "children": [n.health() for n in self.notifiers],
        }
