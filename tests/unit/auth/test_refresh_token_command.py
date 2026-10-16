from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.auth.app.commands.logout import LogoutCommand, LogoutCommandHandler
from src.auth.app.commands.refresh_token import (
    RefreshTokenCommand,
    RefreshTokenCommandHandler,
)
from src.auth.app.services.token_service import TokenClaims, TokenPair
from src.auth.domain.entities import AuthSession, Role, User
from src.auth.domain.exceptions import (
    InvalidTokenError,
    TokenExpiredError,
    TokenReusedError,
)
from src.tenancy.app.types import TenantAccess
from src.tenancy.domain.entities import Membership, Tenant

TENANT = Tenant(ruc="1799999990001", legal_name="Empresa")
ACCESS = TenantAccess(
    tenant=TENANT,
    membership=Membership(tenant_id=TENANT.id, user_id=1, role=Role.MANAGER, id=3),
)


def _user(**overrides) -> User:
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "alice",
        "email": "alice@example.com",
        "password_hash": "h",
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _session(**overrides) -> AuthSession:
    defaults: dict[str, Any] = {
        "id": 7,
        "user_id": 1,
        "tenant_id": TENANT.id,
        "expires_at": datetime.now() + timedelta(days=1),
        "refresh_jti": "current",
    }
    defaults.update(overrides)
    return AuthSession(**defaults)


def _claims(sid: int | None = 7, jti: str | None = "current") -> TokenClaims:
    return TokenClaims(
        sub=1,
        username="alice",
        role=1,
        tid=TENANT.id,
        typ="refresh",
        iat=0,
        exp=0,
        iss="faclab",
        sid=sid,
        jti=jti,
    )


def _handler(user=None, session=None, claims=None, access=ACCESS):
    repo = MagicMock()
    repo.get_by_id.return_value = user
    session_repo = MagicMock()
    session_repo.first_for_update.return_value = session
    session_repo.update.side_effect = lambda s: s
    memberships = MagicMock()
    memberships.active_access.return_value = access
    token_service = MagicMock()
    token_service.refresh_ttl_seconds = 604800
    token_service.refresh_reuse_grace_seconds = 30
    token_service.decode_refresh.return_value = claims or _claims()
    token_service.issue_pair.return_value = TokenPair(
        access_token="a2", refresh_token="r2", expires_in=900
    )
    handler = RefreshTokenCommandHandler(repo, session_repo, memberships, token_service)
    return handler, repo, session_repo, token_service


def test_refresh_rotates_the_token_and_extends_the_session():
    session = _session(expires_at=datetime.now() + timedelta(hours=1))
    handler, _, session_repo, token_service = _handler(_user(), session)

    result = handler.handle(RefreshTokenCommand(refresh_token="old"))

    assert result.pair.access_token == "a2"
    assert result.tenant == TENANT
    token_service.decode_refresh.assert_called_once_with("old")
    session_repo.first_for_update.assert_called_once_with(id=7)
    assert session.refresh_jti not in (None, "current")
    assert session.previous_refresh_jti == "current"
    assert session.refreshed_at is not None
    token_service.issue_pair.assert_called_once_with(
        _user(), ACCESS.membership, 7, session.refresh_jti
    )
    session_repo.update.assert_called_once_with(session)
    assert session.expires_at > datetime.now() + timedelta(days=6)


def test_the_token_just_replaced_gets_the_current_one_within_the_grace():
    session = _session(
        refresh_jti="new",
        previous_refresh_jti="current",
        refreshed_at=datetime.now() - timedelta(seconds=5),
    )
    handler, _, _, token_service = _handler(_user(), session)

    handler.handle(RefreshTokenCommand(refresh_token="old"))

    # Not rotated again, so both tabs end up with the same token
    assert (session.refresh_jti, session.previous_refresh_jti) == ("new", "current")
    token_service.issue_pair.assert_called_once_with(
        _user(), ACCESS.membership, 7, "new"
    )
    assert session.revoked_at is None


@pytest.mark.parametrize(
    "session",
    [
        _session(
            refresh_jti="new",
            previous_refresh_jti="current",
            refreshed_at=datetime.now() - timedelta(seconds=31),
        ),
        _session(
            refresh_jti="newest",
            previous_refresh_jti="new",
            refreshed_at=datetime.now(),
        ),
    ],
    ids=["previous-after-grace", "older"],
)
def test_a_reused_refresh_token_revokes_the_session(session):
    handler, _, session_repo, token_service = _handler(_user(), session)

    with pytest.raises(TokenReusedError) as exc:
        handler.handle(RefreshTokenCommand(refresh_token="old"))

    assert exc.value.commit_transaction  # the revocation survives the 401
    assert session.revoked_at is not None
    session_repo.update.assert_called_once_with(session)
    token_service.issue_pair.assert_not_called()


def test_a_session_opened_before_rotation_must_log_in_again():
    handler, *_ = _handler(_user(), _session(refresh_jti=None))

    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="old"))


@pytest.mark.parametrize(
    "session",
    [
        None,
        _session(user_id=2),
        _session(revoked_at=datetime.now()),
        _session(expires_at=datetime.now() - timedelta(seconds=1)),
    ],
    ids=["missing", "other-user", "revoked", "expired"],
)
def test_refresh_needs_an_active_session_of_the_same_user(session):
    handler, _, _, token_service = _handler(_user(), session)

    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="old"))
    token_service.issue_pair.assert_not_called()


@pytest.mark.parametrize(
    "claims", [_claims(sid=None), _claims(jti=None)], ids=["no-sid", "no-jti"]
)
def test_refresh_token_without_session_or_rotation_must_log_in_again(claims):
    handler, *_ = _handler(_user(), _session(), claims=claims)

    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="pre-sessions"))


def test_refresh_inactive_user_raises_invalid_token():
    handler, *_ = _handler(_user(is_active=False), _session())

    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="old"))


def test_the_session_keeps_its_tenant_with_the_current_role():
    handler, _, _, token_service = _handler(_user(), _session())

    handler.handle(RefreshTokenCommand(refresh_token="old"))

    memberships = handler.memberships
    memberships.active_access.assert_called_once_with(1, TENANT.id)
    assert token_service.issue_pair.call_args.args[1].role == Role.MANAGER


def test_a_session_ends_when_its_membership_or_tenant_is_no_longer_active():
    handler, _, _, token_service = _handler(_user(), _session(), access=None)

    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="old"))
    token_service.issue_pair.assert_not_called()


def test_refresh_unknown_user_raises_invalid_token():
    handler, *_ = _handler(None, _session())

    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="old"))


def test_refresh_propagates_invalid_token_from_service():
    handler, repo, _, token_service = _handler()
    token_service.decode_refresh.side_effect = InvalidTokenError("bad typ")

    with pytest.raises(InvalidTokenError):
        handler.handle(RefreshTokenCommand(refresh_token="access-token"))
    repo.get_by_id.assert_not_called()


# Logout


def _logout(session=None, claims=None, error=None):
    session_repo = MagicMock()
    session_repo.get_by_id.return_value = session
    token_service = MagicMock()
    token_service.decode_refresh.return_value = claims or _claims()
    if error:
        token_service.decode_refresh.side_effect = error
    LogoutCommandHandler(session_repo, token_service).handle(
        LogoutCommand(refresh_token="r")
    )
    return session_repo


def test_logout_revokes_the_session():
    session = _session()

    session_repo = _logout(session)

    assert session.revoked_at is not None
    session_repo.update.assert_called_once_with(session)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"error": TokenExpiredError("expired")},
        {"error": InvalidTokenError("bad")},
        {"claims": _claims(sid=None)},
        {"session": None},
        {"session": _session(user_id=2)},
    ],
    ids=["expired", "invalid", "no-sid", "unknown-session", "other-user"],
)
def test_logout_with_nothing_to_close_does_not_fail(kwargs):
    session_repo = _logout(**kwargs)

    session_repo.update.assert_not_called()
