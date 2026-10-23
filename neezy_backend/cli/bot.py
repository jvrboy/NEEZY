"""Read-only loopback status for the lightweight NEEZY executor."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from .common import _emit

_MAX_STATUS_BYTES = 256_000


def _ascii(value: object) -> str:
    return str(value).encode("ascii", "replace").decode("ascii")


def _read_status(timeout: float) -> dict:
    # Imported lazily so the rest of the CLI does not load executor machinery.
    from ..executor_config import load_executor_config

    config = load_executor_config()
    # ExecutorConfig restricts this host to loopback; do not accept a URL argument.
    url = f"http://{config.status_host}:{config.status_port}/api/status"
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        content = response.read(_MAX_STATUS_BYTES + 1)
    if len(content) > _MAX_STATUS_BYTES:
        raise ValueError("executor status response exceeds the size limit")
    document = json.loads(content.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("executor status must be a JSON object")
    return document


def cmd_bot(args, fetch, out) -> int:
    del fetch
    if args.action != "status":
        raise ValueError(f"unknown bot action {args.action!r}")
    if not 0.1 <= args.timeout <= 5.0:
        raise ValueError("bot status timeout must be between 0.1 and 5 seconds")
    try:
        document = _read_status(args.timeout)
    except (OSError, ValueError) as error:
        out.write("Executor offline or unavailable on loopback.\n")
        out.write(f"Reason: {_ascii(error)}\n")
        out.write("No executor action or order was attempted.\n")
        return 1
    if args.json:
        _emit(out, document)
        return 0

    execution = document.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    open_trades = document.get("open_trades")
    models = document.get("models")
    issues = document.get("issues")
    paper = document.get("paper_validation")
    out.write(f"Service: {_ascii(document.get('service', 'neezy-light-executor'))}\n")
    out.write(f"Status: {_ascii(document.get('status', 'unknown'))}\n")
    out.write(f"Heartbeat: {_ascii(document.get('heartbeat_utc', 'unknown'))}\n")
    enabled = execution.get("enabled") is True
    out.write(f"Execution: {'enabled' if enabled else 'disabled / observer'}\n")
    out.write(f"Mode: {_ascii(execution.get('mode', 'unknown'))}\n")
    out.write(
        f"Open trades: {len(open_trades) if isinstance(open_trades, list) else 0}\n"
    )
    if isinstance(models, dict):
        active = sum(
            isinstance(value, dict) and value.get("active") is True
            for value in models.values()
        )
        out.write(f"Models: {active} active / {len(models)} configured\n")
    if isinstance(paper, dict):
        out.write(f"Paper validation: {_ascii(paper.get('status', 'unknown'))}\n")
    issue_rows = issues if isinstance(issues, list) else []
    out.write(f"Issues: {len(issue_rows)}\n")
    for issue in issue_rows[:5]:
        if isinstance(issue, dict):
            message = _ascii(issue.get("message", issue.get("code", "unknown")))
            out.write(f"  - {message[:240]}\n")
    out.write("Read-only status; no executor action or order was attempted.\n")
    return 0
