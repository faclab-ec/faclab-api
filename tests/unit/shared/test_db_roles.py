"""The role URLs of `python -m src.shared.infra.db_roles` (S2.4). The SQL runs
against PostgreSQL in the integration tests, whose fixture bootstraps the roles."""

import pytest

from src.shared.infra.db_roles import (
    APP,
    ATTRIBUTES,
    OWNER,
    WORKER,
    RoleConfigError,
    RoleUrls,
    main,
)

SECRET = "s3cret-value"
ADMIN = f"postgresql://postgres:{SECRET}@db:5432/postgres"


def _url(user: str, database: str = "faclab", host: str = "db") -> str:
    return f"postgresql://{user}:{SECRET}@{host}:5432/{database}"


def _parse(**overrides) -> RoleUrls:
    urls = {
        "admin": ADMIN,
        "owner": _url(OWNER),
        "app": _url(APP),
        "worker": _url(WORKER),
        **overrides,
    }
    return RoleUrls.parse(**urls)


def test_three_roles_of_one_database():
    urls = _parse()

    assert urls.database == "faclab"
    assert {role: url.username for role, url in urls.roles().items()} == {
        OWNER: OWNER,
        APP: APP,
        WORKER: WORKER,
    }


def test_only_the_worker_bypasses_row_level_security():
    assert "NOBYPASSRLS" in ATTRIBUTES[OWNER]
    assert "NOBYPASSRLS" in ATTRIBUTES[APP]
    assert ATTRIBUTES[WORKER].endswith(" BYPASSRLS")
    assert all("NOSUPERUSER" in attributes for attributes in ATTRIBUTES.values())


@pytest.mark.parametrize(
    "overrides",
    [
        {"app": _url("postgres")},
        {"worker": _url(APP)},
        {"owner": f"postgresql://{OWNER}@db:5432/faclab"},
        {"worker": _url(WORKER, database="other")},
        {"app": _url(APP, host="elsewhere")},
        {"admin": f"postgresql://postgres:{SECRET}@elsewhere:5432/postgres"},
        {"owner": f"postgresql://{OWNER}:{SECRET}@db:5432"},
        {"owner": f"postgresql://{OWNER}:{SECRET}@db:5432/"},
        {"app": f"not a url {SECRET}"},
    ],
    ids=[
        "app-as-superuser",
        "worker-as-app",
        "no-password",
        "other-database",
        "other-host",
        "admin-elsewhere",
        "no-database",
        "empty-database",
        "garbage",
    ],
)
def test_inconsistent_urls_are_rejected_without_the_password(overrides):
    with pytest.raises(RoleConfigError) as error:
        _parse(**overrides)

    assert SECRET not in str(error.value)


def test_the_urls_never_show_their_passwords():
    assert SECRET not in repr(_parse())


def test_main_refuses_an_incomplete_environment(monkeypatch):
    for name in (
        "DATABASE_URL_ADMIN",
        "DATABASE_URL",
        "DATABASE_URL_WORKER",
        "DATABASE_URL_MIGRATIONS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("environs.Env.read_env", lambda *args, **kwargs: None)

    assert main() == 1
