"""Which URLs the server calls with a webhook (SSRF, ADR-0009).

An endpoint is an HTTPS URL towards public addresses. Its name is resolved
when it is registered and again before each attempt, and the request connects
to the very address that was checked (`src/webhooks/infra/http.py`), so a name
that resolves to a public address when registered and to an internal one later
(DNS rebinding) reaches nothing internal.

Refused: another scheme, a user or password in the URL, a fragment, `localhost`,
a name that doesn't resolve, and any address that is not global: private,
loopback, link-local (169.254.169.254, the cloud metadata), shared (100.64/10),
multicast, reserved or of documentation, also inside an IPv6 address
(IPv4-mapped, 6to4, Teredo, NAT64 64:ff9b::/96), the deprecated IPv4-compatible
::/96 and the local-use NAT64 64:ff9b:1::/48 (S9.3). WEBHOOK_ALLOW_PRIVATE_URLS, local only, lets a
development receiver on http://localhost through.
"""

import socket
from collections.abc import Callable
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, IPv6Network, ip_address
from urllib.parse import urlsplit

from wireup import injectable

from config import config
from src.webhooks.app.ports import WebhookUrlPolicy
from src.webhooks.domain.entities import URL_MAX_LENGTH
from src.webhooks.domain.exceptions import WebhookUrlNotAllowedError

# host, port -> its addresses
Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    addresses: list[str] = []
    for *_, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        address = str(sockaddr[0])
        if address not in addresses:
            addresses.append(address)
    return addresses


# Python counts them as global
_NAT64 = IPv6Network("64:ff9b::/96")
_NEVER = (IPv6Network("::/96"), IPv6Network("64:ff9b:1::/48"))


def _embedded_ipv4(address: IPv6Address) -> IPv4Address | None:
    if address in _NAT64:
        return IPv4Address(int(address) & 0xFFFFFFFF)
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    return None


def address_allowed(text: str) -> bool:
    """Whether the server may connect to this address: a global one"""
    try:
        address = ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, IPv6Address):
        if any(address in network for network in _NEVER):
            return False
        embedded = _embedded_ipv4(address)
        if embedded is not None and not address_allowed(str(embedded)):
            return False
    return address.is_global and not address.is_multicast


@dataclass(frozen=True)
class Target:
    """Where a request goes: the checked addresses of the URL's host"""

    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]
    # The path and query, what the request line carries
    request_target: str


class DnsUrlGuard(WebhookUrlPolicy):
    def __init__(
        self, resolver: Resolver = system_resolver, allow_private: bool = False
    ):
        self.resolver = resolver
        self.allow_private = allow_private

    def ensure_allowed(self, url: str) -> None:
        self.target(url)

    def target(self, url: str) -> Target:
        """The checked addresses of the URL; raises `WebhookUrlNotAllowedError`"""
        if len(url) > URL_MAX_LENGTH:
            raise WebhookUrlNotAllowedError(f"it is longer than {URL_MAX_LENGTH}")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise WebhookUrlNotAllowedError("it is not a valid URL") from None
        schemes = ("https", "http") if self.allow_private else ("https",)
        if parts.scheme not in schemes:
            raise WebhookUrlNotAllowedError("it must be https")
        if parts.username is not None or parts.password is not None:
            raise WebhookUrlNotAllowedError("it can't carry a user or password")
        if parts.fragment:
            raise WebhookUrlNotAllowedError("it can't have a fragment (#)")
        host = (parts.hostname or "").rstrip(".")
        if not host:
            raise WebhookUrlNotAllowedError("it has no host")
        if not self.allow_private and (
            host == "localhost" or host.endswith(".localhost")
        ):
            raise WebhookUrlNotAllowedError("it points at this server")
        port = port or (443 if parts.scheme == "https" else 80)
        addresses = self._addresses(host, port)
        if not self.allow_private:
            refused = [a for a in addresses if not address_allowed(a)]
            if refused:
                raise WebhookUrlNotAllowedError(
                    "it resolves to a private or local address"
                )
        path = parts.path or "/"
        return Target(
            scheme=parts.scheme,
            host=host,
            port=port,
            addresses=tuple(addresses),
            request_target=f"{path}?{parts.query}" if parts.query else path,
        )

    def _addresses(self, host: str, port: int) -> list[str]:
        try:
            return [str(ip_address(host))]
        except ValueError:
            pass
        try:
            addresses = self.resolver(host, port)
        except (OSError, UnicodeError):
            raise WebhookUrlNotAllowedError("its host doesn't resolve") from None
        if not addresses:
            raise WebhookUrlNotAllowedError("its host doesn't resolve")
        return addresses


@injectable(lifetime="singleton")
def webhook_url_policy() -> WebhookUrlPolicy:
    return DnsUrlGuard(allow_private=config.WEBHOOK_ALLOW_PRIVATE_URLS)
