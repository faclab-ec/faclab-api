"""How `POST /api/oauth/token` reads the client's credentials (RFC 6749 §2.3):
HTTP Basic or the form, never both."""

import base64
from urllib.parse import quote

import pytest

from src.integrations.infra.oauth_routes import _credentials, _OAuthError


def _basic(client_id: str, secret: str) -> str:
    raw = f"{quote(client_id, safe='')}:{quote(secret, safe='')}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def test_http_basic():
    credentials = _credentials(_basic("fl_test_0123456789ab", "s3:cr/t"), None, None)

    assert credentials.client_id == "fl_test_0123456789ab"
    # Form-urlencoded inside Basic
    assert credentials.client_secret == "s3:cr/t"


def test_the_form():
    credentials = _credentials(None, "fl_test_0123456789ab", "secret")

    assert (credentials.client_id, credentials.client_secret) == (
        "fl_test_0123456789ab",
        "secret",
    )


def test_basic_with_the_same_client_id_in_the_form():
    credentials = _credentials(
        _basic("fl_test_0123456789ab", "secret"), "fl_test_0123456789ab", None
    )

    assert credentials.client_secret == "secret"


@pytest.mark.parametrize(
    ("authorization", "client_id", "client_secret", "status", "error"),
    [
        # Two methods at once
        (_basic("fl_test_0123456789ab", "a"), None, "b", 400, "invalid_request"),
        (
            _basic("fl_test_0123456789ab", "a"),
            "fl_test_ffffffffffff",
            None,
            400,
            "invalid_request",
        ),
        # No credentials, or half of them
        (None, None, None, 401, "invalid_client"),
        (None, "fl_test_0123456789ab", None, 401, "invalid_client"),
        ("Bearer abc", None, None, 401, "invalid_client"),
        # Not base64, or without the colon
        ("Basic %%%", None, None, 401, "invalid_client"),
        (
            "Basic " + base64.b64encode(b"nocolon").decode(),
            None,
            None,
            401,
            "invalid_client",
        ),
    ],
)
def test_bad_credentials(authorization, client_id, client_secret, status, error):
    with pytest.raises(_OAuthError) as raised:
        _credentials(authorization, client_id, client_secret)

    assert (raised.value.status, raised.value.error) == (status, error)
