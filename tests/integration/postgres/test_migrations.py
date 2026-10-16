"""Alembic migrations against PostgreSQL."""

import subprocess
import sys

from sqlalchemy import inspect

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


def test_the_baseline_goes_down_and_up_again(pg_engine):
    tables = set(inspect(pg_engine).get_table_names())

    down = _alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    assert set(inspect(pg_engine).get_table_names()) == {"alembic_version"}

    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert set(inspect(pg_engine).get_table_names()) == tables
