"""Plans, subscriptions and usage limits on PostgreSQL (S8.4): a branch beyond
the plan answers 409 `PLAN_LIMIT_REACHED` (also two at once), a suspended
company reads but doesn't sell while the invoicing of what it sold goes on,
the documents the SRI authorized count in their month and the company sees
its plan and usage."""

from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from src.auth.domain.entities import Role
from src.invoicing.infra.invoice_messages import handle_invoice_message
from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.tenant import tenant_scope
from src.subscriptions.infra.guard import subscription_access
from src.subscriptions.infra.models import PlanModel, SubscriptionModel
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    concurrently,
    make_branch,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
    with_key,
)
from tests.integration.postgres.public_api import integration_headers

BRANCHES = "/api/admin/branches"
SUBSCRIPTION = "/api/admin/subscription"


@pytest.fixture(autouse=True)
def _fresh_status():
    """The guard keeps a subscription's status for a while: each change of
    these tests applies at once"""
    subscription_access().forget()
    yield
    subscription_access().forget()


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


def _subscribe(
    engine: Engine,
    tenant_id: UUID,
    plan: str = "ilimitado",
    status: str = "active",
    trial_ends_at: datetime | None = None,
    **limits,
) -> None:
    """What the platform does with its CLI: the tenant's subscription to the
    plan, created with `limits` when missing"""
    with Session(bind=engine) as session:
        plan_id = session.scalar(select(PlanModel.id).where(PlanModel.code == plan))
        if plan_id is None:
            model = PlanModel(code=plan, name=plan.title(), **limits)
            session.add(model)
            session.flush()
            plan_id = model.id
        session.execute(
            delete(SubscriptionModel).where(SubscriptionModel.tenant_id == tenant_id)
        )
        session.add(
            SubscriptionModel(
                tenant_id=tenant_id,
                plan_id=plan_id,
                status=status,
                trial_ends_at=trial_ends_at,
            )
        )
        session.commit()
    subscription_access().forget()


# Limits


def test_a_branch_beyond_the_plan_answers_plan_limit_reached(
    admin_api, pg_engine, tenant
):
    _subscribe(pg_engine, tenant, "basico", max_branches=2)
    make_branch(admin_api, "001")
    make_branch(admin_api, "002")

    error = admin_api.error(
        "POST", BRANCHES, 409, json={"establishmentCode": "003", "name": "Cuenca"}
    )

    assert error["code"] == "PLAN_LIMIT_REACHED"
    assert (error["resource"], error["limit"]) == ("branches", 2)
    # An inactive branch takes no seat; activating it again does
    closed = admin_api.post(
        BRANCHES, {"establishmentCode": "003", "name": "Cuenca", "isActive": False}
    )
    error = admin_api.error(
        "PUT",
        f"{BRANCHES}/{closed['id']}",
        409,
        json={"establishmentCode": "003", "name": "Cuenca", "isActive": True},
    )
    assert error["code"] == "PLAN_LIMIT_REACHED"


def test_two_branches_at_once_never_take_the_last_seat(
    admin, admin_api, pg_engine, tenant
):
    _subscribe(pg_engine, tenant, "basico", max_branches=2)
    make_branch(admin_api, "001")

    def create(code: str):
        return lambda client: client.post(
            BRANCHES,
            headers=admin,
            json={"establishmentCode": code, "name": f"Sucursal {code}"},
        )

    responses = concurrently(create("002"), create("003"))

    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(admin_api.get(BRANCHES)) == 2


def test_a_user_beyond_the_plan_is_refused(admin_api, pg_engine, tenant):
    # The admin of the test is the only user
    _subscribe(pg_engine, tenant, "solo", max_users=1)

    error = admin_api.error(
        "POST",
        "/api/admin/users",
        409,
        json={
            "username": "cajera",
            "email": "cajera@example.com",
            "password": "Secret123!",
            "role": Role.CASHIER.value,
        },
    )

    assert (error["code"], error["resource"]) == ("PLAN_LIMIT_REACHED", "users")


def test_a_plan_without_the_public_api_gives_no_scope(admin_api, pg_engine, tenant):
    _subscribe(pg_engine, tenant, "basico", public_api=False)

    error = admin_api.error(
        "POST",
        "/api/admin/integrations",
        409,
        json={"name": "Tienda web", "scopes": ["products:read"]},
    )

    assert error["code"] == "SCOPE_NOT_IN_PLAN"


# Read-only


@pytest.fixture
def shop(client, admin_api, auth_headers) -> dict:
    """A cashier with an open shift and a confirmed sale of a 10.00 product
    (11.50 with VAT), 10 on the shelf"""
    location = make_location(admin_api, make_warehouse(admin_api)["id"])
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 10, location["id"])
    terminal = make_terminal(admin_api, location["id"])
    cashier = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    shift = cashier.post("/api/pos/shifts/open", {"openingBalance": "0"})
    sale = _sell(cashier, product["id"])
    return {"cashier": cashier, "product": product, "shift": shift, "sale": sale}


def _quick_sale(product_id: int) -> dict:
    return {
        "items": [{"productId": product_id, "quantity": 1}],
        "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
    }


def _sell(cashier: Api, product_id: int) -> dict:
    return cashier.post("/api/pos/sales/quick", _quick_sale(product_id))


def _authorize(tenant_id: UUID, sale_id: int) -> None:
    """faclab-invoicing's result, as the consumer handles it"""
    with tenant_scope(TenantContext(tenant_id, TenantSource.MESSAGE)):
        handle_invoice_message(
            {
                "type": "InvoiceAuthorized",
                "invoiceId": f"invoice-{sale_id}",
                "saleId": str(sale_id),
                "status": "authorized",
                "occurredAt": "2026-11-24T15:00:00.000Z",
            }
        )


@pytest.mark.parametrize(
    ("status", "trial_ends_at"),
    [
        ("suspended", None),
        ("cancelled", None),
        ("trial", datetime.now() - timedelta(minutes=1)),
    ],
    ids=["suspended", "cancelled", "trial-ended"],
)
def test_a_read_only_company_reads_but_doesnt_sell(
    shop, admin_api, pg_engine, tenant, status, trial_ends_at
):
    cashier, product = shop["cashier"], shop["product"]
    _subscribe(pg_engine, tenant, status=status, trial_ends_at=trial_ends_at)

    sale = cashier.get(f"/api/pos/sales/{shop['sale']['id']}")
    assert sale["status"] == "CONFIRMED"
    assert cashier.get("/api/pos/shifts/active")["id"] == shop["shift"]["id"]
    assert admin_api.get(f"/api/admin/products/{product['id']}")["id"] == product["id"]
    for method, path, body, api in (
        ("POST", "/api/pos/sales/quick", _quick_sale(product["id"]), cashier),
        ("POST", "/api/pos/sales", {"isFinalConsumer": True}, cashier),
        ("POST", "/api/admin/products", {"name": "Pala", "sku": "PALA"}, admin_api),
        ("PUT", f"/api/admin/branches/{shop['sale']['branchId']}", {}, admin_api),
    ):
        error = api.error(method, path, 403, json=body)
        assert error["code"] == "SUBSCRIPTION_READ_ONLY", (method, path)
    # What it shows of itself
    me = admin_api.get("/api/auth/me")["subscription"]
    assert (me["status"], me["readOnly"]) == (status, True)
    # It still closes the shift that was open, to balance its cash
    closed = cashier.post(
        f"/api/pos/shifts/{shop['shift']['id']}/close",
        {"counts": [{"paymentMethod": "CASH", "counted": "11.50"}]},
    )
    assert closed["status"] == "CLOSED"


def test_the_invoices_of_a_suspended_company_are_still_issued_and_counted(
    shop, admin_api, pg_engine, tenant
):
    sale = shop["sale"]
    _subscribe(pg_engine, tenant, status="suspended")

    _authorize(tenant, sale["id"])
    # Kafka may deliver it again: it counts once
    _authorize(tenant, sale["id"])

    shown = shop["cashier"].get(f"/api/pos/sales/{sale['id']}")
    assert (shown["status"], shown["invoiceStatus"]) == ("INVOICED", "AUTHORIZED")
    current = admin_api.get(SUBSCRIPTION)["documents"]["months"][-1]
    assert (current["invoices"], current["creditNotes"], current["total"]) == (1, 0, 1)


def test_the_public_api_of_a_suspended_company_reads_but_doesnt_sell(
    client, admin_api, pg_engine, tenant, shop
):
    headers = integration_headers(admin_api, client)
    _subscribe(pg_engine, tenant, status="suspended")

    products = client.get("/api/v1/products", headers=headers)
    sale = client.post(
        "/api/v1/sales",
        headers={**with_key(headers), "X-Branch-Id": str(shop["sale"]["branchId"])},
        json={},
    )

    assert products.status_code == 200
    assert sale.status_code == 403
    assert sale.json()["errors"][0]["code"] == "SUBSCRIPTION_READ_ONLY"


def test_an_active_company_sells_again_after_its_suspension(shop, pg_engine, tenant):
    _subscribe(pg_engine, tenant, status="suspended")
    shop["cashier"].error(
        "POST", "/api/pos/sales/quick", 403, json=_quick_sale(shop["product"]["id"])
    )

    _subscribe(pg_engine, tenant, status="active")

    assert _sell(shop["cashier"], shop["product"]["id"])["status"] == "CONFIRMED"


# What the company sees


def test_the_company_sees_its_plan_and_usage(
    client, admin_api, auth_headers, pg_engine, tenant
):
    _subscribe(
        pg_engine,
        tenant,
        "basico",
        max_branches=3,
        max_users=5,
        max_monthly_documents=300,
        public_api=False,
    )
    make_branch(admin_api, "001")
    viewer = Api(client, auth_headers(Role.VIEWER))

    shown = viewer.get(SUBSCRIPTION)

    assert shown["plan"]["code"] == "basico"
    assert shown["plan"]["publicApi"] is False
    assert (shown["status"], shown["readOnly"]) == ("active", False)
    usage = {r["resource"]: (r["used"], r["limit"]) for r in shown["resources"]}
    assert usage["branches"] == (1, 3)
    # The admin and the viewer
    assert usage["users"] == (2, 5)
    assert usage["terminals"] == (0, None)
    assert shown["documents"]["limit"] == 300
    assert len(shown["documents"]["months"]) == 6
    # The cashier sees no plan screen, but its /me says the company's status
    cashier = Api(client, auth_headers(Role.CASHIER))
    cashier.error("GET", SUBSCRIPTION, 403)
    assert cashier.get("/api/auth/me")["subscription"] == {
        "planName": "Basico",
        "status": "active",
        "trialEndsAt": None,
        "readOnly": False,
        "documentsLimitReached": False,
    }
