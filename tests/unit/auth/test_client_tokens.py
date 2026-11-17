"""Access tokens of the integration clients (S6.2): what they carry, and that a
user's token and an integration's are never taken for each other."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.auth.app.services.token_service import ClientTokenClaims, TokenClaims
from src.auth.domain.entities import Role, User
from src.auth.domain.exceptions import InvalidTokenError, TokenExpiredError
from src.auth.domain.scopes import Scope
from src.auth.infra.signing_keys import JwtKeys
from src.auth.infra.token_service import JwtTokenService
from src.tenancy.domain.entities import Membership
from tests.tokens import sign_token

TENANT = UUID("11111111-1111-4111-8111-111111111111")
KEY = Ed25519PrivateKey.generate()


def _service() -> JwtTokenService:
    settings: dict[str, Any] = {
        "JWT_ACCESS_TTL_SECONDS": 900,
        "JWT_REFRESH_TTL_SECONDS": 7200,
        "JWT_ISSUER": "faclab-test",
        "JWT_REFRESH_REUSE_GRACE_SECONDS": 30,
        "JWT_SELECTION_TTL_SECONDS": 300,
        "JWT_AUDIENCE": "faclab-core",
        "JWT_SERVICE_AUDIENCES": ["faclab-invoicing"],
    }
    with patch("src.auth.infra.token_service.config") as mock_cfg:
        for name, value in settings.items():
            setattr(mock_cfg, name, value)
        return JwtTokenService(JwtKeys(KEY))


def _client_token(svc: JwtTokenService, **overrides) -> str:
    values: dict[str, Any] = {
        "public_id": "fl_test_0123456789ab",
        "tenant_id": TENANT,
        "secret_id": 7,
        "scopes": {Scope.STOCK_READ, Scope.SALES_WRITE},
        "branch_ids": None,
    }
    values.update(overrides)
    return svc.issue_client_access(**values).access_token


def _claims(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


def test_the_token_carries_tenant_client_scope_and_secret():
    svc = _service()
    issued = svc.issue_client_access(
        public_id="fl_test_0123456789ab",
        tenant_id=TENANT,
        secret_id=7,
        scopes={Scope.STOCK_READ, Scope.SALES_WRITE},
        branch_ids=[15, 12],
    )

    claims = _claims(issued.access_token)

    assert claims["sub"] == "client:fl_test_0123456789ab"
    assert claims["azp"] == "fl_test_0123456789ab"
    assert claims["tid"] == str(TENANT)
    assert claims["scope"] == "sales:write stock:read"
    assert claims["bids"] == [12, 15]
    assert claims["cred"] == 7
    assert claims["typ"] == "access"
    # Only the core until faclab-invoicing's public API checks scopes (S6.3)
    assert claims["aud"] == "faclab-core"
    assert claims["exp"] - claims["iat"] == 900 == issued.expires_in
    # No role nor permissions: what it may do is its scopes
    assert "role" not in claims and "perms" not in claims
    assert jwt.get_unverified_header(issued.access_token)["kid"]


def test_without_branch_limit_there_is_no_bids_claim():
    assert "bids" not in _claims(_client_token(_service()))


def test_decode_bearer_reads_an_integration_token():
    svc = _service()

    claims = svc.decode_bearer(_client_token(svc, branch_ids=[3]))

    assert claims == ClientTokenClaims(
        public_id="fl_test_0123456789ab",
        tid=TENANT,
        secret_id=7,
        scopes=frozenset({Scope.STOCK_READ, Scope.SALES_WRITE}),
        iat=claims.iat,
        exp=claims.exp,
        iss="faclab-test",
        bids=frozenset({3}),
    )


def test_decode_bearer_still_reads_a_user_token():
    svc = _service()
    user = User(id=42, username="alice", email="a@x.ec", password_hash="h")
    pair = svc.issue_pair(
        user, Membership(tenant_id=TENANT, user_id=42, role=Role.ADMIN), 1, "j"
    )

    claims = svc.decode_bearer(pair.access_token)

    assert isinstance(claims, TokenClaims)
    assert claims.sub == 42


@pytest.mark.parametrize(
    "method", ["decode_access", "decode_refresh", "decode_selection"]
)
def test_a_user_method_never_accepts_an_integration_token(method):
    svc = _service()

    with pytest.raises(InvalidTokenError):
        getattr(svc, method)(_client_token(svc))


def test_a_scope_retired_after_issuing_gives_nothing():
    svc = _service()
    token = _claims(_client_token(svc))
    token["scope"] = "stock:read users:manage"

    claims = svc.decode_bearer(sign_token(token, KEY))

    assert isinstance(claims, ClientTokenClaims)
    assert claims.scopes == {Scope.STOCK_READ}


@pytest.mark.parametrize(
    "change",
    [
        {"azp": "fl_test_ffffffffffff"},  # sub and azp name different clients
        {"cred": None},
        {"tid": None},
        {"scope": None},
        {"tid": "not-a-uuid"},
    ],
)
def test_a_malformed_integration_token_is_invalid(change):
    svc = _service()
    token = _claims(_client_token(svc))
    token.update(change)
    token = {k: v for k, v in token.items() if v is not None}

    with pytest.raises(InvalidTokenError):
        svc.decode_bearer(sign_token(token, KEY))


def test_an_expired_integration_token_is_expired():
    svc = _service()
    token = _claims(_client_token(svc))
    past = datetime.now(UTC) - timedelta(hours=1)
    token["iat"] = int(past.timestamp())
    token["exp"] = int((past + timedelta(minutes=15)).timestamp())

    with pytest.raises(TokenExpiredError):
        svc.decode_bearer(sign_token(token, KEY))
