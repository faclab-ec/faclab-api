"""Text search on catalog lists and date filters on movements, against
PostgreSQL (ILIKE, wildcard escaping and datetime comparisons)."""

import pytest

from tests.integration.postgres.api import (
    Api,
    make_customer,
    make_location,
    make_movement,
    make_product,
    make_supplier,
    make_warehouse,
)


@pytest.fixture
def api(client, admin) -> Api:
    return Api(client, admin)


def _names(api: Api, path: str, **params) -> list[str]:
    return sorted(row["name"] for row in api.get(path, params=params))


def test_products_match_name_sku_or_exact_barcode(api):
    make_product(api, "LAP-001", name="Portátil 14")
    make_product(api, "MOU-002", name="Mouse óptico", barcode="7861234500017")
    make_product(api, "DSC-50", name="Cupón 50% off")
    make_product(api, "DSC-5X", name="Cupón 5 de descuento")

    assert _names(api, "/api/admin/products", search="portátil") == ["Portátil 14"]
    assert _names(api, "/api/admin/products", search="lap") == ["Portátil 14"]
    assert _names(api, "/api/admin/products", search="7861234500017") == [
        "Mouse óptico"
    ]
    # % is a literal, not a wildcard
    assert _names(api, "/api/admin/products", search="50%") == ["Cupón 50% off"]
    assert len(_names(api, "/api/admin/products")) == 4


def test_products_search_respects_the_category_and_pagination(api):
    category = api.post("/api/admin/categories", {"name": "Cómputo"})
    make_product(api, "LAP-1", name="Laptop A", categoryId=category["id"])
    make_product(api, "LAP-2", name="Laptop B", categoryId=category["id"])
    make_product(api, "LAP-3", name="Laptop C")

    response = api.client.get(
        "/api/admin/products",
        params={"search": "laptop", "categoryId": category["id"], "limit": 1},
        headers=api.headers,
    )

    body = response.json()
    assert len(body["data"]) == 1
    assert body["meta"]["pagination"]["total"] == 2


def test_customers_and_suppliers_match_name_or_tax_id(api):
    ana = make_customer(api, 1, "Ana Pérez")
    make_customer(api, 2, "Luis Mora")
    make_supplier(api, 3, "Distribuidora Andina")
    inactive = make_supplier(api, 4, "Andes Import")
    api.put(
        f"/api/admin/suppliers/{inactive['id']}",
        {**inactive, "isActive": False},
    )

    assert _names(api, "/api/admin/customers", search="pérez") == ["Ana Pérez"]
    assert _names(api, "/api/admin/customers", search=ana["taxId"]) == ["Ana Pérez"]
    assert _names(api, "/api/admin/suppliers", search="and") == [
        "Andes Import",
        "Distribuidora Andina",
    ]
    assert _names(api, "/api/admin/suppliers", search="and", isActive=True) == [
        "Distribuidora Andina"
    ]


def test_movements_filter_by_date_range_inclusive(api):
    product = make_product(api)
    shelf = make_location(api, make_warehouse(api)["id"])
    for date in ("2026-10-01T08:00:00", "2026-10-05T12:00:00", "2026-10-08T18:00:00"):
        make_movement(api, product["id"], 1, shelf["id"], date=date)

    def dates(**params) -> list[str]:
        rows = api.get("/api/admin/movements", params=params)
        return sorted(row["date"][:10] for row in rows)

    assert dates(fromDate="2026-10-05T12:00:00") == ["2026-10-05", "2026-10-08"]
    assert dates(toDate="2026-10-05T12:00:00") == ["2026-10-01", "2026-10-05"]
    assert dates(fromDate="2026-10-02T00:00", toDate="2026-10-07T23:59") == [
        "2026-10-05"
    ]
    assert dates(type="OUT") == []
