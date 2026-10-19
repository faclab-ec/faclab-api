"""Authors come from the token, never from the body: a caller that sends
someone else's name still signs as the authenticated user (full name, or
username when the user has none)."""

import pytest

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)

IMPOSTOR = "Impostor"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shelf(admin_api) -> dict:
    return make_location(admin_api, make_warehouse(admin_api)["id"])


@pytest.fixture
def cashier(client, auth_headers, admin_api, shelf) -> Api:
    headers = auth_headers(Role.CASHIER, full_name="Caja Uno")
    return Api(client, at_terminal(headers, make_terminal(admin_api, shelf["id"])))


def test_pos_documents_are_signed_by_the_cashier(admin_api, cashier, shelf):
    product = make_product(admin_api, salePrice="10.00", taxCode="VAT_15")
    make_movement(admin_api, product["id"], 10, shelf["id"])

    shift = cashier.post(
        "/api/pos/shifts/open", {"cashierName": IMPOSTOR, "openingBalance": "50.00"}
    )
    sale = cashier.post(
        "/api/pos/sales/quick",
        {
            "items": [{"productId": product["id"], "quantity": 1}],
            "payments": [{"amount": "11.50", "paymentMethod": "CASH"}],
            "createdBy": IMPOSTOR,
        },
    )
    movement = cashier.post(
        f"/api/pos/shifts/{shift['id']}/cash-movements",
        {"type": "OUT", "amount": "5.00", "performedBy": IMPOSTOR},
    )
    [item] = cashier.get(f"/api/pos/sales/{sale['id']}/items")
    refund = cashier.post(
        "/api/pos/refunds",
        {
            "originalSaleId": sale["id"],
            "items": [{"saleItemId": item["id"], "quantity": 1}],
            "refundedBy": IMPOSTOR,
        },
    )
    receipt = cashier.get(f"/api/pos/sales/{sale['id']}/receipt")
    closed = cashier.post(
        f"/api/pos/shifts/{shift['id']}/close",
        {"closingBalance": "56.50", "closedBy": IMPOSTOR},
    )

    assert shift["cashierName"] == "Caja Uno"
    assert closed["closedBy"] == "Caja Uno"
    assert sale["createdBy"] == "Caja Uno"
    assert movement["performedBy"] == "Caja Uno"
    assert refund["refundedBy"] == "Caja Uno"
    assert receipt["cashier"] == "Caja Uno"


def test_inventory_documents_are_signed_by_the_user(admin_api):
    warehouse = make_warehouse(admin_api)
    shelf = make_location(admin_api, warehouse["id"], "A1")
    backroom = make_location(admin_api, warehouse["id"], "B1")

    adjustment = admin_api.post(
        "/api/admin/adjustments",
        {
            "warehouseId": warehouse["id"],
            "reason": "physical_count",
            "adjustedBy": IMPOSTOR,
        },
    )
    adjustment = admin_api.put(
        f"/api/admin/adjustments/{adjustment['id']}",
        {"notes": "recount", "adjustedBy": IMPOSTOR},
    )
    transfer = admin_api.post(
        "/api/admin/transfers",
        {
            "sourceLocationId": backroom["id"],
            "destinationLocationId": shelf["id"],
            "requestedBy": IMPOSTOR,
        },
    )
    transfer = admin_api.put(
        f"/api/admin/transfers/{transfer['id']}",
        {"notes": "restock", "requestedBy": IMPOSTOR},
    )

    # The admin has no full name, so the username signs
    assert (adjustment["adjustedBy"], adjustment["notes"]) == ("admin-test", "recount")
    assert (transfer["requestedBy"], transfer["notes"]) == ("admin-test", "restock")
