"""Config loader with JSON-Schema validation for TideForge configs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import jsonschema


class ConfigError(ValueError):
    """Raised when a config file fails schema validation."""


def validate_against_schema(data: Any, schema_path: str | Path) -> None:
    schema = json.loads(Path(schema_path).read_text())
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        raise ConfigError(
            f"config does not match schema {schema_path}: "
            f"{exc.message} at {list(exc.absolute_path)}"
        ) from exc


def load_config(path: str | Path, schema: str | Path | None = None) -> Dict:
    cfg = json.loads(Path(path).read_text())
    if schema:
        validate_against_schema(cfg, schema)
    return cfg
