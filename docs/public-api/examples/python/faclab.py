"""Cliente mínimo de la API pública de Faclab, sin más dependencia que httpx.

- Pide el token con client credentials y lo reutiliza hasta un minuto antes de
  que venza.
- Cada POST lleva su `Idempotency-Key`: pasa la misma en los reintentos de una
  misma operación.
- Ante 429 espera `Retry-After` y reintenta.
- Los errores llegan como `FaclabError` con el código del catálogo.

Lee la configuración del entorno: FACLAB_API_URL (por defecto
http://localhost:3000), FACLAB_CLIENT_ID y FACLAB_CLIENT_SECRET.
"""

import os
import time
import uuid
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal

import httpx

# Tarifa de cada código de IVA (`taxCode` de los productos)
TAX_RATES = {
    "VAT_0": Decimal("0"),
    "VAT_5": Decimal("5"),
    "VAT_8_TOURISM": Decimal("8"),
    "VAT_12": Decimal("12"),
    "VAT_13": Decimal("13"),
    "VAT_14": Decimal("14"),
    "VAT_15": Decimal("15"),
    "EXEMPT": Decimal("0"),
    "NOT_TAXED": Decimal("0"),
}

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(unit_price: str, quantity: str, tax_code: str) -> Decimal:
    """Lo que cobra Faclab por una línea sin descuento: el subtotal y el IVA,
    cada uno redondeado al centavo (mitad hacia arriba)"""
    subtotal = Decimal(unit_price) * Decimal(quantity)
    return cents(subtotal) + cents(subtotal * TAX_RATES[tax_code] / 100)


class FaclabError(Exception):
    def __init__(self, response: httpx.Response):
        self.status = response.status_code
        self.request_id = response.headers.get("X-Request-Id")
        try:
            error = response.json()["errors"][0]
        except (ValueError, KeyError, IndexError):
            error = {"code": f"HTTP_{response.status_code}", "message": response.text}
        self.code = error.get("code")
        self.field = error.get("field")
        self.body = error
        super().__init__(
            f"{self.status} {self.code}: {error.get('message')} "
            f"(requestId {self.request_id})"
        )


class Faclab:
    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.base_url = (
            base_url or os.environ.get("FACLAB_API_URL", "http://localhost:3000")
        ).rstrip("/")
        self._credentials = (
            client_id or os.environ["FACLAB_CLIENT_ID"],
            client_secret or os.environ["FACLAB_CLIENT_SECRET"],
        )
        self.http = httpx.Client(base_url=self.base_url, timeout=30)
        self._token: str | None = None
        self._expires_at = 0.0

    def token(self) -> str:
        if self._token and time.monotonic() < self._expires_at - 60:
            return self._token
        response = self.http.post(
            "/api/oauth/token",
            data={"grant_type": "client_credentials"},
            auth=self._credentials,
        )
        if response.status_code != 200:
            # El endpoint de token responde como OAuth: {"error", "error_description"}
            raise RuntimeError(f"token: {response.status_code} {response.text}")
        body = response.json()
        self._token = body["access_token"]
        self._expires_at = time.monotonic() + body["expires_in"]
        return self._token

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        branch_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers = {}
        if branch_id is not None:
            headers["X-Branch-Id"] = str(branch_id)
        if method == "POST":
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        renewed = False
        for _ in range(5):
            headers["Authorization"] = f"Bearer {self.token()}"
            response = self.http.request(
                method, path, json=json, params=params, headers=headers
            )
            if response.status_code == 429:
                time.sleep(int(response.headers.get("Retry-After", "1")))
                continue
            if response.status_code == 401 and not renewed:
                # Venció mientras tanto: una vez con un token nuevo
                self._token = None
                renewed = True
                continue
            break
        if response.is_error:
            raise FaclabError(response)
        return response

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params=params or None).json()

    def post(self, path: str, body: dict, **options) -> httpx.Response:
        return self.request("POST", path, json=body, **options)

    def pages(self, path: str, **params) -> Iterator[dict]:
        """Todas las filas de un listado, página por página (orden estable)"""
        limit = int(params.pop("limit", 200))
        offset = 0
        while True:
            page = self.get(path, limit=limit, offset=offset, **params)
            yield from page["data"]
            if len(page["data"]) < limit:
                return
            offset += limit
