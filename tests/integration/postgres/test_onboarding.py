"""The onboarding checklist of core (S8.5): derived from the company's data, so
it moves as the setup is done, wherever it was done."""

import pytest

from tests.integration.postgres.api import (
    Api,
    make_location,
    make_terminal,
    make_warehouse,
)

ONBOARDING = "/api/admin/onboarding"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


def _steps(api: Api) -> dict[str, dict]:
    return {step["key"]: step for step in api.get(ONBOARDING)["steps"]}


def test_a_company_without_setup_is_not_ready(admin_api):
    result = admin_api.get(ONBOARDING)

    assert result["ready"] is False
    steps = _steps(admin_api)
    assert [s["done"] for s in steps.values()] == [False] * 5
    # Only the first three are needed to invoice
    assert {k for k, s in steps.items() if s["required"]} == {
        "branches",
        "emission_points",
        "terminals",
    }


def test_the_steps_are_done_as_the_company_sets_up(admin_api):
    warehouse = make_warehouse(admin_api)
    location = make_location(admin_api, warehouse["id"], "A1")
    make_terminal(admin_api, location["id"])

    steps = _steps(admin_api)

    assert steps["branches"]["done"] and steps["emission_points"]["done"]
    assert steps["terminals"] == {
        "key": "terminals",
        "done": True,
        "count": 1,
        "required": True,
    }
    assert admin_api.get(ONBOARDING)["ready"] is True
    # The admin alone: more users and an import are optional and still missing
    assert not steps["users"]["done"] and not steps["import"]["done"]


def test_a_cashier_cannot_read_it(client, auth_headers):
    from src.auth.domain.entities import Role

    response = client.get(ONBOARDING, headers=auth_headers(Role.CASHIER))

    assert response.status_code == 403
