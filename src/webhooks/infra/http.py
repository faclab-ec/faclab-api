"""The webhooks' HTTP client (S6.4), with the standard library alone.

Before each attempt the URL's host is resolved and every address checked
(`DnsUrlGuard`), and the connection goes to the very address that was checked,
with the TLS certificate verified against the host's name: a name that later
resolves to an internal address reaches nothing internal. One attempt has
`timeout` seconds in all (connecting, TLS, the request and the answer); a
redirect is an answer like any other, never followed; at most 64 KB of the
answer are read, and only its status is kept.
"""

import contextlib
import http.client
import socket
import ssl
import threading
import time
from dataclasses import dataclass

from src.webhooks.domain.exceptions import WebhookUrlNotAllowedError
from src.webhooks.infra.urls import DnsUrlGuard, Target

USER_AGENT = "Faclab-Webhooks/1.0"
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class SendResult:
    status: int | None
    # What went wrong, in our words (never the receiver's body)
    error: str | None
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


def _connect(
    addresses: tuple[str, ...], port: int, timeout: float | None
) -> socket.socket:
    last: OSError | None = None
    for address in addresses:
        try:
            return socket.create_connection((address, port), timeout=timeout)
        except OSError as exc:
            last = exc
    raise last or OSError("no address to connect to")


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Plain HTTP, only with WEBHOOK_ALLOW_PRIVATE_URLS (local)"""

    def __init__(self, target: Target, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout)
        self._addresses = target.addresses

    def connect(self) -> None:
        self.sock = _connect(self._addresses, self.port, self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, target: Target, timeout: float, tls: ssl.SSLContext):
        super().__init__(target.host, target.port, timeout=timeout, context=tls)
        self._addresses = target.addresses
        self._tls = tls

    def connect(self) -> None:
        sock = _connect(self._addresses, self.port, self.timeout)
        self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)


class WebhookSender:
    def __init__(
        self,
        guard: DnsUrlGuard,
        timeout: float = 10.0,
        tls: ssl.SSLContext | None = None,
    ):
        self.guard = guard
        self.timeout = timeout
        self.tls = tls or ssl.create_default_context()

    def post(self, url: str, headers: dict[str, str], body: bytes) -> SendResult:
        started = time.monotonic()

        def result(status: int | None, error: str | None) -> SendResult:
            return SendResult(status, error, int((time.monotonic() - started) * 1000))

        try:
            target = self.guard.target(url)
        except WebhookUrlNotAllowedError as exc:
            return result(None, f"address not allowed: {exc.reason}")
        connection: http.client.HTTPConnection = (
            _PinnedHTTPSConnection(target, self.timeout, self.tls)
            if target.scheme == "https"
            else _PinnedHTTPConnection(target, self.timeout)
        )
        timed_out = threading.Event()

        def abort() -> None:
            # The whole attempt's deadline: a receiver that answers a byte at a
            # time doesn't hold the worker past it
            timed_out.set()
            sock = connection.sock
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

        deadline = threading.Timer(self.timeout, abort)
        deadline.daemon = True
        deadline.start()
        try:
            connection.request(
                "POST",
                target.request_target,
                body=body,
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
            response = connection.getresponse()
            response.read(MAX_RESPONSE_BYTES)
            status = response.status
            return result(status, None if 200 <= status < 300 else f"HTTP {status}")
        except TimeoutError:
            return result(None, "timeout")
        except ssl.SSLError as exc:
            if timed_out.is_set():
                return result(None, "timeout")
            return result(None, f"TLS error: {exc.reason or type(exc).__name__}")
        except (OSError, http.client.HTTPException) as exc:
            if timed_out.is_set():
                return result(None, "timeout")
            reason = getattr(exc, "strerror", None) or type(exc).__name__
            return result(None, f"connection error: {reason}")
        finally:
            deadline.cancel()
            connection.close()
