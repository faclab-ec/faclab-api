"""Quotes against PostgreSQL (S5.4): a hardware store quotes cement and nails to
a builder at its wholesale list, prints and emails the quote, and charges it at
the POS as a sale with its same items; one past its validity isn't charged
until it is renewed."""

from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, text

import src
from src.auth.domain.entities import Role
from src.quotes.infra.expiration import expire_quotes
from src.shared.app.mail import Mailer, OutgoingMail
from src.shared.infra.database import worker_session_maker
from tests.integration.postgres.api import (
    Api,
    at_terminal,
    make_branch,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_terminal,
    make_warehouse,
)

NEXT_MONTH = (date.today() + timedelta(days=30)).isoformat()


class RecordingMailer(Mailer):
    def __init__(self):
        self.sent: list[OutgoingMail] = []

    def send(self, mail: OutgoingMail) -> None:
        self.sent.append(mail)


@pytest.fixture
def admin_api(client, admin) -> Api:
    return Api(client, admin)


@pytest.fixture
def shelf(admin_api) -> dict:
    return make_location(admin_api, make_warehouse(admin_api)["id"])


@pytest.fixture
def terminal(admin_api, shelf) -> dict:
    return make_terminal(admin_api, shelf["id"])


@pytest.fixture
def cashier(client, auth_headers, terminal) -> Api:
    api = Api(client, at_terminal(auth_headers(Role.CASHIER), terminal))
    api.post("/api/pos/shifts/open", {"openingBalance": "0"})
    return api


@pytest.fixture
def cement(admin_api, shelf) -> dict:
    product = make_product(admin_api, "FERR-003", name="Cemento", salePrice="9.50")
    make_movement(admin_api, product["id"], 100, shelf["id"])
    return product


@pytest.fixture
def nails(admin_api, shelf) -> dict:
    product = make_product(admin_api, "FERR-010", name="Clavos", salePrice="2.00")
    make_movement(admin_api, product["id"], 100, shelf["id"])
    return product


@pytest.fixture
def builder(admin_api, cement) -> dict:
    """Builders pay 8.90 a bag"""
    price_list = admin_api.post("/api/admin/price-lists", {"name": "Mayorista"})
    admin_api.post(
        f"/api/admin/price-lists/{price_list['id']}/items",
        {"productId": cement["id"], "price": "8.90"},
    )
    customer = make_customer(admin_api, seed=7, name="Constructora Andes")
    return admin_api.put(
        f"/api/admin/customers/{customer['id']}/price-list",
        {"priceListId": price_list["id"]},
    )


@pytest.fixture
def quote(admin_api, terminal, builder, cement, nails) -> dict:
    """10 bags at the builder's 8.90 and 5 boxes of nails at 2.00"""
    created = admin_api.post(
        "/api/admin/quotes",
        {
            "branchId": terminal["branchId"],
            "customerId": builder["id"],
            "validUntil": NEXT_MONTH,
            "notes": "Obra Calderón",
        },
    )
    path = f"/api/admin/quotes/{created['id']}/items"
    admin_api.post(path, {"productId": cement["id"], "quantity": 10})
    return admin_api.post(path, {"productId": nails["id"], "quantity": 5})


def _charge(quote: dict, **overrides) -> dict:
    return {
        "quoteId": quote["id"],
        "customerId": quote["customerId"],
        "items": [
            {"productId": item["productId"], "quantity": item["quantity"]}
            for item in quote["items"]
        ],
        "payments": [{"amount": quote["total"], "paymentMethod": "CASH"}],
        **overrides,
    }


def test_a_quote_is_numbered_in_its_branch_and_priced_by_its_lists(quote):
    assert quote["number"] == "COT-001-000001"
    assert quote["status"] == "DRAFT"
    assert [i["unitPrice"] for i in quote["items"]] == [8.9, 2.0]
    # 10 × 8.90 + 5 × 2.00 = 99.00, plus 15% VAT
    assert (quote["subtotal"], quote["tax"], quote["total"]) == (99.0, 14.85, 113.85)


def test_its_pdf_is_printed(admin_api, client, admin, quote):
    response = client.get(f"/api/admin/quotes/{quote['id']}/pdf", headers=admin)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert "cotizacion-COT-001-000001.pdf" in response.headers["content-disposition"]


def test_it_goes_by_email_with_its_pdf(admin_api, quote):
    mailer = RecordingMailer()
    assert src.wireup_container is not None
    with src.wireup_container.override.injectable(Mailer, mailer):
        sent = admin_api.post(
            f"/api/admin/quotes/{quote['id']}/email", {"to": "compras@andes.ec"}
        )

    [mail] = mailer.sent
    assert mail.to == "compras@andes.ec"
    assert mail.subject.startswith("Cotización COT-001-000001")
    assert mail.attachments[0].content.startswith(b"%PDF-")
    assert sent["status"] == "SENT"


def test_with_email_off_the_quote_is_not_sent(admin_api, quote):
    error = admin_api.error(
        "POST",
        f"/api/admin/quotes/{quote['id']}/email",
        400,
        json={"to": "compras@andes.ec"},
    )

    assert error["code"] == "EMAIL_DISABLED"
    assert admin_api.get(f"/api/admin/quotes/{quote['id']}")["status"] == "DRAFT"


def test_charging_it_makes_a_sale_with_its_items_and_reference(
    admin_api, cashier, quote, shelf, db_session
):
    """Acceptance: the conversion creates a sale with the same items and a
    reference to the quote"""
    admin_api.post(f"/api/admin/quotes/{quote['id']}/accept")
    seen = cashier.get(f"/api/pos/quotes/{quote['id']}")
    assert [i["priceChanged"] for i in seen["items"]] == [False, False]
    assert [i["enoughStock"] for i in seen["items"]] == [True, True]

    sale = cashier.post("/api/pos/sales/quick", _charge(quote))

    assert sale["quoteId"] == quote["id"]
    assert sale["status"] == "CONFIRMED"
    assert sale["total"] == quote["total"]
    assert [(i["productId"], i["quantity"], i["unitPrice"]) for i in sale["items"]] == [
        (i["productId"], i["quantity"], i["unitPrice"]) for i in quote["items"]
    ]
    converted = admin_api.get(f"/api/admin/quotes/{quote['id']}")
    assert converted["status"] == "CONVERTED"
    assert (converted["saleId"], converted["saleNumber"]) == (
        sale["id"],
        sale["number"],
    )
    assert admin_api.get(f"/api/admin/sales/{sale['id']}")["quoteId"] == quote["id"]
    # No longer offered at the POS, and not charged twice
    assert cashier.get("/api/pos/quotes") == []
    error = cashier.error("POST", "/api/pos/sales/quick", 409, json=_charge(quote))
    assert error["code"] == "QUOTE_ALREADY_CONVERTED"


def test_a_changed_price_is_charged_as_quoted_with_its_reason(
    admin_api, cashier, quote, cement
):
    """The cashier honours the quoted 8.90 though the list says 9.20 today"""
    [price_list] = [
        p for p in admin_api.get("/api/admin/price-lists") if p["name"] == "Mayorista"
    ]
    [item] = admin_api.get(f"/api/admin/price-lists/{price_list['id']}/items")
    admin_api.put(
        f"/api/admin/price-lists/{price_list['id']}/items/{item['id']}",
        {"price": "9.20", "minQuantity": 0},
    )
    seen = cashier.get(f"/api/pos/quotes/{quote['id']}")
    assert (seen["items"][0]["listPrice"], seen["items"][0]["priceChanged"]) == (
        9.2,
        True,
    )

    items = [
        {
            "productId": i["productId"],
            "quantity": i["quantity"],
            "unitPrice": i["unitPrice"],
            "overrideReason": f"Cotización {quote['number']}",
        }
        for i in quote["items"]
    ]
    sale = cashier.post("/api/pos/sales/quick", _charge(quote, items=items))

    assert sale["items"][0]["unitPrice"] == 8.9
    assert sale["items"][0]["overrideReason"] == "Cotización COT-001-000001"
    log = admin_api.get(
        "/api/admin/audit-log", params={"action": "sale.price_overridden"}
    )
    assert {entry["resourceId"] for entry in log} == {sale["id"]}


def test_other_items_are_not_the_quote(cashier, quote):
    body = _charge(quote)
    body["items"][0]["quantity"] = 8

    error = cashier.error("POST", "/api/pos/sales/quick", 400, json=body)

    assert error["code"] == "QUOTE_ITEMS_CHANGED"


def test_a_quote_of_another_branch_is_charged_at_its_own(
    admin_api, client, auth_headers, quote
):
    other = make_branch(admin_api, "002", name="Sucursal Norte")
    warehouse = make_warehouse(admin_api, "WH2", branch_id=other["id"])
    location = make_location(admin_api, warehouse["id"], "B1")
    elsewhere = make_terminal(
        admin_api, location["id"], branch_id=other["id"], code="CAJA-02"
    )
    api = Api(client, at_terminal(auth_headers(Role.CASHIER), elsewhere))
    api.post("/api/pos/shifts/open", {"openingBalance": "0"})

    error = api.error("POST", "/api/pos/sales/quick", 400, json=_charge(quote))

    assert error["code"] == "QUOTE_OUTSIDE_BRANCH"
    api.error("GET", f"/api/pos/quotes/{quote['id']}", 404)


def test_an_expired_quote_is_not_charged_until_it_is_renewed(
    admin_api, cashier, quote, pg_engine: Engine
):
    """Acceptance: an expired quote isn't converted without renewing it"""
    past = date.today() - timedelta(days=2)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE quotes SET issue_date = :past, valid_until = :past "
                "WHERE id = :id"
            ),
            {"past": past, "id": quote["id"]},
        )
    # Past its date it is already expired, before the worker marks it
    error = cashier.error("POST", "/api/pos/sales/quick", 400, json=_charge(quote))
    assert error["code"] == "QUOTE_EXPIRED"
    assert cashier.get(f"/api/pos/quotes/{quote['id']}")["expired"] is True

    assert expire_quotes(worker_session_maker(), date.today()) == 1
    assert admin_api.get(f"/api/admin/quotes/{quote['id']}")["status"] == "EXPIRED"
    assert cashier.get("/api/pos/quotes") == []

    renewed = admin_api.post(
        f"/api/admin/quotes/{quote['id']}/renew", {"validUntil": NEXT_MONTH}
    )
    assert (renewed["status"], renewed["issueDate"]) == (
        "DRAFT",
        date.today().isoformat(),
    )
    sale = cashier.post("/api/pos/sales/quick", _charge(renewed))
    assert sale["quoteId"] == quote["id"]


def test_the_worker_marks_only_the_quotes_past_their_date(
    admin_api, quote, pg_engine: Engine
):
    assert expire_quotes(worker_session_maker(), date.today()) == 0
    assert admin_api.get(f"/api/admin/quotes/{quote['id']}")["status"] == "DRAFT"


def test_a_draft_is_edited_and_deleted_and_a_sent_one_is_not(admin_api, quote):
    path = f"/api/admin/quotes/{quote['id']}"
    item = quote["items"][1]
    updated = admin_api.put(f"{path}/items/{item['id']}", {"quantity": 10})
    assert updated["subtotal"] == 109.0

    admin_api.post(f"{path}/send")
    error = admin_api.error("DELETE", path, 400)
    assert error["code"] == "INVALID_QUOTE_STATUS"

    draft = admin_api.post(
        "/api/admin/quotes", {"branchId": quote["branchId"], "validUntil": NEXT_MONTH}
    )
    assert draft["number"] == "COT-001-000002"
    admin_api.delete(f"/api/admin/quotes/{draft['id']}")
    admin_api.error("GET", f"/api/admin/quotes/{draft['id']}", 404)
