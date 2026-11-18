"""A webhook receiver for the tests (S6.4): HTTPS on 127.0.0.1 with a
self-signed certificate for `localhost`, that checks each message's signature
with the code PUBLIC_API.md §7.2 publishes, as an integrator copies it."""

import base64
import datetime as dt
import hashlib
import hmac
import ipaddress
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from src.webhooks.domain.signing import secret_key


def verify(secret: bytes, msg_id: str, ts: str, body: bytes, header: str) -> bool:
    """PUBLIC_API.md §7.2, as published"""
    if abs(time.time() - int(ts)) > 300:
        return False
    expected = base64.b64encode(
        hmac.new(secret, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return any(
        hmac.compare_digest(expected, sig.split(",", 1)[1]) for sig in header.split(" ")
    )


@dataclass(frozen=True)
class Certificate:
    cert_pem: bytes
    key_pem: bytes

    def client_context(self) -> ssl.SSLContext:
        """What the sender trusts: this certificate alone"""
        return ssl.create_default_context(cadata=self.cert_pem.decode())


def localhost_certificate() -> Certificate:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return Certificate(
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


@dataclass
class Received:
    path: str
    headers: dict[str, str]
    body: bytes
    verified: bool


@dataclass
class Receiver:
    """Answers `status` after `delay` seconds and keeps what it got"""

    certificate: Certificate
    status: int = 204
    delay: float = 0.0
    # The endpoint's secrets (whsec_…) it checks the signatures with
    secrets: list[str] = field(default_factory=list)
    received: list[Received] = field(default_factory=list)

    def __post_init__(self):
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                headers = {k.lower(): v for k, v in self.headers.items()}
                verified = any(
                    verify(
                        secret_key(secret),
                        headers.get("webhook-id", ""),
                        headers.get("webhook-timestamp", "0"),
                        body,
                        headers.get("webhook-signature", ""),
                    )
                    for secret in receiver.secrets
                )
                receiver.received.append(Received(self.path, headers, body, verified))
                if receiver.delay:
                    time.sleep(receiver.delay)
                self.send_response(receiver.status)
                if 300 <= receiver.status < 400:
                    self.send_header("Location", "https://localhost/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        with tempfile.TemporaryDirectory() as folder:
            cert, key = Path(folder) / "cert.pem", Path(folder) / "key.pem"
            cert.write_bytes(self.certificate.cert_pem)
            key.write_bytes(self.certificate.key_pem)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def url(self) -> str:
        return f"https://localhost:{self.port}/hooks"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
