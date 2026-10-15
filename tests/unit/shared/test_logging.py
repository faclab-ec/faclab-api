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
