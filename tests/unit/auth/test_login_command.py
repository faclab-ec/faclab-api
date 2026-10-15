from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.auth.app.commands.login import LoginCommand, LoginCommandHandler
from src.auth.app.repositories import LoginFailureRepository
from src.auth.app.services.token_service import TokenPair
from src.auth.domain.entities import (
    AuthSession,
    LoginFailure,
    LoginLockoutPolicy,
    Role,
    User,
)
from src.auth.domain.events import UserLoggedIn
from src.auth.domain.exceptions import (
    InvalidCredentialsError,
    LoginFailedError,
    LoginLockedError,
)


class InMemoryLoginFailures(LoginFailureRepository):
    def __init__(self):
        self.failures: list[LoginFailure] = []

    def _of(self, username, ip_address):
        return [
            f
            for f in self.failures
            if (username is not None and f.username == username)
            or (username is None and f.ip_address == ip_address)
        ]

    def add(self, failure):
        self.failures.append(failure)

    def last_failure_at(self, *, username=None, ip_address=None):
        times = [f.attempted_at for f in self._of(username, ip_address)]
        return max(times, default=None)

    def count_since(self, since, *, username=None, ip_address=None):
        return sum(1 for f in self._of(username, ip_address) if f.attempted_at > since)

    def clear_for_username(self, username):
        self.failures = [f for f in self.failures if f.username != username]

    def purge_before(self, before):
        self.failures = [f for f in self.failures if f.attempted_at >= before]

    def age(self, by: timedelta):
        for f in self.failures:
            f.attempted_at -= by


POLICY = LoginLockoutPolicy(
    max_failures_per_user=3,
    max_failures_per_ip=5,
    window=timedelta(minutes=15),
    lockout=timedelta(minutes=15),
)


def _user(**overrides) -> User:
    defaults: dict[str, Any] = {
        "id": 1,
        "username": "alice",
        "email": "alice@example.com",
        "password_hash": "hashed",
        "role": Role.ADMIN,
        "is_active": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _handler(user=None, verify=True, failures=None):
    repo = MagicMock()
    repo.get_by_username.return_value = user
    repo.update.side_effect = lambda u: u
    hasher = MagicMock()
    hasher.verify.return_value = verify
    session_repo = MagicMock()
    session_repo.create.side_effect = lambda session: AuthSession(
        id=42,
        user_id=session.user_id,
        expires_at=session.expires_at,
        refresh_jti=session.refresh_jti,
    )
    token_service = MagicMock()
    token_service.refresh_ttl_seconds = 604800
    token_service.issue_pair.return_value = TokenPair(
        access_token="a", refresh_token="r", expires_in=900
    )
    publisher = MagicMock()
    failures = failures if failures is not None else InMemoryLoginFailures()
    handler = LoginCommandHandler(
        repo, session_repo, failures, POLICY, hasher, token_service, publisher
    )
    return handler, repo, publisher, session_repo, token_service, hasher, failures


def test_login_with_valid_credentials_returns_pair_and_updates_last_login():
    handler, repo, publisher, *_ = _handler(user=_user())
    result = handler.handle(LoginCommand(username="alice", password="pw"))

    assert result.access_token == "a"
    assert result.refresh_token == "r"
    repo.update.assert_called_once()
    updated = repo.update.call_args[0][0]
    assert updated.last_login_at is not None

    publisher.publish.assert_called_once()
    event = publisher.publish.call_args[0][0]
    assert isinstance(event, UserLoggedIn)
    assert event.user_id == 1
    assert event.username == "alice"


def test_login_unknown_user_spends_a_dummy_hash_and_fails():
    handler, *_, hasher, _ = _handler(user=None)
    with pytest.raises(InvalidCredentialsError):
        handler.handle(LoginCommand(username="ghost", password="pw"))
    hasher.verify_dummy.assert_called_once_with("pw")


def test_login_inactive_user_checks_the_password_and_fails():
    handler, *_, hasher, _ = _handler(user=_user(is_active=False))
    with pytest.raises(InvalidCredentialsError):
        handler.handle(LoginCommand(username="alice", password="pw"))
    hasher.verify.assert_called_once_with("pw", "hashed")


def test_login_wrong_password_raises_invalid_credentials():
    handler, *_ = _handler(user=_user(), verify=False)
    with pytest.raises(InvalidCredentialsError):
        handler.handle(LoginCommand(username="alice", password="bad"))


def test_a_failed_login_is_recorded_and_kept_when_the_request_fails():
    handler, *_, failures = _handler(user=_user(), verify=False)

    with pytest.raises(LoginFailedError) as exc:
        handler.handle(
            LoginCommand(username="alice", password="bad", ip_address="1.2.3.4")
        )

    assert exc.value.error_code == "INVALID_CREDENTIALS"
    assert exc.value.commit_transaction
    [failure] = failures.failures
    assert (failure.username, failure.ip_address) == ("alice", "1.2.3.4")


def test_login_opens_a_session_that_lasts_as_long_as_the_refresh_token():
    handler, _, _, session_repo, token_service, *_ = _handler(user=_user())

    handler.handle(LoginCommand(username="alice", password="pw"))

    [session] = session_repo.create.call_args.args
    assert session.user_id == 1
    assert (session.expires_at - datetime.now()).days == 6  # 7 days minus a moment
    assert session.refresh_jti
    user, session_id, refresh_jti = token_service.issue_pair.call_args.args
    assert (user.id, session_id, refresh_jti) == (1, 42, session.refresh_jti)


# Lockout


def _fail_times(handler, times, username="alice", ip="1.2.3.4"):
    for _ in range(times):
        with pytest.raises(LoginFailedError):
            handler.handle(
                LoginCommand(username=username, password="bad", ip_address=ip)
            )


def test_failures_lock_the_username_even_with_the_right_password():
    failures = InMemoryLoginFailures()
    bad, *_ = _handler(user=_user(), verify=False, failures=failures)
    _fail_times(bad, 3)

    good, *_, hasher, _ = _handler(user=_user(), verify=True, failures=failures)
    with pytest.raises(LoginLockedError) as exc:
        good.handle(LoginCommand(username="alice", password="pw"))

    assert exc.value.error_code == "LOGIN_LOCKED"
    hasher.verify.assert_not_called()
    assert len(failures.failures) == 3  # attempts while locked are not recorded


def test_the_lock_ends_after_the_lockout_time():
    failures = InMemoryLoginFailures()
    bad, *_ = _handler(user=_user(), verify=False, failures=failures)
    _fail_times(bad, 3)
    failures.age(POLICY.lockout + timedelta(seconds=1))

    good, *_ = _handler(user=_user(), verify=True, failures=failures)
    good.handle(LoginCommand(username="alice", password="pw"))

    assert failures.failures == []  # a successful login clears the username


def test_failures_below_the_limit_do_not_lock():
    failures = InMemoryLoginFailures()
    bad, *_ = _handler(user=_user(), verify=False, failures=failures)
    _fail_times(bad, 2)

    good, *_ = _handler(user=_user(), verify=True, failures=failures)
    assert good.handle(LoginCommand(username="alice", password="pw")).access_token


def test_failures_outside_the_window_do_not_add_up():
    failures = InMemoryLoginFailures()
    bad, *_ = _handler(user=_user(), verify=False, failures=failures)
    _fail_times(bad, 2)
    failures.age(POLICY.window + timedelta(minutes=1))
    _fail_times(bad, 1)
    # The first two are outside the window that ends at the last failure, so
    # only one counts
    good, *_ = _handler(user=_user(), verify=True, failures=failures)
    assert good.handle(LoginCommand(username="alice", password="pw")).access_token


def test_unknown_usernames_lock_too():
    failures = InMemoryLoginFailures()
    handler, *_ = _handler(user=None, failures=failures)
    _fail_times(handler, 3, username="ghost")

    with pytest.raises(LoginLockedError):
        handler.handle(LoginCommand(username="ghost", password="pw"))


def test_failures_from_one_ip_lock_that_ip_for_every_username():
    failures = InMemoryLoginFailures()
    handler, *_ = _handler(user=None, failures=failures)
    for name in ("a", "b", "c", "d", "e"):
        _fail_times(handler, 1, username=name, ip="9.9.9.9")

    good, *_ = _handler(user=_user(), verify=True, failures=failures)
    with pytest.raises(LoginLockedError):
        good.handle(LoginCommand(username="alice", password="pw", ip_address="9.9.9.9"))
    # Another client can still log in as alice
    assert good.handle(
        LoginCommand(username="alice", password="pw", ip_address="5.5.5.5")
    ).access_token


def test_a_successful_login_keeps_the_ip_failures():
    failures = InMemoryLoginFailures()
    handler, *_ = _handler(user=None, failures=failures)
    _fail_times(handler, 2, username="ghost", ip="9.9.9.9")

    good, *_ = _handler(user=_user(), verify=True, failures=failures)
    good.handle(LoginCommand(username="alice", password="pw", ip_address="9.9.9.9"))

    assert len(failures.failures) == 2
