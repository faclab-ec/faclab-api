"""Accounts payable against PostgreSQL (S5.7): each receipt owes its total,
due in the supplier's terms, and payments go to the oldest first or as the user
says, never above what is owed, also when two arrive at once."""

from datetime import date, datetime, timedelta

import pytest

from src.auth.domain.entities import Role
from tests.integration.postgres.api import Api, concurrently, make_product, national_id


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def supplier(api) -> dict:
    return api.post(
        "/api/admin/suppliers",
        {
            "name": "Ferretería Mayorista",
            "taxId": national_id(5) + "001",
            "taxType": 1,
            "paymentTerms": 15,
        },
    )


def _receipt(api: Api, supplier: dict, cost: str, invoice: str, sku: str) -> dict:
    """A product at 0 % VAT received in full for `cost`"""
    product = make_product(api, sku, taxCode="VAT_0")
    po = api.post("/api/admin/purchase-orders", {"supplierId": supplier["id"]})
    item = api.post(
        "/api/admin/purchase-order-items",
        {
            "purchaseOrderId": po["id"],
            "productId": product["id"],
            "quantityOrdered": 1,
            "unitCost": cost,
        },
    )
    api.post(f"/api/admin/purchase-orders/{po['id']}/send")
    return api.post(
        f"/api/admin/purchase-orders/{po['id']}/receive",
        {
            "items": [{"purchaseOrderItemId": item["id"], "quantityReceived": 1}],
            "supplierInvoiceNumber": invoice,
        },
    )


def test_a_receipt_is_due_in_the_suppliers_terms(api, supplier):
    _receipt(api, supplier, "30.00", "001-001-000000001", "A")

    [payable] = api.get("/api/admin/payables", params={"supplierId": supplier["id"]})

    assert (payable["amount"], payable["termDays"]) == (30.0, 15)
    assert payable["dueOn"] == (date.today() + timedelta(days=15)).isoformat()
    assert payable["supplierName"] == "Ferretería Mayorista"
    assert payable["daysOverdue"] == 0
    assert api.get("/api/admin/payables", params={"overdue": True}) == []


def test_a_payment_pays_the_oldest_first_and_is_numbered(api, supplier):
    first = _receipt(api, supplier, "30.00", "001-001-000000001", "A")
    _receipt(api, supplier, "20.00", "001-001-000000002", "B")

    payment = api.post(
        "/api/admin/supplier-payments",
        {
            "supplierId": supplier["id"],
            "amount": "35.00",
            "paymentMethod": "TRANSFER",
            "reference": "TRF-881",
        },
    )

    year = datetime.now().year
    assert payment["number"] == f"PP-{year}-0001"
    assert [
        (a["supplierInvoiceNumber"], a["amount"], a["balance"])
        for a in payment["applications"]
    ] == [
        ("001-001-000000001", 30.0, 0.0),
        ("001-001-000000002", 5.0, 15.0),
    ]
    account = api.get(f"/api/admin/supplier-accounts/{supplier['id']}")
    assert account["outstanding"] == 15.0
    assert [p["number"] for p in account["payments"]] == [payment["number"]]
    [paid] = api.get(
        "/api/admin/payables",
        params={"supplierId": supplier["id"], "status": "PAID"},
    )
    assert paid["purchaseReceiptId"] == first["id"]
    assert api.get(f"/api/admin/supplier-payments/{payment['id']}")["paidBy"]


def test_a_payment_by_hand_and_one_over_what_is_owed(api, supplier):
    _receipt(api, supplier, "30.00", "001-001-000000001", "A")
    second = _receipt(api, supplier, "20.00", "001-001-000000002", "B")
    [_, payable] = api.get("/api/admin/payables", params={"supplierId": supplier["id"]})
    assert payable["purchaseReceiptId"] == second["id"]

    api.post(
        "/api/admin/supplier-payments",
        {
            "supplierId": supplier["id"],
            "amount": "20.00",
            "paymentMethod": "CASH",
            "applications": [{"payableId": payable["id"], "amount": "20.00"}],
        },
    )
    error = api.error(
        "POST",
        "/api/admin/supplier-payments",
        400,
        json={"supplierId": supplier["id"], "amount": "30.01", "paymentMethod": "CASH"},
    )

    assert error["code"] == "SUPPLIER_PAYMENT_EXCEEDS_BALANCE"
    assert api.get(f"/api/admin/payables/{payable['id']}")["status"] == "PAID"


def test_concurrent_payments_never_pay_more_than_is_owed(api, admin, supplier):
    _receipt(api, supplier, "30.00", "001-001-000000001", "A")
    body = {"supplierId": supplier["id"], "amount": "30.00", "paymentMethod": "CASH"}

    responses = concurrently(
        *(
            lambda client: client.post(
                "/api/admin/supplier-payments", json=body, headers=admin
            )
            for _ in range(2)
        )
    )

    assert sorted(r.status_code for r in responses) == [201, 400]
    assert api.get(f"/api/admin/supplier-accounts/{supplier['id']}")["outstanding"] == 0


def test_an_operator_sees_what_is_owed_but_doesnt_pay(
    client, auth_headers, api, supplier
):
    _receipt(api, supplier, "30.00", "001-001-000000001", "A")
    operator = Api(client, auth_headers(Role.OPERATOR))

    assert len(operator.get("/api/admin/payables")) == 1
    operator.error(
        "POST",
        "/api/admin/supplier-payments",
        403,
        json={"supplierId": supplier["id"], "amount": "1.00", "paymentMethod": "CASH"},
    )
