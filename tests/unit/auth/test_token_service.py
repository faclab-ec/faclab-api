from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import jwt
import pytest

from src.auth.domain.entities import Role, User
from src.auth.domain.exceptions import InvalidTokenError, TokenExpiredError
from src.auth.infra.token_service import JwtTokenService


def _user(**overrides) -> User:
    defaults: dict[str, Any] = {
        "id": 42,
        "username": "alice",
        "email": "alice@example.com",
        "password_hash": "hash",
        "role": Role.ADMIN,
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _service(**config_overrides) -> JwtTokenService:
    defaults: dict[str, Any] = {
        "JWT_SECRET": "test-secret",
        "JWT_ACCESS_TTL_SECONDS": 900,
        "JWT_REFRESH_TTL_SECONDS": 7200,
        "JWT_ISSUER": "faclab-test",
    }
    defaults.update(config_overrides)
    with patch("src.auth.infra.token_service.config") as mock_cfg:
        for k, v in defaults.items():
            setattr(mock_cfg, k, v)
        return JwtTokenService()


def test_issue_pair_and_decode_round_trip():
    svc = _service()
    pair = svc.issue_pair(_user())

    assert pair.token_type == "Bearer"
    assert pair.expires_in == 900
    assert pair.access_token and pair.refresh_token

    access_claims = svc.decode_access(pair.access_token)
    assert access_claims.sub == 42
    assert access_claims.username == "alice"
    assert access_claims.role == int(Role.ADMIN)
    assert access_claims.typ == "access"
    assert access_claims.iss == "faclab-test"

    refresh_claims = svc.decode_refresh(pair.refresh_token)
    assert refresh_claims.typ == "refresh"
    assert refresh_claims.sub == 42


def test_access_decoded_as_refresh_raises_invalid_token():
    svc = _service()
    pair = svc.issue_pair(_user())
    with pytest.raises(InvalidTokenError):
        svc.decode_refresh(pair.access_token)


def test_refresh_decoded_as_access_raises_invalid_token():
    svc = _service()
    pair = svc.issue_pair(_user())
    with pytest.raises(InvalidTokenError):
        svc.decode_access(pair.refresh_token)


def test_token_signed_with_other_secret_raises():
    svc = _service(JWT_SECRET="secret-a")
    pair = svc.issue_pair(_user())

    evil = _service(JWT_SECRET="secret-b")
    with pytest.raises(InvalidTokenError):
        evil.decode_access(pair.access_token)


def test_expired_token_raises_token_expired():
    svc = _service()
    now = datetime.now(UTC) - timedelta(seconds=60)
    payload = {
        "sub": "1",
        "username": "u",
        "role": 1,
        "typ": "access",
        "iat": int((now - timedelta(seconds=10)).timestamp()),
        "exp": int(now.timestamp()),
        "iss": "faclab-test",
    }
    token = jwt.encode(payload, "test-secret", algorithm="HS256")

    with pytest.raises(TokenExpiredError):
        svc.decode_access(token)


def test_garbage_token_raises_invalid_token():
    svc = _service()
    with pytest.raises(InvalidTokenError):
        svc.decode_access("not-a-jwt")


def test_mcp_claim_round_trip():
    svc = _service()
    user = _user(must_change_password=True)
    pair = svc.issue_pair(user)
    claims = svc.decode_access(pair.access_token)
    assert claims.must_change_password is True
    refresh_claims = svc.decode_refresh(pair.refresh_token)
    assert refresh_claims.must_change_password is True


def test_mcp_claim_defaults_false_for_legacy_tokens():
    svc = _service()
    now = datetime.now(UTC)
    payload = {
        "sub": "1",
        "username": "u",
        "role": 1,
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=60)).timestamp()),
        "iss": "faclab-test",
    }
    token = jwt.encode(payload, "test-secret", algorithm="HS256")
    claims = svc.decode_access(token)
    assert claims.must_change_password is False


def test_wrong_issuer_raises_invalid_token():
    svc = _service(JWT_ISSUER="faclab-a")
    pair = svc.issue_pair(_user())

    other = _service(JWT_ISSUER="faclab-b")
    with pytest.raises(InvalidTokenError):
        other.decode_access(pair.access_token)
