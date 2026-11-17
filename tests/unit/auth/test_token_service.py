from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.auth.domain.entities import Role, User
from src.auth.domain.exceptions import (
    InvalidTokenError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import permissions_for
from src.auth.infra.signing_keys import JwtKeys, key_id, public_jwk
from src.auth.infra.token_service import JwtTokenService
from src.tenancy.domain.entities import Membership
from tests.tokens import sign_token

TENANT = UUID("11111111-1111-4111-8111-111111111111")
KEY = Ed25519PrivateKey.generate()


def _user(**overrides) -> User:
    defaults: dict[str, Any] = {
        "id": 42,
        "username": "alice",
        "email": "alice@example.com",
        "password_hash": "hash",
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _membership(role: Role = Role.ADMIN, tenant_id: UUID = TENANT) -> Membership:
    return Membership(tenant_id=tenant_id, user_id=42, role=role, id=3)


def _payload(**overrides) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": "1",
        "username": "u",
        "role": 1,
        "tid": str(TENANT),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=60)).timestamp()),
        "iss": "faclab-test",
        "aud": "faclab-core",
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def _sign(payload: dict[str, Any], key: Ed25519PrivateKey = KEY) -> str:
    return sign_token(payload, key)


def _service(keys: JwtKeys | None = None, **config_overrides) -> JwtTokenService:
    defaults: dict[str, Any] = {
        "JWT_ACCESS_TTL_SECONDS": 900,
        "JWT_REFRESH_TTL_SECONDS": 7200,
        "JWT_ISSUER": "faclab-test",
        "JWT_REFRESH_REUSE_GRACE_SECONDS": 30,
        "JWT_SELECTION_TTL_SECONDS": 300,
        "JWT_AUDIENCE": "faclab-core",
        "JWT_SERVICE_AUDIENCES": ["faclab-invoicing"],
    }
    defaults.update(config_overrides)
    with patch("src.auth.infra.token_service.config") as mock_cfg:
        for k, v in defaults.items():
            setattr(mock_cfg, k, v)
        return JwtTokenService(keys or JwtKeys(KEY))


def test_issue_pair_and_decode_round_trip():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(), 7, "jti-1")

    assert pair.token_type == "Bearer"
    assert pair.expires_in == 900
    assert pair.access_token and pair.refresh_token

    access_claims = svc.decode_access(pair.access_token)
    assert access_claims.sub == 42
    assert access_claims.username == "alice"
    assert access_claims.role == int(Role.ADMIN)
    assert access_claims.tid == TENANT
    assert access_claims.typ == "access"
    assert access_claims.iss == "faclab-test"

    refresh_claims = svc.decode_refresh(pair.refresh_token)
    assert refresh_claims.typ == "refresh"
    assert refresh_claims.sub == 42
    assert refresh_claims.tid == TENANT
    assert access_claims.sid == refresh_claims.sid == 7
    assert refresh_claims.jti == "jti-1"
    assert access_claims.jti is None  # only refresh tokens rotate


def test_role_and_permissions_come_from_the_membership():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(Role.CASHIER), 7, "jti-1")

    claims = svc.decode_access(pair.access_token)

    assert claims.role == int(Role.CASHIER)


def test_access_token_lists_the_role_permissions_for_other_services():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(Role.CASHIER), 7, "jti-1")

    access = jwt.decode(pair.access_token, options={"verify_signature": False})
    refresh = jwt.decode(pair.refresh_token, options={"verify_signature": False})

    assert access["perms"] == sorted(p.value for p in permissions_for(Role.CASHIER))
    assert "perms" not in refresh


def test_access_decoded_as_refresh_raises_invalid_token():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(), 7, "jti-1")
    with pytest.raises(InvalidTokenError):
        svc.decode_refresh(pair.access_token)


def test_refresh_decoded_as_access_raises_invalid_token():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(), 7, "jti-1")
    with pytest.raises(InvalidTokenError):
        svc.decode_access(pair.refresh_token)


def test_a_token_signed_with_a_key_that_is_not_published_is_rejected():
    stranger = Ed25519PrivateKey.generate()
    svc = _service()
    pair = _service(JwtKeys(stranger)).issue_pair(_user(), _membership(), 7, "j")

    # Also when it claims the kid of a published key
    impostor = _sign(_payload(), stranger)
    borrowed_kid = sign_token(_payload(), stranger, kid=key_id(KEY.public_key()))

    for token in (pair.access_token, pair.refresh_token, impostor, borrowed_kid):
        with pytest.raises(InvalidTokenError):
            svc.decode_access(token)
    with pytest.raises(InvalidTokenError):
        svc.decode_refresh(pair.refresh_token)


def test_tokens_are_signed_with_eddsa_and_name_their_key():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(), 7, "j")

    for token in (
        pair.access_token,
        pair.refresh_token,
        svc.issue_selection(_user()).token,
    ):
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "EdDSA"
        assert header["kid"] == key_id(KEY.public_key())


def test_a_token_without_kid_is_rejected():
    token = jwt.encode(_payload(), KEY, algorithm="EdDSA")

    with pytest.raises(InvalidTokenError):
        _service().decode_access(token)


@pytest.mark.parametrize("algorithm", ["HS256", "none"])
def test_a_token_with_another_algorithm_is_rejected(algorithm):
    kid = key_id(KEY.public_key())
    # HS256 keyed with the public key, which anyone can read in the JWKS
    secret = public_jwk(KEY.public_key())["x"] if algorithm == "HS256" else ""
    token = jwt.encode(_payload(), secret, algorithm=algorithm, headers={"kid": kid})

    with pytest.raises(InvalidTokenError):
        _service().decode_access(token)


def test_access_tokens_name_every_service_and_the_others_only_the_core():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(), 7, "j")
    selection = svc.issue_selection(_user()).token

    def audience(token: str):
        return jwt.decode(token, options={"verify_signature": False})["aud"]

    assert audience(pair.access_token) == ["faclab-core", "faclab-invoicing"]
    assert audience(pair.refresh_token) == "faclab-core"
    assert audience(selection) == "faclab-core"


@pytest.mark.parametrize("aud", [None, "faclab-invoicing", ["faclab-invoicing"]])
def test_a_token_that_is_not_for_the_core_is_rejected(aud):
    token = _sign({**_payload(aud=None), **({"aud": aud} if aud else {})})

    with pytest.raises(InvalidTokenError):
        _service().decode_access(token)


def test_a_rotation_keeps_the_sessions_of_the_previous_key():
    previous, current = KEY, Ed25519PrivateKey.generate()
    before = _service(JwtKeys(previous)).issue_pair(_user(), _membership(), 7, "j1")

    # The new key signs; the previous one is still published and accepted
    rotated = _service(JwtKeys(current, [previous.public_key()]))
    after = rotated.issue_pair(_user(), _membership(), 7, "j2")

    assert rotated.decode_access(before.access_token).sid == 7
    assert rotated.decode_refresh(before.refresh_token).jti == "j1"
    assert rotated.decode_refresh(after.refresh_token).jti == "j2"
    header = jwt.get_unverified_header(after.access_token)
    assert header["kid"] == key_id(current.public_key())

    # Once the previous key is retired its tokens stop working
    retired = _service(JwtKeys(current))
    assert retired.decode_access(after.access_token).sid == 7
    with pytest.raises(InvalidTokenError):
        retired.decode_refresh(before.refresh_token)


def test_expired_token_raises_token_expired():
    svc = _service()
    now = datetime.now(UTC) - timedelta(seconds=60)
    payload = _payload(
        iat=int((now - timedelta(seconds=10)).timestamp()),
        exp=int(now.timestamp()),
    )
    token = _sign(payload)

    with pytest.raises(TokenExpiredError):
        svc.decode_access(token)


def test_garbage_token_raises_invalid_token():
    svc = _service()
    with pytest.raises(InvalidTokenError):
        svc.decode_access("not-a-jwt")


def test_mcp_claim_round_trip():
    svc = _service()
    user = _user(must_change_password=True)
    pair = svc.issue_pair(user, _membership(), 7, "jti-1")
    claims = svc.decode_access(pair.access_token)
    assert claims.must_change_password is True
    refresh_claims = svc.decode_refresh(pair.refresh_token)
    assert refresh_claims.must_change_password is True


def test_mcp_claim_defaults_false_when_absent():
    svc = _service()
    token = _sign(_payload())
    claims = svc.decode_access(token)
    assert claims.must_change_password is False


def test_an_access_token_without_tenant_is_rejected():
    svc = _service()
    token = _sign(_payload(tid=None))

    with pytest.raises(TenantRequiredError):
        svc.decode_access(token)


def test_an_access_token_without_role_is_rejected():
    svc = _service()
    token = _sign(_payload(role=None))

    with pytest.raises(InvalidTokenError):
        svc.decode_access(token)


def test_a_malformed_tenant_is_an_invalid_token():
    svc = _service()
    token = _sign(_payload(tid="not-a-uuid"))

    with pytest.raises(InvalidTokenError):
        svc.decode_access(token)


def test_the_selection_token_only_serves_to_select_a_tenant():
    svc = _service()
    selection = svc.issue_selection(_user())

    claims = svc.decode_selection(selection.token)

    assert selection.expires_in == 300
    assert claims.typ == "selection"
    assert claims.sub == 42
    assert claims.tid is None and claims.sid is None and claims.role is None
    with pytest.raises(InvalidTokenError):
        svc.decode_access(selection.token)
    with pytest.raises(InvalidTokenError):
        svc.decode_refresh(selection.token)


def test_an_access_token_also_selects_a_tenant_but_a_refresh_token_does_not():
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(), 7, "jti-1")

    claims = svc.decode_selection(pair.access_token)

    assert claims.typ == "access"
    assert claims.sid == 7
    with pytest.raises(InvalidTokenError):
        svc.decode_selection(pair.refresh_token)


def test_wrong_issuer_raises_invalid_token():
    svc = _service(JWT_ISSUER="faclab-a")
    pair = svc.issue_pair(_user(), _membership(), 7, "jti-1")

    other = _service(JWT_ISSUER="faclab-b")
    with pytest.raises(InvalidTokenError):
        other.decode_access(pair.access_token)


def test_access_token_carries_the_full_name_when_set():
    svc = _service()

    named = svc.issue_pair(_user(full_name="Alice Pérez"), _membership(), 7, "j")
    unnamed = svc.issue_pair(_user(), _membership(), 7, "j")

    assert svc.decode_access(named.access_token).name == "Alice Pérez"
    assert svc.decode_access(unnamed.access_token).name is None


def test_the_access_token_lists_the_branches_the_membership_is_limited_to():
    svc = _service()

    pair = svc.issue_pair(_user(), _membership(), 7, "j", branch_ids=[5, 2, 5])

    claims = jwt.decode(pair.access_token, options={"verify_signature": False})
    assert claims["bids"] == [2, 5]
    assert svc.decode_access(pair.access_token).bids == frozenset({2, 5})
    refresh = jwt.decode(pair.refresh_token, options={"verify_signature": False})
    assert "bids" not in refresh


def test_without_branches_the_token_has_no_bids_claim():
    svc = _service()

    pair = svc.issue_pair(_user(), _membership(), 7, "j")

    claims = jwt.decode(pair.access_token, options={"verify_signature": False})
    assert "bids" not in claims
    assert svc.decode_access(pair.access_token).bids is None


def test_a_malformed_bids_claim_is_an_invalid_token():
    token = _sign(_payload(bids="1,2"))

    with pytest.raises(InvalidTokenError):
        _service().decode_access(token)


@pytest.mark.parametrize(
    "token_of",
    [
        lambda svc, pair: "not-a-jwt",
        lambda svc, pair: pair.refresh_token,  # wrong typ
        lambda svc, pair: (
            _service(JwtKeys(Ed25519PrivateKey.generate()))
            .issue_pair(_user(), _membership(), 7, "j")
            .access_token
        ),
    ],
    ids=["garbage", "wrong-typ", "unpublished-key"],
)
def test_invalid_tokens_get_a_generic_message(token_of):
    svc = _service()
    pair = svc.issue_pair(_user(), _membership(), 7, "j")

    with pytest.raises(InvalidTokenError) as exc:
        svc.decode_access(token_of(svc, pair))

    # PyJWT's own text stays in the server log
    assert exc.value.message == "invalid token"
