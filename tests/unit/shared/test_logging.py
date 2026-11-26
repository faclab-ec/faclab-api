from src.shared.infra.logging import redact_sensitive


def test_sensitive_keys_are_redacted_at_any_depth():
    event = {
        "event": "login",
        "username": "ana",
        "password": "s3cret",
        "body": {"newPassword": "s3cret", "items": [{"refresh_token": "rt"}]},
        "headers": {"Authorization": "Bearer abc", "Set-Cookie": "faclab_refresh=x"},
    }

    redacted = redact_sensitive(None, "info", event)

    assert redacted["username"] == "ana"
    assert redacted["password"] == "[REDACTED]"
    assert redacted["body"]["newPassword"] == "[REDACTED]"
    assert redacted["body"]["items"][0]["refresh_token"] == "[REDACTED]"
    assert redacted["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["headers"]["Set-Cookie"] == "[REDACTED]"
    assert "s3cret" not in str(redacted)


def test_other_values_are_left_alone():
    event = {"event": "sale_confirmed", "tokens_used": 3, "loc": ("body", "items")}

    assert redact_sensitive(None, "info", dict(event)) == event


def test_new_blocked_keys_are_redacted():
    event = {
        "event": "invoice_signed",
        "xml": "<factura/>",
        "p12": b"\x30\x82",
        "privateKey": "-----BEGIN",
        "client_secret": "cs",
        "signature": "sig",
        "certificate": {"serial": "1"},
    }

    redacted = redact_sensitive(None, "info", event)

    assert redacted == {"event": "invoice_signed"} | {
        key: "[REDACTED]" for key in event if key != "event"
    }


def test_trace_context_comes_from_the_active_span():
    from opentelemetry.sdk.trace import TracerProvider

    from src.shared.infra.logging import add_trace_context

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("request") as span:
        event = add_trace_context(None, "info", {"event": "x"})

    assert event["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert event["span_id"] == format(span.get_span_context().span_id, "016x")
    assert "trace_id" not in add_trace_context(None, "info", {"event": "x"})


def test_event_name_is_derived_from_the_event():
    from src.shared.infra.logging import add_event_name

    def name(**event):
        return add_event_name(None, "info", event)["event.name"]

    assert name(event="outbox_publish_failed") == "outbox.publish.failed"
    # Free text from another library: the name of its logger
    assert name(event="Started server process [7]", logger="uvicorn.error") == (
        "uvicorn.error"
    )
    assert name(event="sale_confirmed", **{"event.name": "sale.confirmed"}) == (
        "sale.confirmed"
    )


def test_json_logs_keep_the_traceback(json_logs):
    import structlog

    try:
        raise ZeroDivisionError("division by zero")
    except ZeroDivisionError:
        structlog.get_logger("tests").exception("unexpected_failure")

    line = next(line for line in json_logs() if line["event"] == "unexpected_failure")
    assert "ZeroDivisionError" in line["exception"]
    assert line["service.name"] == "faclab-core"


def test_personal_data_keys_are_redacted_but_names_of_things_are_not():
    event = {
        "event": "customer_imported",
        "email": "ana@example.com",
        "tax_id": "1790012345001",
        "customer": {"phone": "0999999999", "Address": "Av. 1", "fullName": "Ana"},
        "branch_name": "Matriz",
        "name": "Matriz",
    }

    redacted = redact_sensitive(None, "info", event)

    assert redacted["email"] == "[REDACTED]"
    assert redacted["tax_id"] == "[REDACTED]"
    assert redacted["customer"] == {
        "phone": "[REDACTED]",
        "Address": "[REDACTED]",
        "fullName": "[REDACTED]",
    }
    assert redacted["name"] == "Matriz"
    assert redacted["branch_name"] == "Matriz"


def test_audit_keeps_the_personal_data_the_log_redacts():
    from src.shared.infra.logging import is_pii_key, is_sensitive_key

    # The audit trail drops is_sensitive_key keys from before/after: email and
    # tax_id are not among them, only the log hides them
    assert is_pii_key("tax_id") and not is_sensitive_key("tax_id")
    assert is_pii_key("email") and not is_sensitive_key("email")


def test_mask_identification_keeps_the_ends_only():
    from src.shared.infra.logging import mask_identification

    assert mask_identification("1790012345001") == "17*********01"
    assert mask_identification("1234") == "****"
    assert mask_identification(None) is None
