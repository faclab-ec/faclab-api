from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.auth.app.commands.select_tenant import (
    SelectTenantCommand,
    SelectTenantCommandHandler,
)
from src.auth.app.services.token_service import TokenClaims, TokenPair
from src.auth.domain.entities import AuthSession, Role, User
from src.auth.domain.exceptions import InvalidTokenError, TenantAccessDeniedError
from src.tenancy.app.types import TenantAccess
from src.tenancy.domain.entities import Membership, Tenant

CURRENT = Tenant(ruc="1799999990001", legal_name="Empresa A")
OTHER = Tenant(ruc="0999999999001", legal_name="Empresa B")
ACCESS = TenantAccess(
    tenant=OTHER,
    membership=Membership(tenant_id=OTHER.id, user_id=1, role=Role.VIEWER, id=4),
)


def _user(**overrides) -> User:
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "alice",
        "email": "alice@example.com",
        "password_hash": "h",
    }
    defaults.update(overrides)
    return User(**defaults)


def _claims(typ="selection", sid=None, sub=1) -> TokenClaims:
    return TokenClaims(
        sub=sub, username="alice", typ=typ, iat=0, exp=0, iss="faclab", sid=sid
    )


def _current(**overrides) -> AuthSession:
    defaults: dict[str, Any] = {
        "id": 7,
        "user_id": 1,
        "tenant_id": CURRENT.id,
        "expires_at": datetime.now() + timedelta(days=1),
        "refresh_jti": "current",
    }
    defaults.update(overrides)
    return AuthSession(**defaults)


def _handler(claims=None, user=None, access=ACCESS, current=None):
    repo = MagicMock()
    repo.get_by_id.return_value = user if user is not None else _user()
    session_repo = MagicMock()
    session_repo.first_for_update.return_value = current
    session_repo.create.side_effect = lambda s: AuthSession(
        id=8,
        user_id=s.user_id,
        tenant_id=s.tenant_id,
        expires_at=s.expires_at,
        refresh_jti=s.refresh_jti,
    )
    memberships = MagicMock()
    memberships.active_access.return_value = access
    memberships.branch_ids.return_value = []
    token_service = MagicMock()
    token_service.refresh_ttl_seconds = 604800
    token_service.decode_selection.return_value = claims or _claims()
    token_service.issue_pair.return_value = TokenPair(
        access_token="a", refresh_token="r", expires_in=900
    )
    handler = SelectTenantCommandHandler(repo, session_repo, memberships, token_service)
    return handler, session_repo, memberships, token_service


def test_the_selection_token_opens_a_session_in_the_chosen_tenant():
    handler, session_repo, memberships, token_service = _handler()

    result = handler.handle(SelectTenantCommand(tenant_id=OTHER.id, token="sel"))

    token_service.decode_selection.assert_called_once_with("sel")
    memberships.active_access.assert_called_once_with(1, OTHER.id)
    [session] = session_repo.create.call_args.args
    assert session.tenant_id == OTHER.id
    user, membership, session_id, _ = token_service.issue_pair.call_args.args
    assert (user.id, membership, session_id) == (1, ACCESS.membership, 8)
    assert result.tenant == OTHER
    assert result.pair.access_token == "a"
    session_repo.first_for_update.assert_not_called()


def test_the_new_session_carries_the_branches_of_that_membership():
    handler, _, memberships, token_service = _handler()
    memberships.branch_ids.return_value = [4, 9]

    handler.handle(SelectTenantCommand(tenant_id=OTHER.id, token="sel"))

    assert token_service.issue_pair.call_args.kwargs == {"branch_ids": [4, 9]}


def test_switching_with_an_access_token_closes_the_current_session():
    current = _current()
    handler, session_repo, _, _ = _handler(
        claims=_claims(typ="access", sid=7), current=current
    )

    result = handler.handle(SelectTenantCommand(tenant_id=OTHER.id, token="access"))

    session_repo.first_for_update.assert_called_once_with(id=7)
    assert current.revoked_at is not None
    session_repo.update.assert_called_once_with(current)
    assert session_repo.create.call_args.args[0].tenant_id == OTHER.id
    assert result.tenant == OTHER


@pytest.mark.parametrize(
    "current",
    [
        None,
        _current(user_id=2),
        _current(revoked_at=datetime.now()),
        _current(expires_at=datetime.now() - timedelta(seconds=1)),
    ],
    ids=["missing", "other-user", "logged-out", "expired"],
)
def test_switching_needs_the_current_session_to_be_active(current):
    handler, session_repo, _, token_service = _handler(
        claims=_claims(typ="access", sid=7), current=current
    )

    with pytest.raises(InvalidTokenError):
        handler.handle(SelectTenantCommand(tenant_id=OTHER.id, token="access"))
    session_repo.create.assert_not_called()
    token_service.issue_pair.assert_not_called()


def test_an_access_token_without_session_cannot_switch():
    handler, session_repo, _, _ = _handler(claims=_claims(typ="access", sid=None))

    with pytest.raises(InvalidTokenError):
        handler.handle(SelectTenantCommand(tenant_id=OTHER.id, token="access"))
    session_repo.create.assert_not_called()


def test_a_tenant_without_an_active_membership_is_denied():
    current = _current()
    handler, session_repo, _, _ = _handler(
        claims=_claims(typ="access", sid=7), current=current, access=None
    )

    with pytest.raises(TenantAccessDeniedError) as exc:
        handler.handle(SelectTenantCommand(tenant_id=OTHER.id, token="access"))

    assert exc.value.error_code == "TENANT_ACCESS_DENIED"
    assert current.revoked_at is None  # the user stays where they were
    session_repo.create.assert_not_called()


def test_a_blocked_account_cannot_select_a_tenant():
    handler, session_repo, _, _ = _handler(user=_user(is_active=False))

    with pytest.raises(InvalidTokenError):
        handler.handle(SelectTenantCommand(tenant_id=OTHER.id, token="sel"))
    session_repo.create.assert_not_called()
