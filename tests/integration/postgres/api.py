"""Thin HTTP helpers and factories for the Postgres integration tests."""

import threading
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from httpx import Response

from main import app

IDEMPOTENCY_KEY = "Idempotency-Key"


def with_key(headers: dict[str, str]) -> dict[str, str]:
    """`headers` plus a new Idempotency-Key: one operation (S3.1)"""
    return {**headers, IDEMPOTENCY_KEY: str(uuid4())}


class Api:
    """Calls the app with auth headers and unwraps the `data` envelope."""

    def __init__(self, client: TestClient, headers: dict[str, str]):
        self.client = client
        self.headers = headers

    def request(self, method: str, path: str, **kwargs) -> Any:
        response = self.client.request(
            method, path, headers=self._headers(method, kwargs), **kwargs
        )
        assert response.is_success, (
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
        if response.status_code == 204 or not response.content:
            return None
        body = response.json()
        return body.get("data", body) if isinstance(body, dict) else body

    def _headers(self, method: str, kwargs: dict[str, Any]) -> dict[str, str]:
        """The caller's headers plus the call's own. Each POST is one operation
        with its own Idempotency-Key, as the web sends them, unless the call
        brings one"""
        headers = {**self.headers, **kwargs.pop("headers", {})}
        if method == "POST" and IDEMPOTENCY_KEY not in headers:
            headers[IDEMPOTENCY_KEY] = str(uuid4())
        return headers

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
        response = self.client.request(
            method, path, headers=self._headers(method, kwargs), **kwargs
        )
        assert response.status_code == expected, (
            f"{method} {path} -> {response.status_code}: {response.text}"
        )
        return response.json()["errors"][0]


def concurrently(*calls: Callable[[TestClient], Response]) -> list[Response]:
    """Starts the calls at once, each with its own client"""
    barrier = threading.Barrier(len(calls))
    responses: list[Response] = []

    def run(call: Callable[[TestClient], Response]) -> None:
        client = TestClient(app)
        barrier.wait()
        responses.append(call(client))

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return responses


def national_id(seed: int) -> str:
    """Valid Ecuadorian cédula (province 17) built from a seed."""
    digits = [1, 7, *map(int, f"{seed % 10_000_000:07d}")]
    total = 0
    for i, digit in enumerate(digits):
        product = digit * (2 if i % 2 == 0 else 1)
        total += product - 9 if product > 9 else product
    check = (10 - total % 10) % 10
    return "".join(map(str, digits)) + str(check)


def make_branch(api: Api, code: str = "001", name: str | None = None) -> dict:
    return api.post(
        "/api/admin/branches",
        {"establishmentCode": code, "name": name or f"Branch {code}"},
    )


def main_branch_id(api: Api) -> int:
    """The caller's tenant's branch 001, created the first time it is needed"""
    for branch in api.get("/api/admin/branches", params={"limit": 1000}):
        if branch["establishmentCode"] == "001":
            return branch["id"]
    return make_branch(api, "001")["id"]


def make_warehouse(api: Api, code: str = "WH1", branch_id: int | None = None) -> dict:
    return api.post(
        "/api/admin/warehouses",
        {
            "branchId": branch_id or main_branch_id(api),
            "name": f"Warehouse {code}",
            "code": code,
        },
    )


def make_location(api: Api, warehouse_id: int, code: str = "A1") -> dict:
    return api.post(
        "/api/admin/locations",
        {"warehouseId": warehouse_id, "name": f"Location {code}", "code": code},
    )


def make_terminal(
    api: Api, location_id: int, branch_id: int | None = None, code: str = "CAJA-01"
) -> dict:
    """A POS terminal of the branch (001 by default) that sells from the
    location, with the branch's first emission point (created if missing)"""
    branch_id = branch_id or main_branch_id(api)
    points = api.get("/api/admin/emission-points", params={"branchId": branch_id})
    point = (
        points[0]
        if points
        else api.post(
            "/api/admin/emission-points", {"branchId": branch_id, "code": "001"}
        )
    )
    return api.post(
        "/api/admin/pos-terminals",
        {
            "branchId": branch_id,
            "emissionPointId": point["id"],
            "defaultLocationId": location_id,
            "code": code,
            "name": f"Caja {code}",
        },
    )


def at_terminal(headers: dict[str, str], terminal: dict) -> dict[str, str]:
    """`headers` plus the POS headers of the terminal: its branch and its id"""
    return {
        **headers,
        "X-Branch-Id": str(terminal["branchId"]),
        "X-Terminal-Id": str(terminal["id"]),
    }


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
