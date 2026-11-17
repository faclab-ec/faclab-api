from datetime import datetime, timedelta

import pytest

from src.auth.domain.scopes import Scope
from src.integrations.domain.credentials import (
    IntegrationEnvironment,
    hash_secret,
    is_public_id,
    new_public_id,
    new_secret,
    secret_matches,
)
from src.integrations.domain.entities import (
    ClientSecret,
    IntegrationClient,
    IntegrationClientStatus,
    allows_ip,
    normalize_networks,
)
from src.integrations.domain.exceptions import IntegrationClientRevokedError
from src.shared.domain.exceptions import InvalidValueError

NOW = datetime(2026, 11, 17, 12, 0)


def _client(
    name: str = "Tienda web",
    scopes: set[Scope] | None = None,
    branch_ids: list[int] | None = None,
    allowed_ips: list[str] | None = None,
) -> IntegrationClient:
    return IntegrationClient.new(
        IntegrationEnvironment.SANDBOX,
        name,
        {Scope.STOCK_READ} if scopes is None else scopes,
        branch_ids,
        allowed_ips,
    )


def test_the_public_id_says_the_environment():
    live = new_public_id(IntegrationEnvironment.PRODUCTION)
    test = new_public_id(IntegrationEnvironment.SANDBOX)

    assert live.startswith("fl_live_") and is_public_id(live)
    assert test.startswith("fl_test_") and is_public_id(test)
    assert not is_public_id("fl_live_XYZ")
    assert not is_public_id("admin")


def test_a_secret_is_random_and_only_its_hash_is_compared():
    secret = new_secret()

    assert len(secret) >= 43 and secret != new_secret()
    assert hash_secret(secret) != secret and len(hash_secret(secret)) == 64
    assert secret_matches(secret, hash_secret(secret))
    assert not secret_matches(secret + "x", hash_secret(secret))


def test_a_new_client_is_active_in_its_environment():
    client = _client(branch_ids=[3, 1], allowed_ips=["203.0.113.7"])

    assert client.status is IntegrationClientStatus.ACTIVE
    assert client.public_id.startswith("fl_test_")
    assert client.branch_ids == {1, 3}
    assert client.allowed_ips == ("203.0.113.7/32",)


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "  "},
        {"name": "x" * 65},
        {"scopes": set()},
        {"allowed_ips": ["not-an-ip"]},
        {"allowed_ips": [f"10.0.{n}.0/24" for n in range(21)]},
    ],
)
def test_an_invalid_client_is_rejected(overrides):
    with pytest.raises(InvalidValueError):
        _client(**overrides)


def test_no_branches_or_addresses_mean_all():
    client = _client(branch_ids=[], allowed_ips=[])

    assert client.branch_ids is None
    assert client.allowed_ips is None
    assert client.allows_ip("198.51.100.1")


def test_addresses_and_networks():
    networks = normalize_networks(["10.0.0.0/8", "203.0.113.7", "203.0.113.7/32"])

    assert networks == ("10.0.0.0/8", "203.0.113.7/32")
    assert allows_ip(networks, "10.20.30.40")
    assert allows_ip(networks, "203.0.113.7")
    assert not allows_ip(networks, "203.0.113.8")
    # Without an address, only a client without limit
    assert not allows_ip(networks, None)
    assert not allows_ip(networks, "testclient")
    assert normalize_networks(["2001:db8::/32"]) == ("2001:db8::/32",)


def test_a_revoked_client_is_final():
    client = _client()
    client.revoke(NOW)

    assert client.status is IntegrationClientStatus.REVOKED
    assert client.revoked_at == NOW
    with pytest.raises(IntegrationClientRevokedError):
        client.revoke(NOW)
    with pytest.raises(IntegrationClientRevokedError):
        client.configure("Otro", {Scope.STOCK_READ}, None, None)


def test_a_secret_keeps_only_its_hash_and_prefix():
    secret = ClientSecret.for_client(5, "abcdefghijklmnop")

    assert secret.prefix == "abcdef"
    assert secret.secret_hash == hash_secret("abcdefghijklmnop")
    assert secret.matches("abcdefghijklmnop")
    assert not secret.matches("abcdefghijklmnoq")


def test_a_secret_works_until_revoked_or_expired():
    secret = ClientSecret.for_client(5, "s3cr3t")
    assert secret.is_active(NOW)

    secret.expire_at(NOW + timedelta(days=7))
    assert secret.is_active(NOW)
    assert not secret.is_active(NOW + timedelta(days=7))

    # A later expiry never extends it
    secret.expire_at(NOW + timedelta(days=30))
    assert secret.expires_at == NOW + timedelta(days=7)

    secret.revoke(NOW)
    assert not secret.is_active(NOW)
