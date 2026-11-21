"""Login metrics (S7.1): `faclab.auth.login.attempts` by result. Brute force
shows as `invalid` and `locked`; never the username nor the address."""

from collections.abc import Generator
from contextlib import contextmanager

from src.auth.domain.exceptions import (
    LoginFailedError,
    LoginLockedError,
    NoActiveTenantError,
)
from src.shared.infra.telemetry_instruments import login_attempts


@contextmanager
def login_attempt() -> Generator[None]:
    """success, invalid (wrong username or password), locked (refused while
    the lockout lasts) or no_tenant (right password, no active tenant). Any
    other error is not an answer to the credentials and is not counted"""
    try:
        yield
    except LoginLockedError:
        login_attempts.add(1, {"result": "locked"})
        raise
    except LoginFailedError:
        login_attempts.add(1, {"result": "invalid"})
        raise
    except NoActiveTenantError:
        login_attempts.add(1, {"result": "no_tenant"})
        raise
    login_attempts.add(1, {"result": "success"})
