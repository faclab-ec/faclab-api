"""Loads the event contracts in `contracts/events/` (see contracts/README.md)."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator

EVENTS = Path(__file__).resolve().parents[2] / "contracts" / "events"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validator(topic: str, version: int = 1) -> Validator:
    schema = _load(EVENTS / topic / f"v{version}.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def examples(topic: str) -> dict[str, dict[str, Any]]:
    """Example messages of a topic, by file name without extension."""
    return {
        path.stem: _load(path)
        for path in sorted((EVENTS / topic / "examples").glob("*.json"))
    }


def errors(validator: Validator, message: Any) -> list[str]:
    """Every way the message breaks the schema; empty when it complies."""
    return [
        f"/{'/'.join(map(str, error.absolute_path))}: {error.message}"
        for error in validator.iter_errors(message)
    ]
