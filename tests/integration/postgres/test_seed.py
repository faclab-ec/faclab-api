"""`make seed` against PostgreSQL: two tenants with the same catalog."""

from sqlalchemy import Engine, text

from scripts import seed

SEED_USERNAME = "seed-admin"


def _by_tenant(engine: Engine, table: str, column: str) -> list[list[str]]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT array_agg({column} ORDER BY {column}) FROM {table}"
                " GROUP BY tenant_id"
            )
        ).all()
    return [row[0] for row in rows]


def test_the_seed_gives_two_tenants_the_same_catalog(pg_engine, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("AUTH_SEED_USERNAME", SEED_USERNAME)
    monkeypatch.setenv("AUTH_SEED_EMAIL", "seed-admin@test.local")
    monkeypatch.setenv("AUTH_SEED_PASSWORD", "Seed-Admin-2026!")

    seed.main()
    # Idempotent tenants and admin; the business data is replaced
    seed.main()

    for table, column in (
        ("products", "sku"),
        ("customers", "tax_id"),
        ("suppliers", "tax_id"),
        ("warehouses", "code"),
        ("purchase_orders", "order_number"),
    ):
        first, second = _by_tenant(pg_engine, table, column)
        assert first == second, table
        assert first
    with pg_engine.connect() as conn:
        memberships = conn.execute(
            text(
                "SELECT count(*) FROM memberships m JOIN users u ON u.id = m.user_id"
                " WHERE u.username = :username AND m.active"
            ),
            {"username": SEED_USERNAME},
        ).scalar()
    assert memberships == 2
