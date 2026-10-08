"""Alembic migrations against PostgreSQL."""

import subprocess
import sys

import pytest
from sqlalchemy import text

from tests.integration.postgres.api import Api, make_product
from tests.integration.postgres.conftest import ROOT


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_models_match_the_migrations(pg_engine):
    result = _alembic("check")

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def before_stock_uniqueness(pg_engine):
    """Run the test on the schema just before decdb2a1b5d4, then go back to head."""
    downgrade = _alembic("downgrade", "c1a2b3d4e5f6")
    assert downgrade.returncode == 0, downgrade.stderr
    yield
    upgrade = _alembic("upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr


def test_upgrade_merges_location_less_stock_rows(
    client, admin, pg_engine, before_stock_uniqueness
):
    product = make_product(Api(client, admin))
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO stocks (product_id, quantity, reserved_quantity, location_id)"
                " VALUES (:p, 5, 1, NULL), (:p, 3, 0, NULL)"
            ),
            {"p": product["id"]},
        )

    assert _alembic("upgrade", "head").returncode == 0

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT quantity, reserved_quantity FROM stocks WHERE product_id = :p"
            ),
            {"p": product["id"]},
        ).all()
    assert [tuple(row) for row in rows] == [(8, 1)]
