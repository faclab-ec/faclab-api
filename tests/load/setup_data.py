"""Datos de las pruebas de carga (S9.2): llena, por la API, una empresa recién aprovisionada con la
escala de la ferretería piloto y deja en un archivo lo que los escenarios de k6 necesitan.

Solo contra un entorno de pruebas: se niega con un host que no sea local ni `*.test`.

    LOAD_BASE_URL=https://api.faclab.test LOAD_CA_FILE=caddy-root.crt \\
    LOAD_RUC=1799999990001 LOAD_ADMIN_USERNAME=... LOAD_ADMIN_PASSWORD=... \\
        python tests/load/setup_data.py --fixtures /ruta/fuera/del/repo/fixtures.json

Se puede repetir: lo que ya existe se reutiliza. El archivo lleva contraseñas y el secreto de un
cliente de integración, así que se escribe con permisos 0600 y nunca dentro del repositorio.
"""

import argparse
import csv
import io
import json
import os
import random
import secrets
import subprocess
import tempfile
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

BRANCHES = ("001", "002")
TERMINALS_PER_BRANCH = 3
SCOPES = [
    "products:read",
    "prices:read",
    "stock:read",
    "customers:read",
    "customers:write",
    "sales:read",
    "sales:write",
    "invoices:read",
]
PRICE_LIST = "Contratistas"
FAMILIES = (
    "Tornillo",
    "Clavo",
    "Tubo PVC",
    "Codo",
    "Cable",
    "Broca",
    "Llave",
    "Foco",
    "Pintura",
    "Lija",
    "Bisagra",
    "Candado",
    "Taco",
    "Perno",
    "Manguera",
    "Brocha",
    "Cinta",
    "Tuerca",
    "Interruptor",
    "Sellante",
)
SIZES = ("1/4", "3/8", "1/2", "3/4", "1", "1 1/4", "1 1/2", "2", "3", "4")


def ensure_test_host(url: str) -> str:
    """The load tests write thousands of documents: never against a real deployment."""
    host = urlsplit(url).hostname or ""
    if host in ("localhost", "127.0.0.1") or host.endswith(".test"):
        return url.rstrip("/")
    raise SystemExit(
        f"setup_data: {host!r} no es un entorno de pruebas (local o *.test)"
    )


def cedula(index: int) -> str:
    """A made-up Ecuadorian cédula with a valid check digit."""
    digits = f"17{index % 6}{index:06d}"[:9]
    total = 0
    for position, char in enumerate(digits):
        value = int(char) * (2 if position % 2 == 0 else 1)
        total += value - 9 if value > 9 else value
    return f"{digits}{(10 - total % 10) % 10}"


def csv_file(header: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


class Api:
    def __init__(self, base_url: str, verify: str | bool, username: str, password: str):
        self.http = httpx.Client(base_url=base_url, verify=verify, timeout=120)
        self.username = username
        self.password = password
        self.token = ""
        self.logged_at = 0.0

    def login(self) -> None:
        response = self.http.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        response.raise_for_status()
        self.token = response.json()["data"]["accessToken"]
        self.logged_at = time.monotonic()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.token or time.monotonic() - self.logged_at > 600:
            self.login()
        headers = {"Authorization": f"Bearer {self.token}", **kwargs.pop("headers", {})}
        response = self.http.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 400:
            raise SystemExit(
                f"{method} {path} respondió {response.status_code}: {response.text[:600]}"
            )
        return response.json() if response.content else None

    def data(self, method: str, path: str, **kwargs: Any) -> Any:
        return self.request(method, path, **kwargs)["data"]

    def every(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while True:
            page = self.data("GET", path, params={"limit": 1000, "offset": len(items)})
            items.extend(page)
            if len(page) < 1000:
                return items

    def ensure(
        self, path: str, key: str, value: object, body: dict[str, Any]
    ) -> dict[str, Any]:
        found = next((item for item in self.every(path) if item[key] == value), None)
        return found or self.data("POST", path, json=body)

    def run_import(self, kind: str, content: bytes) -> None:
        job = self.data(
            "POST",
            "/api/admin/imports",
            data={"kind": kind, "mode": "SKIP"},
            files={"file": (f"{kind.lower()}.csv", content, "text/csv")},
        )
        if job["status"] != "VALIDATED":
            errors = self.data(
                "GET",
                f"/api/admin/imports/{job['id']}/rows",
                params={"action": "ERROR", "limit": 5},
            )
            raise SystemExit(
                f"importación {kind} {job['status']}: {json.dumps(errors)[:800]}"
            )
        started = time.monotonic()
        self.data("POST", f"/api/admin/imports/{job['id']}/confirm")
        while True:
            job = self.data("GET", f"/api/admin/imports/{job['id']}")
            if job["status"] not in ("QUEUED", "RUNNING"):
                break
            time.sleep(3)
        if job["status"] != "COMPLETED":
            raise SystemExit(f"importación {kind} terminó {job['status']}")
        print(
            f"importación {kind}: {job['totalRows']} filas en {time.monotonic() - started:.0f} s"
        )


def set_up_structure(api: Api) -> list[dict[str, Any]]:
    branches = []
    for code in BRANCHES:
        branch = api.ensure(
            "/api/admin/branches",
            "establishmentCode",
            code,
            {"establishmentCode": code, "name": f"Local {code}", "address": "Quito"},
        )
        emission = next(
            (
                e
                for e in api.every("/api/admin/emission-points")
                if e["branchId"] == branch["id"] and e["code"] == "001"
            ),
            None,
        ) or api.data(
            "POST",
            "/api/admin/emission-points",
            json={"branchId": branch["id"], "code": "001"},
        )
        warehouse = api.ensure(
            "/api/admin/warehouses",
            "code",
            f"BOD-{code}",
            {"code": f"BOD-{code}", "name": f"Bodega {code}", "branchId": branch["id"]},
        )
        location = next(
            (
                item
                for item in api.every("/api/admin/locations")
                if item["warehouseId"] == warehouse["id"] and item["code"] == "GENERAL"
            ),
            None,
        ) or api.data(
            "POST",
            "/api/admin/locations",
            json={"warehouseId": warehouse["id"], "name": "General", "code": "GENERAL"},
        )
        terminals = []
        for number in range(1, TERMINALS_PER_BRANCH + 1):
            existing = next(
                (
                    t
                    for t in api.every("/api/admin/pos-terminals")
                    if t["branchId"] == branch["id"] and t["code"] == f"CAJA-0{number}"
                ),
                None,
            )
            terminal = existing or api.data(
                "POST",
                "/api/admin/pos-terminals",
                json={
                    "branchId": branch["id"],
                    "emissionPointId": emission["id"],
                    "defaultLocationId": location["id"],
                    "code": f"CAJA-0{number}",
                    "name": f"Caja {number}",
                },
            )
            terminals.append({"id": terminal["id"]})
        branches.append(
            {
                "id": branch["id"],
                "code": code,
                "emissionPointId": emission["id"],
                "locationId": location["id"],
                "warehouseCode": warehouse["code"],
                "terminals": terminals,
            }
        )
    return branches


def set_up_catalog(
    api: Api, branches: list[dict[str, Any]], size: int, customers: int
) -> None:
    api.ensure(
        "/api/admin/units-of-measure",
        "symbol",
        "und",
        {"name": "Unidad", "symbol": "und"},
    )
    api.ensure("/api/admin/price-lists", "name", PRICE_LIST, {"name": PRICE_LIST})
    if (
        api.request("GET", "/api/admin/products", params={"limit": 1})["meta"][
            "pagination"
        ]["total"]
        >= size
    ):
        print("el catálogo ya está cargado")
        return

    rng = random.Random(92)
    products = []
    for index in range(1, size + 1):
        family = FAMILIES[index % len(FAMILIES)]
        # Most of what a hardware store sells costs little: two thirds under USD 3
        cents = rng.randint(5, 300) if index % 3 else rng.randint(300, 2500)
        products.append(
            (
                f"SKU-{index:05d}",
                f"{family} {SIZES[index % len(SIZES)]} ref {index:05d}",
                family,
                "und",
                f"786{index:010d}",
                f"{cents * 0.6 / 100:.2f}",
                f"{cents / 100:.2f}",
                "15",
            )
        )
    api.run_import(
        "PRODUCTS",
        csv_file(
            (
                "sku",
                "nombre",
                "categoria",
                "unidad",
                "codigo_barras",
                "precio_compra",
                "precio_venta",
                "iva",
            ),
            products,
        ),
    )
    api.run_import(
        "PRESENTATIONS",
        csv_file(
            ("sku", "presentacion", "factor", "codigo_barras"),
            (
                (row[0], "Caja x25", "25", f"787{index:010d}")
                for index, row in enumerate(products, 1)
                if index % 5 == 0
            ),
        ),
    )
    api.run_import(
        "PRICES",
        csv_file(
            ("lista", "sku", "cantidad_minima", "precio"),
            (
                (PRICE_LIST, row[0], "0", f"{max(float(row[6]) * 0.92, 0.01):.2f}")
                for row in products[: size // 5]
            ),
        ),
    )
    api.run_import(
        "STOCK",
        csv_file(
            ("bodega", "ubicacion", "sku", "cantidad", "costo_unitario"),
            (
                (branch["warehouseCode"], "GENERAL", row[0], "1000000", row[5])
                for branch in branches
                for row in products
            ),
        ),
    )
    api.run_import(
        "CUSTOMERS",
        csv_file(
            (
                "tipo_identificacion",
                "identificacion",
                "nombre",
                "cupo",
                "plazo_dias",
                "lista_precios",
            ),
            (
                (
                    "CEDULA",
                    cedula(index),
                    f"Cliente {index:04d}",
                    "1000000" if index % 4 == 0 else "",
                    "30" if index % 4 == 0 else "",
                    PRICE_LIST if index % 4 == 1 else "",
                )
                for index in range(1, customers + 1)
            ),
        ),
    )


def set_up_cashiers(api: Api, branches: list[dict[str, Any]], password: str) -> None:
    """Throwaway cashiers with the admin's password, so running it again needs no reset."""
    users = {u["username"] for u in api.every("/api/admin/users")}
    for branch in branches:
        for number, terminal in enumerate(branch["terminals"], 1):
            username = f"load-{branch['code']}-{number}"
            if username not in users:
                api.data(
                    "POST",
                    "/api/admin/users",
                    json={
                        "username": username,
                        "email": f"{username}@example.com",
                        "password": password,
                        "fullName": f"Cajero {branch['code']}-{number}",
                        "role": 5,
                    },
                )
            terminal["username"] = username
            terminal["password"] = password


def open_shifts(
    base_url: str, verify: str | bool, branches: list[dict[str, Any]]
) -> None:
    for branch in branches:
        for terminal in branch["terminals"]:
            cashier = Api(base_url, verify, terminal["username"], terminal["password"])
            cashier.login()
            headers = {
                "Authorization": f"Bearer {cashier.token}",
                "X-Branch-Id": str(branch["id"]),
                "X-Terminal-Id": str(terminal["id"]),
            }
            response = cashier.http.post(
                "/api/pos/shifts/open", json={"openingBalance": 100}, headers=headers
            )
            if response.status_code >= 400 and response.status_code != 409:
                raise SystemExit(
                    f"no se pudo abrir el turno: {response.status_code} {response.text}"
                )
    print("turnos abiertos")


def certificate(ruc: str, folder: Path, password: str) -> bytes:
    """A throwaway self-signed certificate naming the RUC (like faclab-infra/e2e/run.sh). The SRI
    never sees it: faclab-invoicing points at the simulator."""
    key, pem, p12 = folder / "key.pem", folder / "cert.pem", folder / "cert.p12"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "7"]
        + ["-subj", f"/C=EC/O=Faclab Load/CN=Faclab Load/serialNumber={ruc}"]
        + ["-keyout", str(key), "-out", str(pem)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkcs12", "-export", "-inkey", str(key), "-in", str(pem)]
        + ["-out", str(p12), "-passout", "env:P12_PASSWORD"]
        + ["-keypbe", "PBE-SHA1-3DES", "-certpbe", "PBE-SHA1-3DES", "-macalg", "sha1"],
        check=True,
        capture_output=True,
        env={**os.environ, "P12_PASSWORD": password},
    )
    return p12.read_bytes()


def set_up_issuer(api: Api, ruc: str) -> None:
    if api.data("GET", "/api/invoicing/status")["ready"]:
        print("el emisor ya está listo")
        return
    profile = {
        "taxId": ruc,
        "name": "Ferretería de carga",
        "tradeName": "Ferretería de carga",
        "mainAddress": "Av. 10 de Agosto, Quito",
        "accountingRequired": True,
        "environment": 1,
        "emissionType": 1,
    }
    api.data("PUT", "/api/company-config", json=profile)
    password = secrets.token_hex(12)
    with tempfile.TemporaryDirectory() as folder:
        content = certificate(ruc, Path(folder), password)
    created = api.data(
        "POST",
        "/api/certificates",
        data={"password": password},
        files={"file": ("load.p12", content, "application/x-pkcs12")},
    )
    api.data(
        "PUT", "/api/company-config", json={**profile, "signingCertId": created["id"]}
    )
    print("emisor configurado:", api.data("GET", "/api/invoicing/status")["ready"])


def integration_client(api: Api) -> dict[str, str]:
    """A new client each time: the secret is only shown when it is created."""
    created = api.data(
        "POST",
        "/api/admin/integrations",
        json={"name": f"Carga {secrets.token_hex(3)}", "scopes": SCOPES},
    )
    client_id = created.get("clientId") or created["client"]["clientId"]
    secret = created.get("secret") or created.get("clientSecret")
    if isinstance(secret, dict):
        secret = secret["secret"]
    return {"id": client_id, "secret": str(secret)}


def sample_catalog(api: Api) -> dict[str, Any]:
    """What the scenarios sell: a spread of the catalog, and the customers by kind."""
    products = []
    for item in api.every("/api/admin/products"):
        if not item["sku"].startswith("SKU-") or int(item["sku"][4:]) % 3 == 1:
            continue
        family, size = item["name"].split(" ref ")[0].rsplit(" ", 1)
        products.append(
            {
                "id": item["id"],
                "cents": round(float(item["salePrice"]) * 100),
                "barcode": item.get("barcode"),
                "term": f"{family} {size}",
            }
        )
    customers = api.every("/api/admin/customers")
    return {
        "products": products,
        "creditCustomers": [c["id"] for c in customers if c.get("creditLimit")],
        "listCustomers": [c["id"] for c in customers if c.get("priceListId")],
        "customers": [c["id"] for c in customers],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--products", type=int, default=10_000)
    parser.add_argument("--customers", type=int, default=500)
    args = parser.parse_args()

    base_url = ensure_test_host(os.environ["LOAD_BASE_URL"])
    verify: str | bool = os.environ.get("LOAD_CA_FILE") or True
    admin = Api(
        base_url,
        verify,
        os.environ["LOAD_ADMIN_USERNAME"],
        os.environ["LOAD_ADMIN_PASSWORD"],
    )

    branches = set_up_structure(admin)
    set_up_catalog(admin, branches, args.products, args.customers)
    set_up_cashiers(admin, branches, admin.password)
    set_up_issuer(admin, os.environ["LOAD_RUC"])
    open_shifts(base_url, verify, branches)
    fixtures = {
        "baseUrl": base_url,
        "admin": {"username": admin.username, "password": admin.password},
        "client": integration_client(admin),
        "branches": branches,
        **sample_catalog(admin),
    }
    args.fixtures.touch(mode=0o600, exist_ok=True)
    args.fixtures.chmod(0o600)
    args.fixtures.write_text(json.dumps(fixtures))
    print(f"{len(fixtures['products'])} productos de muestra en {args.fixtures}")


if __name__ == "__main__":
    main()
