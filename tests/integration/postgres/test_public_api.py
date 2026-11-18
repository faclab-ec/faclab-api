"""The public API /api/v1 end to end on PostgreSQL (S6.3): an integration
client goes through its catalog with its token, every response matches the
public OpenAPI with no undocumented field, and a sale of the API is made like
the POS's: stock, number, invoice message and audit."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from config import config
from src.audit.infra.models import AuditLogModel
from src.shared.infra.outbox.models import OutboxMessageModel
from tests.integration.postgres.api import (
    Api,
    make_branch,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_warehouse,
    national_id,
    with_key,
)
from tests.integration.postgres.public_api import assert_documented, integration_headers

V1 = "/api/v1"


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shop(admin_api) -> dict:
    """Branch 001 with an emission point and a location holding 10 hammers"""
    branch = make_branch(admin_api, "001")
    point = admin_api.post(
        "/api/admin/emission-points", {"branchId": branch["id"], "code": "002"}
    )
    warehouse = make_warehouse(admin_api, "BOD-001", branch["id"])
    location = make_location(admin_api, warehouse["id"], "GENERAL")
    product = make_product(admin_api, "MART-16", salePrice="10.00")
    make_movement(admin_api, product["id"], 10, location["id"], unitCost="6.00")
    return {
        "branch": branch["id"],
        "point": point["id"],
        "location": location["id"],
        "product": product["id"],
    }


@pytest.fixture
def headers(admin_api, client) -> dict[str, str]:
    return integration_headers(admin_api, client)


def _get(client, path, headers, **params):
    response = client.get(f"{V1}{path}", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return assert_documented(response)


def _post(client, path, headers, body, status=201, branch=None):
    request_headers = with_key(headers)
    if branch is not None:
        request_headers["X-Branch-Id"] = str(branch)
    response = client.post(f"{V1}{path}", headers=request_headers, json=body)
    assert response.status_code == status, response.text
    return assert_documented(response)


def _error(response, status) -> dict:
    assert response.status_code == status, response.text
    assert_documented(response)
    return response.json()["errors"][0]


def _sale(shop, **overrides) -> dict:
    return {
        "emissionPointId": shop["point"],
        "locationId": shop["location"],
        "externalReference": "WEB-100234",
        "items": [{"productId": shop["product"], "quantity": "2"}],
        # 2 × 10.00 + 15% VAT
        "payments": [{"method": "TRANSFER", "amount": "23.00", "reference": "tx-1"}],
        **overrides,
    }


def test_branches_say_where_a_sale_can_be_made(client, headers, shop):
    [branch] = _get(client, "/branches", headers)

    assert branch["code"] == "001"
    assert [p["id"] for p in branch["emissionPoints"]] == [shop["point"]]
    assert [loc["id"] for loc in branch["locations"]] == [shop["location"]]
    assert branch["locations"][0]["warehouseCode"] == "BOD-001"


def test_products_are_listed_with_strings_and_presentations(client, headers, shop):
    page = client.get(f"{V1}/products", headers=headers, params={"sku": "MART-16"})
    [product] = assert_documented(page)

    assert page.json()["meta"]["pagination"] == {"total": 1, "limit": 50, "offset": 0}
    assert product["salePrice"] == "10.00"
    assert product["unitSymbol"] == "und"
    assert product["presentations"][0]["isBase"] is True
    assert product["presentations"][0]["factor"] == "1"
    assert product["updatedAt"].endswith("Z")
    # The cost is not public
    assert "purchasePrice" not in product


def test_a_product_is_created_once_and_replaced_keeping_its_cost(
    client, headers, admin_api, shop
):
    body = {
        "sku": "PALA-1",
        "name": "Pala",
        "unitOfMeasureId": _get(client, f"/products/{shop['product']}", headers)[
            "unitOfMeasureId"
        ],
        "salePrice": "15.50",
        "barcode": "7861234500011",
    }
    key = with_key(headers)
    first = client.post(f"{V1}/products", headers=key, json=body)
    again = client.post(f"{V1}/products", headers=key, json=body)
    created = assert_documented(first)

    assert first.status_code == again.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["data"]["id"] == created["id"]
    assert created["barcode"] == "7861234500011"

    admin_api.put(
        f"/api/admin/products/{created['id']}",
        {**body, "purchasePrice": "9.00", "minStock": 5},
    )
    replaced = client.put(
        f"{V1}/products/{created['id']}",
        headers=headers,
        json={**body, "name": "Pala cuadrada", "salePrice": "16"},
    )

    assert assert_documented(replaced)["salePrice"] == "16.00"
    internal = admin_api.get(f"/api/admin/products/{created['id']}")
    assert Decimal(str(internal["purchasePrice"])) == Decimal("9.00")
    assert Decimal(str(internal["minStock"])) == Decimal(5)


def test_a_taken_sku_and_a_bad_body(client, headers, shop):
    unit = _get(client, f"/products/{shop['product']}", headers)["unitOfMeasureId"]

    taken = client.post(
        f"{V1}/products",
        headers=with_key(headers),
        json={"sku": "MART-16", "name": "Otro", "unitOfMeasureId": unit},
    )
    as_float = client.post(
        f"{V1}/products",
        headers=with_key(headers),
        json={"sku": "X", "name": "X", "unitOfMeasureId": unit, "salePrice": 1.5},
    )
    unknown_field = client.post(
        f"{V1}/products",
        headers=with_key(headers),
        json={"sku": "X", "name": "X", "unitOfMeasureId": unit, "cost": "1"},
    )

    assert _error(taken, 409)["code"] == "PRODUCT_SKU_ALREADY_EXISTS"
    assert _error(as_float, 422)["code"] == "VALIDATION_ERROR"
    assert _error(unknown_field, 422)["code"] == "VALIDATION_ERROR"


def test_a_sync_walks_by_update_time_in_a_stable_order(client, headers, admin_api):
    for sku in ("A-1", "B-2", "C-3"):
        make_product(admin_api, sku)
    since = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    first = _get(client, "/products", headers, updatedSince=since, limit=2)
    second = _get(client, "/products", headers, updatedSince=since, limit=2, offset=2)
    newest = _get(client, "/products", headers, sort="-sku", limit=1)
    future = _get(
        client,
        "/products",
        headers,
        updatedSince=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )

    assert [p["sku"] for p in first + second] == ["A-1", "B-2", "C-3"]
    assert newest[0]["sku"] == "C-3"
    assert future == []
    invalid = client.get(f"{V1}/products", headers=headers, params={"sort": "cost"})
    assert _error(invalid, 422) == {
        "code": "VALIDATION_ERROR",
        "message": "Can't sort by 'cost'",
        "field": "sort",
        "detail": "Allowed: createdAt, id, name, sku, updatedAt, each optionally "
        "with a leading -",
    }


def test_price_lists_and_their_prices(client, headers, admin_api, shop):
    created = admin_api.post("/api/admin/price-lists", {"name": "Mayorista"})
    base = admin_api.get(f"/api/admin/products/{shop['product']}/presentations")[0]
    admin_api.post(
        f"/api/admin/price-lists/{created['id']}/items",
        {
            "productId": shop["product"],
            "presentationId": base["id"],
            "minQuantity": 10,
            "price": "8.50",
        },
    )

    lists = _get(client, "/price-lists", headers, sort="name")
    [item] = _get(client, f"/price-lists/{created['id']}/items", headers)

    assert "Mayorista" in [pl["name"] for pl in lists]
    assert [pl["name"] for pl in lists] == sorted(pl["name"] for pl in lists)
    assert (item["minQuantity"], item["price"]) == ("10", "8.50")
    missing = client.get(f"{V1}/price-lists/999999/items", headers=headers)
    assert _error(missing, 404)["code"] == "NOT_FOUND"


def test_stock_by_branch(client, headers, admin_api, shop):
    [row] = _get(client, "/stock", headers, branchId=shop["branch"])

    assert (row["productId"], row["sku"]) == (shop["product"], "MART-16")
    assert (row["quantity"], row["available"]) == ("10", "10")
    assert row["locationId"] == shop["location"]
    # A client of every branch says which
    unnamed = client.get(f"{V1}/stock", headers=headers)
    assert _error(unnamed, 400) == {
        "code": "BRANCH_REQUIRED",
        "message": "Send branchId: this client may operate in more than one branch",
        "field": "branchId",
    }


def test_a_client_of_one_branch_sees_only_it(client, admin_api, shop):
    other = make_branch(admin_api, "002")
    limited = integration_headers(admin_api, client, branch_ids=[shop["branch"]])

    [row] = _get(client, "/stock", limited)
    branches = _get(client, "/branches", limited)

    assert row["branchId"] == shop["branch"]
    assert [b["id"] for b in branches] == [shop["branch"]]
    denied = client.get(
        f"{V1}/stock", headers=limited, params={"branchId": other["id"]}
    )
    assert _error(denied, 403)["code"] == "BRANCH_ACCESS_DENIED"


def test_customers_by_identification_keep_their_credit(client, headers, admin_api):
    identification = national_id(41)
    body = {
        "name": "Constructora Andes",
        "identificationType": "NATIONAL_ID",
        "identification": identification,
        "email": "compras@andes.ec",
    }

    created = _post(client, "/customers", headers, body)
    duplicate = client.post(f"{V1}/customers", headers=with_key(headers), json=body)
    found = _get(client, "/customers", headers, identification=identification)

    assert created["identificationType"] == "NATIONAL_ID"
    assert _error(duplicate, 409) == {
        "code": "CUSTOMER_ALREADY_EXISTS",
        "message": "A customer with this identification already exists",
        "existingId": created["id"],
    }
    assert [c["id"] for c in found] == [created["id"]]

    admin_api.put(
        f"/api/admin/customers/{created['id']}",
        {
            "name": "Constructora Andes",
            "taxId": identification,
            "taxType": 2,
            "creditLimit": "500",
            "paymentTerms": 30,
        },
    )
    replaced = client.put(
        f"{V1}/customers/{created['id']}",
        headers=headers,
        json={**body, "name": "Constructora Andes S.A."},
    )

    assert assert_documented(replaced)["name"] == "Constructora Andes S.A."
    internal = admin_api.get(f"/api/admin/customers/{created['id']}")
    assert (Decimal(str(internal["creditLimit"])), internal["paymentTerms"]) == (
        Decimal(500),
        30,
    )
    invalid = client.post(
        f"{V1}/customers",
        headers=with_key(headers),
        json={**body, "identification": "1234567890"},
    )
    assert _error(invalid, 422)["code"] == "VALIDATION_ERROR"


def test_a_sale_of_the_api_is_made_like_the_pos(
    client, headers, admin_api, shop, db_session, monkeypatch
):
    monkeypatch.setattr(config, "KAFKA_ENABLED", True)
    customer = make_customer(admin_api, seed=42)
    key = with_key(headers) | {"X-Branch-Id": str(shop["branch"])}
    body = _sale(shop, customer={"identification": customer["taxId"]})

    response = client.post(f"{V1}/sales", headers=key, json=body)
    again = client.post(f"{V1}/sales", headers=key, json=body)
    sale = assert_documented(response)

    assert response.status_code == 201
    assert again.headers["Idempotent-Replayed"] == "true"
    assert (sale["status"], sale["channel"]) == ("CONFIRMED", "api")
    assert sale["number"] == "V-001-000001"
    assert (sale["total"], sale["paymentStatus"]) == ("23.00", "PAID")
    assert sale["invoiceStatus"] == "PENDING"
    assert sale["customerId"] == customer["id"]
    assert sale["externalReference"] == "WEB-100234"
    assert sale["items"][0]["quantity"] == "2"
    assert sale["payments"] == [
        {"method": "TRANSFER", "amount": "23.00", "reference": "tx-1"}
    ]
    # Once: the stock went down by two
    [row] = _get(client, "/stock", headers, branchId=shop["branch"])
    assert row["available"] == "8"
    # Its invoice goes with its branch and channel
    [message] = db_session.scalars(select(OutboxMessageModel))
    assert message.payload["payload"]["source"] == "api"
    assert message.payload["payload"]["branch_id"] == shop["branch"]
    assert message.payload["payload"]["emission_point_code"] == "002"
    # Listed and read back, with the filters of a sync
    listed = _get(
        client, "/sales", headers, channel="api", externalReference="WEB-100234"
    )
    assert [s["id"] for s in listed] == [sale["id"]]
    assert _get(client, f"/sales/{sale['id']}", headers)["number"] == sale["number"]


def test_a_price_override_is_audited_with_the_client(client, headers, shop, db_session):
    body = _sale(
        shop,
        items=[
            {
                "productId": shop["product"],
                "quantity": "1",
                "unitPrice": "9.00",
                "overrideReason": "Promoción web",
            }
        ],
        payments=[{"method": "CREDIT_CARD", "amount": "10.35"}],
    )

    sale = _post(client, "/sales", headers, body, branch=shop["branch"])

    assert sale["items"][0]["unitPrice"] == "9.00"
    [entry] = db_session.scalars(
        select(AuditLogModel).where(AuditLogModel.action == "sale.price_overridden")
    )
    assert entry.actor_integration_id is not None
    assert entry.actor_name == "Tienda web"
    without_reason = client.post(
        f"{V1}/sales",
        headers=with_key(headers) | {"X-Branch-Id": str(shop["branch"])},
        json=_sale(shop, items=[{**body["items"][0], "overrideReason": None}]),
    )
    assert _error(without_reason, 400)["code"] == "OVERRIDE_REASON_REQUIRED"


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        (
            {"payments": [{"method": "CASH", "amount": "23.00"}]},
            422,
            "VALIDATION_ERROR",
        ),
        (
            {"payments": [{"method": "TRANSFER", "amount": "20.00"}]},
            400,
            "INSUFFICIENT_PAYMENT",
        ),
        (
            {"payments": [{"method": "TRANSFER", "amount": "30.00"}]},
            400,
            "PAYMENT_EXCEEDS_BALANCE",
        ),
        ({"items": [{"productId": 0, "quantity": "1"}]}, 422, "VALIDATION_ERROR"),
        (
            {"items": [{"productId": 999999, "quantity": "1"}]},
            422,
            "REFERENCE_NOT_FOUND",
        ),
        ({"locationId": 999999}, 422, "REFERENCE_NOT_FOUND"),
        ({"customer": {"identification": "0999999999"}}, 422, "REFERENCE_NOT_FOUND"),
        (
            {
                "items": [{"productId": "PRODUCT", "quantity": "11"}],
                "payments": [{"method": "TRANSFER", "amount": "126.50"}],
            },
            400,
            "INSUFFICIENT_STOCK",
        ),
    ],
    ids=[
        "cash",
        "short",
        "over",
        "invalid-id",
        "unknown-product",
        "unknown-location",
        "unknown-customer",
        "no-stock",
    ],
)
def test_a_sale_that_cant_be_made(client, headers, shop, change, status, code):
    body = _sale(shop, **change)
    for item in body["items"]:
        if item["productId"] == "PRODUCT":
            item["productId"] = shop["product"]

    response = client.post(
        f"{V1}/sales",
        headers=with_key(headers) | {"X-Branch-Id": str(shop["branch"])},
        json=body,
    )

    assert _error(response, status)["code"] == code
    [row] = _get(client, "/stock", headers, branchId=shop["branch"])
    assert row["available"] == "10"


def test_a_place_of_another_branch_is_refused(client, headers, admin_api, shop):
    other = make_branch(admin_api, "002")
    warehouse = make_warehouse(admin_api, "BOD-002", other["id"])
    location = make_location(admin_api, warehouse["id"], "NORTE")

    response = client.post(
        f"{V1}/sales",
        headers=with_key(headers) | {"X-Branch-Id": str(shop["branch"])},
        json=_sale(shop, locationId=location["id"]),
    )
    without_branch = client.post(
        f"{V1}/sales", headers=with_key(headers), json=_sale(shop)
    )

    assert _error(response, 400)["code"] == "LOCATION_OUTSIDE_BRANCH"
    assert _error(without_branch, 400)["code"] == "BRANCH_REQUIRED"


def test_a_client_cancels_only_its_own_sales(client, headers, admin_api, shop):
    sale = _post(client, "/sales", headers, _sale(shop), branch=shop["branch"])
    other = integration_headers(admin_api, client, name="ERP")

    refused = client.post(
        f"{V1}/sales/{sale['id']}/cancel", headers=with_key(other), json={}
    )
    cancelled = _post(
        client,
        f"/sales/{sale['id']}/cancel",
        headers,
        {"reason": "Pedido anulado"},
        status=200,
    )

    assert _error(refused, 403)["code"] == "PERMISSION_DENIED"
    assert cancelled["status"] == "CANCELLED"
    [row] = _get(client, "/stock", headers, branchId=shop["branch"])
    assert row["available"] == "10"


def test_scopes_tokens_and_the_switch(client, admin_api, admin, monkeypatch):
    reader = integration_headers(admin_api, client, scopes=["products:read"])
    # An admin's token: every permission, but a person's
    user = admin

    no_scope = client.get(f"{V1}/customers", headers=reader)
    users_token = client.get(f"{V1}/products", headers=user)
    anonymous = client.get(f"{V1}/products")
    unknown_route = client.get(f"{V1}/unknown", headers=reader)

    assert _error(no_scope, 403)["code"] == "INSUFFICIENT_SCOPE"
    assert _error(users_token, 403)["code"] == "PERMISSION_DENIED"
    assert anonymous.status_code == 403
    assert unknown_route.json()["errors"][0]["code"] == "NOT_FOUND"
    monkeypatch.setattr(config, "PUBLIC_API_ENABLED", False)
    disabled = client.get(f"{V1}/products", headers=reader)
    assert _error(disabled, 503)["code"] == "PUBLIC_API_DISABLED"


def test_the_public_contract_is_served(client):
    response = client.get("/openapi/public.json")

    assert response.status_code == 200
    assert "/api/v1/sales" in response.json()["paths"]
    assert "/api/admin/products" not in response.json()["paths"]
