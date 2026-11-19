"""Receptor de webhooks de Faclab (guías "Webhooks" y "Facturas por webhook").

Comprueba la firma Standard Webhooks, rechaza mensajes de más de 5 minutos,
responde 204 de inmediato y procesa después, una sola vez por `webhook-id`.
Ante `invoice.authorized` pide la factura a la API y guarda su RIDE.

    FACLAB_WEBHOOK_SECRET=whsec_... python receptor_webhooks.py

- FACLAB_WEBHOOK_SECRET: el secreto del endpoint (`GET …/secret`). En su
  lugar, FACLAB_WEBHOOK_SECRET_FILE: un archivo que lo contiene, leído en cada
  mensaje (sirve para rotarlo sin reiniciar).
- FACLAB_WEBHOOK_PORT (8000) y FACLAB_WEBHOOK_BIND (127.0.0.1).
- Con FACLAB_CLIENT_ID y FACLAB_CLIENT_SECRET, descarga las facturas
  autorizadas en FACLAB_INVOICES_DIR (./facturas).

En producción va detrás de HTTPS: Faclab solo envía a URLs https públicas.
"""

import base64
import hashlib
import hmac
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOLERANCE_SECONDS = 300


def secret() -> bytes:
    path = os.environ.get("FACLAB_WEBHOOK_SECRET_FILE")
    value = (
        Path(path).read_text().strip() if path else os.environ["FACLAB_WEBHOOK_SECRET"]
    )
    return base64.b64decode(value.removeprefix("whsec_"))


def verify(msg_id: str, timestamp: str, body: bytes, header: str) -> bool:
    """La firma de `{id}.{timestamp}.{cuerpo}` con HMAC-SHA256, sobre el cuerpo tal
    como llegó. Durante una rotación el encabezado trae dos firmas"""
    try:
        if abs(time.time() - int(timestamp)) > TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False
    expected = base64.b64encode(
        hmac.new(
            secret(), f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256
        ).digest()
    ).decode()
    return any(
        hmac.compare_digest(expected, signature.split(",", 1)[-1])
        for signature in header.split(" ")
        if signature.startswith("v1,")
    )


seen: set[str] = set()
events: queue.Queue[dict] = queue.Queue()


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        msg_id = self.headers.get("webhook-id", "")
        ok = verify(
            msg_id,
            self.headers.get("webhook-timestamp", ""),
            body,
            self.headers.get("webhook-signature", ""),
        )
        # Rápido: el trabajo se hace fuera de la solicitud
        self.send_response(204 if ok else 401)
        self.end_headers()
        if not ok:
            print(f"firma inválida {msg_id}", flush=True)
            return
        if msg_id in seen:  # un reintento de algo ya recibido
            return
        seen.add(msg_id)
        events.put(json.loads(body))

    def log_message(self, *args):
        pass


def download_invoice(invoice_id: int) -> None:
    from faclab import Faclab  # solo si hay credenciales

    api = Faclab()
    invoice = api.get(f"/api/v1/invoices/{invoice_id}")["data"]
    folder = Path(os.environ.get("FACLAB_INVOICES_DIR", "facturas"))
    folder.mkdir(exist_ok=True)
    ride = api.request("GET", f"/api/v1/invoices/{invoice_id}/ride")
    (folder / f"{invoice['accessCode']}.pdf").write_bytes(ride.content)
    print(f"  factura {invoice['number']} guardada en {folder}", flush=True)


def process(event: dict) -> None:
    data = event["data"]
    print(f"verificado {event['type']} {event['id']}", flush=True)
    if event["type"] == "invoice.authorized":
        print(f"  venta {data['saleNumber']}: factura {data['invoiceId']}", flush=True)
        if os.environ.get("FACLAB_CLIENT_ID"):
            download_invoice(data["invoiceId"])
    elif event["type"] == "invoice.rejected":
        print(f"  venta {data['saleNumber']} rechazada: {data['reason']}", flush=True)
    elif event["type"] == "credit_note.authorized":
        print(
            f"  nota de crédito {data['number']} de la venta {data['saleId']}",
            flush=True,
        )


def worker() -> None:
    while True:
        event = events.get()
        try:
            process(event)
        except Exception as error:  # un evento que falla no detiene a los demás
            print(f"error procesando {event.get('id')}: {error}", flush=True)


def main() -> None:
    port = int(os.environ.get("FACLAB_WEBHOOK_PORT", "8000"))
    bind = os.environ.get("FACLAB_WEBHOOK_BIND", "127.0.0.1")
    threading.Thread(target=worker, daemon=True).start()
    print(f"escuchando en http://{bind}:{port}", flush=True)
    ThreadingHTTPServer((bind, port), Receiver).serve_forever()


if __name__ == "__main__":
    main()
