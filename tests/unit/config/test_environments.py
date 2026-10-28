"""Settings per ENVIRONMENT.

`config` reads the environment when it is imported, so each case imports it in a
fresh interpreter with only the variables under test.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

_SETTINGS = (
    "ENVIRONMENT",
    "DATABASE_URL",
    "DATABASE_URL_WORKER",
    "DATABASE_URL_MIGRATIONS",
    "DATABASE_URL_ADMIN",
    "CORS_ORIGINS",
    "JWT_SECRET",
    "DOCS_ENABLED",
    "KAFKA_ENABLED",
    "RUN_BACKGROUND",
)

_PRINT_CONFIG = """
import json
from config import config
print(json.dumps({
    "database_url": config.DB_CONNECTION_STRING,
    "worker_database_url": config.DB_WORKER_CONNECTION_STRING,
    "cors_origins": config.CORS_ORIGINS,
    "docs_enabled": config.DOCS_ENABLED,
}))
"""

_PRINT_ROUTES = """
import json
import main
print(json.dumps(sorted(getattr(r, "path", "") for r in main.app.routes)))
"""

# The API's lifespan with Kafka on: which messaging threads it starts
_PRINT_BACKGROUND_THREADS = """
import json
import threading
from fastapi.testclient import TestClient
import main
with TestClient(main.app):
    names = sorted(t.name for t in threading.enumerate())
print(json.dumps({"messaging": main.messaging is not None, "threads": names}))
"""

DEPLOYED = {
    "DATABASE_URL": "postgresql://faclab@db:5432/faclab",
    "DATABASE_URL_WORKER": "postgresql://faclab_worker@db:5432/faclab",
    "CORS_ORIGINS": "https://app.faclab.ec,https://admin.faclab.ec",
    "JWT_SECRET": "x" * 40,
}


def _run(code: str, **settings: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in _SETTINGS}
    env.update({"OTEL_ENABLED": "false", "KAFKA_ENABLED": "false", **settings})
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _last_json_line(result: subprocess.CompletedProcess):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_refuses_to_start_without_required_settings(
    environment,
):
    result = _run(_PRINT_CONFIG, ENVIRONMENT=environment)

    assert result.returncode != 0
    assert (
        f"Missing required settings for {environment}: "
        "DATABASE_URL, DATABASE_URL_WORKER, CORS_ORIGINS, JWT_SECRET"
    ) in result.stderr


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environment_reads_its_settings_with_docs_off(environment):
    settings = _last_json_line(_run(_PRINT_CONFIG, ENVIRONMENT=environment, **DEPLOYED))

    assert settings == {
        "database_url": DEPLOYED["DATABASE_URL"],
        "worker_database_url": DEPLOYED["DATABASE_URL_WORKER"],
        "cors_origins": ["https://app.faclab.ec", "https://admin.faclab.ec"],
        "docs_enabled": False,
    }


def test_production_requires_the_worker_url_even_without_kafka():
    """The worker's purges cross tenants: as faclab_app they would see nothing"""
    deployed = {k: v for k, v in DEPLOYED.items() if k != "DATABASE_URL_WORKER"}

    result = _run(_PRINT_CONFIG, ENVIRONMENT="production", **deployed)

    assert result.returncode != 0
    assert "Missing required settings for production: DATABASE_URL_WORKER" in (
        result.stderr
    )


def test_docs_can_be_enabled_in_production():
    settings = _last_json_line(
        _run(_PRINT_CONFIG, ENVIRONMENT="production", DOCS_ENABLED="true", **DEPLOYED)
    )

    assert settings["docs_enabled"] is True


def test_production_rejects_a_wildcard_cors_origin():
    result = _run(
        _PRINT_CONFIG,
        ENVIRONMENT="production",
        **{**DEPLOYED, "CORS_ORIGINS": "*"},
    )

    assert result.returncode != 0
    assert "CORS_ORIGINS must list explicit origins" in result.stderr


def test_production_rejects_a_short_jwt_secret():
    result = _run(
        _PRINT_CONFIG,
        ENVIRONMENT="production",
        **{**DEPLOYED, "JWT_SECRET": "short"},
    )

    assert result.returncode != 0
    assert "JWT_SECRET must be unique" in result.stderr


def test_local_keeps_development_defaults():
    settings = _last_json_line(_run(_PRINT_CONFIG, ENVIRONMENT="local"))

    assert settings == {
        "database_url": "sqlite:///./warehouse.db",
        "worker_database_url": "sqlite:///./warehouse.db",
        "cors_origins": ["http://localhost:3000", "http://localhost:5173"],
        "docs_enabled": True,
    }


def test_production_app_has_health_but_no_docs(tmp_path):
    routes = _last_json_line(
        _run(
            _PRINT_ROUTES,
            ENVIRONMENT="production",
            **{**DEPLOYED, "DATABASE_URL": f"sqlite:///{tmp_path}/app.db"},
        )
    )

    assert {"/health/live", "/health/ready"} <= set(routes)
    assert not {"/", "/docs", "/openapi.json", "/openapi/admin.json"} & set(routes)


def test_without_run_background_the_api_starts_no_messaging_threads():
    result = _last_json_line(
        _run(_PRINT_BACKGROUND_THREADS, KAFKA_ENABLED="true", RUN_BACKGROUND="false")
    )

    assert result["messaging"] is False
    assert not {"outbox-relay", "kafka-consumer", "kafka-producer"} & set(
        result["threads"]
    )


def test_run_background_keeps_the_messaging_in_the_api():
    """The rollback switch: the API builds its producer, relay and consumer"""
    result = _last_json_line(
        _run(
            "import json, main; print(json.dumps(main.messaging is not None))",
            KAFKA_ENABLED="true",
            RUN_BACKGROUND="true",
        )
    )

    assert result is True
