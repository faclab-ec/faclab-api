"""The platform operator's token (S8.5): no tenant, for this service only, and
never taken for a company's or an integration's."""

from typing import Any
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.auth.app.services.token_service import PlatformTokenClaims
from src.auth.domain.entities import User
from src.auth.domain.exceptions import InvalidTokenError
from src.auth.infra.signing_keys import JwtKeys
from src.auth.infra.token_service import JwtTokenService
from tests.tokens import sign_token

KEY = Ed25519PrivateKey.generate()


def _service(ttl: int = 600) -> JwtTokenService:
    settings: dict[str, Any] = {
        "JWT_ACCESS_TTL_SECONDS": 900,
        "JWT_REFRESH_TTL_SECONDS": 7200,
        "JWT_ISSUER": "faclab-test",
        "JWT_REFRESH_REUSE_GRACE_SECONDS": 30,
        "JWT_SELECTION_TTL_SECONDS": 300,
        "JWT_AUDIENCE": "faclab-core",
        "JWT_SERVICE_AUDIENCES": ["faclab-invoicing"],
        "PLATFORM_TOKEN_TTL_SECONDS": ttl,
    }
    with patch("src.auth.infra.token_service.config") as mock_cfg:
        for name, value in settings.items():
            setattr(mock_cfg, name, value)
        return JwtTokenService(JwtKeys(KEY))


def _operator() -> User:
    return User(
        id=7,
        username="ops",
        email="ops@faclab.test",
        password_hash="x",
        full_name="Operadora Uno",
    )


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def test_it_carries_the_operator_and_nothing_of_a_company():
    token = _service().issue_platform_access(_operator())

    claims = _claims(token.access_token)
    assert claims["typ"] == "platform"
    assert (claims["sub"], claims["username"], claims["name"]) == (
        "7",
        "ops",
        "Operadora Uno",
    )
    assert not {"tid", "role", "perms", "sid", "bids", "mcp"} & claims.keys()
    assert token.expires_in == 600
    assert claims["exp"] - claims["iat"] == 600


def test_only_this_service_is_its_audience():
    # faclab-invoicing authorizes with the core's access tokens: it must refuse this one
    claims = _claims(_service().issue_platform_access(_operator()).access_token)

    assert claims["aud"] == "faclab-core"


def test_the_bearer_decoder_gives_the_operator():
    service = _service()
    token = service.issue_platform_access(_operator())

    decoded = service.decode_bearer(token.access_token)

    assert isinstance(decoded, PlatformTokenClaims)
    assert (decoded.sub, decoded.username, decoded.name) == (
        7,
        "ops",
        "Operadora Uno",
    )


@pytest.mark.parametrize(
    "method", ["decode_access", "decode_refresh", "decode_selection"]
)
def test_a_company_s_decoders_never_take_it(method):
    service = _service()
    token = service.issue_platform_access(_operator()).access_token

    with pytest.raises(InvalidTokenError):
        getattr(service, method)(token)


def test_a_platform_token_with_a_tenant_is_refused():
    service = _service()
    now = _claims(service.issue_platform_access(_operator()).access_token)
    forged = sign_token({**now, "tid": "11111111-1111-4111-8111-111111111111"}, KEY)

    with pytest.raises(InvalidTokenError):
        service.decode_bearer(forged)
