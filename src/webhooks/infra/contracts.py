"""The JSON Schema of each webhook event (S6.4): the published contract.

`docs/public-api/webhooks/v1/<type>.schema.json` keeps the current one
(`make public-openapi` writes them, a test fails while they differ). They are
open, like the API's: a receiver ignores the fields it doesn't know, which are
added without a new version.
"""

import json
from pathlib import Path
from typing import Any

from src.webhooks.infra.schemas import EVENT_MODELS

SNAPSHOTS = Path(__file__).resolve().parents[3] / "docs/public-api/webhooks/v1"


def _untitled(value: Any) -> Any:
    """Without the titles Pydantic derives from each name ("Productid")"""
    if isinstance(value, dict):
        return {k: _untitled(v) for k, v in value.items() if k != "title"}
    if isinstance(value, list):
        return [_untitled(v) for v in value]
    return value


def event_schema(event_type: str) -> dict:
    model = EVENT_MODELS[event_type]
    schema = _untitled(model.model_json_schema(mode="serialization", by_alias=True))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://faclab.ec/webhooks/v1/{event_type}.schema.json",
        **schema,
        "title": f"{event_type} v1",
    }


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def snapshot_path(event_type: str) -> Path:
    return SNAPSHOTS / f"{event_type}.schema.json"


def main() -> None:
    """`make public-openapi` writes them next to the OpenAPI"""
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    for event_type in EVENT_MODELS:
        snapshot_path(event_type).write_text(render(event_schema(event_type)))
    print(f"wrote {SNAPSHOTS.relative_to(SNAPSHOTS.parents[3])}")


if __name__ == "__main__":
    main()
