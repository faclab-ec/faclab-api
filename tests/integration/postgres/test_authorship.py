"""Authors come from the token, never from the body: a caller that sends
someone else's name still signs as the authenticated user (full name, or
username when the user has none)."""

import pytest

from src.auth.domain.entities import Role
from tests.integration.postgres.api import (
    Api,
    make_location,
    make_movement,
    make_product,
    make_warehouse,
)

IMPOSTOR = "Impostor"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def cashier(client, auth_headers) -> Api:
    return Api(client, auth_headers(Role.CASHIER, full_name="Caja Uno"))


def test_pos_documents_are_signed_by_the_cashier(admin_api, cashier):
    warehouse = make_warehouse(admin_api)
    shelf = make_location(admin_api, warehouse["id"])
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

    assert shift["cashierName"] == "Caja Uno"
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
