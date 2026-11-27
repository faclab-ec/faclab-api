"""Which URLs receive webhooks (SSRF, S6.4): HTTPS towards public addresses."""

import pytest

from src.webhooks.domain.exceptions import WebhookUrlNotAllowedError
from src.webhooks.infra.urls import DnsUrlGuard, address_allowed
from tests.webhooks_kit import PUBLIC_ADDRESS, table_resolver

guard = DnsUrlGuard(resolver=table_resolver())


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.10",
        "127.0.0.1",
        "0.0.0.0",
        "169.254.169.254",  # the cloud metadata
        "100.64.0.1",  # shared (CGNAT)
        "192.0.2.10",  # documentation
        "198.18.0.1",  # benchmarking
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reserved
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fd00::1",
        "ff02::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",  # IPv4-mapped
        "::ffff:10.0.0.1",
        "2002:0a00:0001::1",  # 6to4 of 10.0.0.1
        "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1 (S9.3)
        "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
        "64:ff9b:1::808:808",  # local-use NAT64
        "::7f00:1",  # IPv4-compatible (deprecated)
        "::808:808",
        "not an address",
    ],
)
def test_private_and_local_addresses_are_refused(address):
    assert not address_allowed(address)


@pytest.mark.parametrize(
    "address",
    [
        PUBLIC_ADDRESS,
        "8.8.8.8",
        "2606:4700:4700::1111",
        "::ffff:8.8.8.8",
        "64:ff9b::808:808",  # NAT64 of a public address
    ],
)
def test_public_addresses_are_allowed(address):
    assert address_allowed(address)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://hooks.tienda.example/faclab", "it must be https"),
        ("ftp://hooks.tienda.example/faclab", "it must be https"),
        ("https://user:pass@hooks.tienda.example/", "user or password"),
        ("https://hooks.tienda.example/#top", "fragment"),
        ("https://localhost/hooks", "points at this server"),
        ("https://api.localhost/hooks", "points at this server"),
        ("https:///hooks", "no host"),
        ("https://hooks.tienda.example:99999/", "not a valid URL"),
        ("https://interno.tienda.example/hooks", "private or local address"),
        ("https://10.0.0.5/hooks", "private or local address"),
        ("https://[::1]/hooks", "private or local address"),
        ("https://169.254.169.254/latest/meta-data", "private or local address"),
        ("https://desconocido.example/hooks", "doesn't resolve"),
        ("https://hooks.tienda.example/" + "a" * 2048, "longer than"),
    ],
)
def test_a_url_the_server_may_not_call_is_refused(url, reason):
    with pytest.raises(WebhookUrlNotAllowedError) as raised:
        guard.ensure_allowed(url)

    assert reason in raised.value.reason
    assert raised.value.extra == {"field": "url"}


def test_a_name_with_one_private_address_among_public_ones_is_refused():
    mixed = DnsUrlGuard(
        resolver=table_resolver({"mixto.example": [PUBLIC_ADDRESS, "10.0.0.5"]})
    )

    with pytest.raises(WebhookUrlNotAllowedError):
        mixed.ensure_allowed("https://mixto.example/hooks")


def test_the_target_keeps_the_checked_addresses_the_port_and_the_query():
    target = guard.target("https://hooks.tienda.example:8443/faclab?token=abc")

    assert target.addresses == (PUBLIC_ADDRESS,)
    assert (target.scheme, target.host, target.port) == (
        "https",
        "hooks.tienda.example",
        8443,
    )
    assert target.request_target == "/faclab?token=abc"
    assert guard.target("https://hooks.tienda.example").request_target == "/"


def test_a_development_receiver_on_this_machine_needs_the_local_switch():
    local = DnsUrlGuard(
        resolver=table_resolver({"localhost": ["127.0.0.1"]}), allow_private=True
    )

    target = local.target("http://localhost:9000/hooks")

    assert target.addresses == ("127.0.0.1",)
    assert target.port == 9000
