"""Dependency-free JSON Schema validator for the subset used by Tideglass.

Supported keywords: ``type`` (incl. lists), ``enum``, ``const``, ``required``,
``properties``, ``additionalProperties`` (bool or schema), ``items``,
``minItems``, ``maxItems``, ``minimum``, ``maximum``, ``exclusiveMinimum``,
``minLength``, ``pattern`` and local ``$ref`` to ``#/$defs/...``. If the
optional ``jsonschema`` package is installed it is used instead, giving full
Draft 2020-12 coverage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Mapping


class SchemaError(ValueError):
    """Raised when a document does not satisfy its schema."""

    def __init__(self, errors: List[str], source: str = "document") -> None:
        self.errors = errors
        head = f"{source} failed schema validation ({len(errors)} error(s)):\n  - "
        super().__init__(head + "\n  - ".join(errors[:20]))


_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _check(
    value: Any,
    schema: Mapping[str, Any],
    path: str,
    root: Mapping[str, Any],
    errs: List[str],
) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"Only local $ref supported, got {ref}")
        target: Any = root
        for part in ref[2:].split("/"):
            target = target[part]
        _check(value, target, path, root, errs)
        return
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPES[x](value) for x in types):
            errs.append(
                f"{path}: expected {'/'.join(types)}, got {type(value).__name__}"
            )
            return
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errs.append(
                f"{path}: {value} <= exclusiveMinimum {schema['exclusiveMinimum']}"
            )
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(item, schema["items"], f"{path}[{i}]", root, errs)
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}: missing required property '{req}'")
        props = schema.get("properties", {})
        addl = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                _check(v, props[k], f"{path}.{k}", root, errs)
            elif addl is False:
                errs.append(f"{path}: unexpected property '{k}'")
            elif isinstance(addl, dict):
                _check(v, addl, f"{path}.{k}", root, errs)


def validate(doc: Any, schema: Mapping[str, Any], source: str = "document") -> None:
    """Validate ``doc`` against ``schema`` and raise :class:`SchemaError` on failure."""
    try:  # Prefer the full implementation when available.
        import jsonschema  # type: ignore

        validator = jsonschema.Draft202012Validator(schema)
        errors = [
            f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
            for e in validator.iter_errors(doc)
        ]
    except ImportError:
        errors = []
        _check(doc, schema, "<root>", schema, errors)
    if errors:
        raise SchemaError(errors, source)


def validate_file(doc_path: Path, schema_path: Path) -> Any:
    """Load a JSON file, validate it and return the parsed document."""
    with open(doc_path, encoding="utf-8") as fh:
        doc = json.load(fh)
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)
    validate(doc, schema, str(doc_path))
    return doc
