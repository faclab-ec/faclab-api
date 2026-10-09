"""Thin HTTP helpers and factories for the Postgres integration tests."""

from typing import Any

from fastapi.testclient import TestClient


class Api:
    """Calls the app with auth headers and unwraps the `data` envelope."""

    def __init__(self, client: TestClient, headers: dict[str, str]):
        self.client = client
        self.headers = headers

    def request(self, method: str, path: str, **kwargs) -> Any:
        response = self.client.request(method, path, headers=self.headers, **kwargs)
        assert response.is_success, (
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
        if response.status_code == 204 or not response.content:
            return None
        body = response.json()
        return body.get("data", body) if isinstance(body, dict) else body

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json: dict | None = None, **kwargs) -> Any:
        return self.request("POST", path, json=json, **kwargs)

    def put(self, path: str, json: dict, **kwargs) -> Any:
        return self.request("PUT", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self.request("DELETE", path, **kwargs)

    def error(self, method: str, path: str, expected: int, **kwargs) -> dict:
        """Call an endpoint that must fail and return its first error entry."""
        response = self.client.request(method, path, headers=self.headers, **kwargs)
        assert response.status_code == expected, (
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
        return response.json()["errors"][0]


def national_id(seed: int) -> str:
    """Valid Ecuadorian cédula (province 17) built from a seed."""
    digits = [1, 7, *map(int, f"{seed % 10_000_000:07d}")]
    total = 0
    for i, digit in enumerate(digits):
        product = digit * (2 if i % 2 == 0 else 1)
        total += product - 9 if product > 9 else product
    check = (10 - total % 10) % 10
    return "".join(map(str, digits)) + str(check)


def make_warehouse(api: Api, code: str = "WH1") -> dict:
    return api.post(
        "/api/admin/warehouses", {"name": f"Warehouse {code}", "code": code}
    )


def make_location(api: Api, warehouse_id: int, code: str = "A1") -> dict:
    return api.post(
        "/api/admin/locations",
        {"warehouseId": warehouse_id, "name": f"Location {code}", "code": code},
    )


def make_product(api: Api, sku: str = "SKU-1", **overrides) -> dict:
    payload = {
        "name": f"Product {sku}",
        "sku": sku,
        "purchasePrice": "6.00",
        "salePrice": "10.00",
        "taxCode": "VAT_15",
        **overrides,
    }
    return api.post("/api/admin/products", payload)


def make_movement(
    api: Api, product_id: int, quantity: int, location_id: int | None, **extra
) -> dict:
    payload = {
        "productId": product_id,
        "quantity": quantity,
        "type": "IN" if quantity > 0 else "OUT",
        "locationId": location_id,
        **extra,
    }
    return api.post("/api/admin/movements", payload)


def make_customer(api: Api, seed: int = 1, name: str = "Customer") -> dict:
    return api.post(
        "/api/admin/customers",
        {"name": name, "taxId": national_id(seed), "taxType": 2},
    )


def make_supplier(api: Api, seed: int = 2, name: str = "Supplier") -> dict:
    return api.post(
        "/api/admin/suppliers",
        {"name": name, "taxId": national_id(seed) + "001", "taxType": 1},
    )
