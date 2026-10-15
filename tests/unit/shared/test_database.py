from unittest.mock import MagicMock, patch

import pytest

from src.shared.domain.exceptions import ApplicationError
from src.shared.infra.database import create_session_factory


class KeepsChangesError(ApplicationError):
    commit_transaction = True


def _run(error: Exception):
    session = MagicMock()
    with patch(
        "src.shared.infra.database.create_session_maker", return_value=lambda: session
    ):
        get_db_session = create_session_factory("sqlite://")
    scope = get_db_session()
    next(scope)
    with pytest.raises(type(error)):
        scope.throw(error)
    return session


def test_an_error_rolls_the_request_back():
    session = _run(ApplicationError("boom"))

    session.rollback.assert_called_once()
    session.commit.assert_not_called()


def test_an_error_that_keeps_its_changes_commits_them():
    session = _run(KeepsChangesError("locked"))

    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_called_once()
