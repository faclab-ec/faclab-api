"""`make sandbox` against PostgreSQL: a company with made-up data and an
integration client that can call the public API right away (S6.5)."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from scripts import sandbox

RUC = "0999999980001"
ARGS = [
    "--ruc",
    RUC,
    "--legal-name",
    "Tienda Demo (sandbox)",
    "--admin-username",
    "tienda-demo",
    "--admin-email",
    "dev@tienda.example",
]


def _scalar(engine: Engine, sql: str):
    with engine.connect() as conn:
        return conn.execute(text(sql), {"ruc": RUC}).scalar()


def _product_ids(engine: Engine) -> list[int]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT p.id FROM products p JOIN tenants t ON t.id = p.tenant_id"
                    " WHERE t.ruc = :ruc ORDER BY p.id"
                ),
                {"ruc": RUC},
            ).scalars()
        )


def _credentials(path) -> tuple[str, str]:
    values = dict(line.split("=", 1) for line in path.read_text().splitlines())
    return values["FACLAB_CLIENT_ID"], values["FACLAB_CLIENT_SECRET"]


def test_the_sandbox_is_ready_for_the_public_api(
    pg_engine, client: TestClient, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("PROVISION_ADMIN_PASSWORD", "Sandbox-Admin-2026!")
    credentials = tmp_path / "sandbox.env"

    code = sandbox.main(
        [*ARGS, "--client-name", "CI", "--credentials-file", str(credentials)]
    )

    assert code == 0
    client_id, secret = _credentials(credentials)
    assert client_id.startswith("fl_test_")
    # The secret only went to the file
    assert secret not in capsys.readouterr().out
    # The seed's catalog replaced the provisioned structure: three branches
    assert (
        _scalar(
            pg_engine,
            "SELECT count(*) FROM branches b JOIN tenants t ON t.id = b.tenant_id"
            " WHERE t.ruc = :ruc",
        )
        == 3
    )
    assert _product_ids(pg_engine)

    token = client.post(
        "/api/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, secret),
    )
    assert token.status_code == 200, token.text
    assert set(token.json()["scope"].split()) == {
        "products:read",
        "products:write",
        "prices:read",
        "prices:write",
        "stock:read",
        "inventory:write",
        "customers:read",
        "customers:write",
        "sales:read",
        "sales:write",
        "invoices:read",
        "webhooks:manage",
    }
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    branches = client.get("/api/v1/branches", headers=headers)
    assert branches.status_code == 200
    assert len(branches.json()["data"]) == 3
    stock = client.get(
        "/api/v1/stock",
        params={"branchId": branches.json()["data"][0]["id"]},
        headers=headers,
    )
    assert any(float(row["available"]) > 0 for row in stock.json()["data"])


def test_a_second_run_keeps_the_data_unless_reset(pg_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("PROVISION_ADMIN_PASSWORD", "Sandbox-Admin-2026!")
    credentials = tmp_path / "sandbox.env"
    assert (
        sandbox.main(
            [*ARGS, "--client-name", "CI", "--credentials-file", str(credentials)]
        )
        == 0
    )
    first = _product_ids(pg_engine)

    assert sandbox.main(ARGS) == 0
    assert _product_ids(pg_engine) == first

    assert sandbox.main([*ARGS, "--reset"]) == 0
    replaced = _product_ids(pg_engine)
    assert len(replaced) == len(first)
    assert not set(replaced) & set(first)
    # The integration client survives a reset
    assert (
        _scalar(
            pg_engine,
            "SELECT count(*) FROM integration_clients c"
            " JOIN tenants t ON t.id = c.tenant_id WHERE t.ruc = :ruc",
        )
        == 1
    )
