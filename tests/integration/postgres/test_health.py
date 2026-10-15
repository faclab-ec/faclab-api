"""Health endpoints against PostgreSQL."""


def test_ready_checks_the_database(client):
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_live_needs_no_token(client):
    assert client.get("/health/live").status_code == 200
