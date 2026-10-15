"""Guard test: no request body names who did something.

The author of a shift, sale, cash movement, refund, adjustment or transfer is
the authenticated user; a field in the body would let a caller sign as someone
else. Body models are read from the real application.
"""

from fastapi.routing import APIRoute
from pydantic import BaseModel

from main import app

AUTHOR_FIELDS = {
    "cashier_name",
    "created_by",
    "performed_by",
    "refunded_by",
    "adjusted_by",
    "requested_by",
    "approved_by",
    "received_by",
}


def _models(annotation) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        nested = [
            model
            for field in annotation.model_fields.values()
            for model in _models(field.annotation)
        ]
        return [annotation, *nested]
    return [m for arg in getattr(annotation, "__args__", ()) for m in _models(arg)]


def test_no_request_body_carries_an_author_field():
    offenders: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for param in route.dependant.body_params:
            for model in _models(param.field_info.annotation):
                found = AUTHOR_FIELDS & set(model.model_fields)
                if found:
                    offenders.append(f"{route.path}: {model.__name__} {sorted(found)}")
    assert not offenders, "Author fields in request bodies:\n  - " + "\n  - ".join(
        offenders
    )
