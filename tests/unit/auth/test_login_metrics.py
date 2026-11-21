"""faclab.auth.login.attempts (S7.1): one per answer to the credentials."""

import pytest

from src.auth.domain.exceptions import (
    InvalidTokenError,
    LoginFailedError,
    LoginLockedError,
    NoActiveTenantError,
)
from src.auth.infra.metrics import login_attempt


def _results(recorded_metrics) -> list[str]:
    return sorted(
        attributes["result"]
        for value, attributes in recorded_metrics.collect().points(
            "faclab.auth.login.attempts"
        )
        for _ in range(int(value))
    )


def test_each_answer_is_counted_by_result(recorded_metrics):
    with login_attempt():
        pass
    for error in (LoginFailedError(), LoginFailedError(), LoginLockedError()):
        with pytest.raises(type(error)), login_attempt():
            raise error
    with pytest.raises(NoActiveTenantError), login_attempt():
        raise NoActiveTenantError()

    assert _results(recorded_metrics) == [
        "invalid",
        "invalid",
        "locked",
        "no_tenant",
        "success",
    ]


def test_other_errors_are_not_login_attempts(recorded_metrics):
    with pytest.raises(InvalidTokenError), login_attempt():
        raise InvalidTokenError("bad token")

    assert _results(recorded_metrics) == []
