from datetime import UTC, datetime

from src.auth.domain.entities import Role, User


def _user(**overrides) -> User:
    return User(username="ana", email="ana@x.ec", password_hash="h0", **overrides)


def test_change_password_clears_the_forced_change():
    user = _user(must_change_password=True)
    user.change_password("h1")
    assert (user.password_hash, user.must_change_password) == ("h1", False)


def test_reset_password_forces_a_change():
    user = _user()
    user.reset_password("tmp")
    assert (user.password_hash, user.must_change_password) == ("tmp", True)


def test_activation_role_and_login():
    user = _user(role=Role.VIEWER)
    at = datetime(2026, 10, 8, tzinfo=UTC)

    user.deactivate()
    assert user.is_active is False
    user.activate()
    user.change_role(Role.MANAGER)
    user.record_login(at)

    assert (user.is_active, user.role, user.last_login_at) == (True, Role.MANAGER, at)
