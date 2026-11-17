from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from ipaddress import ip_address, ip_network

from src.auth.domain.scopes import Scope
from src.integrations.domain.credentials import (
    SECRET_PREFIX_LENGTH,
    IntegrationEnvironment,
    hash_secret,
    new_public_id,
    secret_matches,
)
from src.integrations.domain.exceptions import IntegrationClientRevokedError
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError

# Rotation: the new secret and the one it replaces, at the same time
MAX_ACTIVE_SECRETS = 2
NAME_MAX_LENGTH = 64  # it is the actor's name in the audit log
MAX_ALLOWED_NETWORKS = 20


class IntegrationClientStatus(StrEnum):
    ACTIVE = "ACTIVE"
    # Terminal: its secrets are revoked and its tokens stop working
    REVOKED = "REVOKED"


@dataclass
class IntegrationClient(Entity):
    """A system of the tenant that calls the API with OAuth 2.0 client
    credentials (S6.2): a service principal with scopes, optionally limited to
    some branches and source addresses. It belongs to the environment of the
    deployment where it was created."""

    public_id: str
    name: str
    environment: IntegrationEnvironment
    scopes: frozenset[Scope]
    # None: every branch of the tenant
    branch_ids: frozenset[int] | None = None
    # Networks (CIDR) it may call from; None: any address
    allowed_ips: tuple[str, ...] | None = None
    status: IntegrationClientStatus = IntegrationClientStatus.ACTIVE
    id: int | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def new(
        cls,
        environment: IntegrationEnvironment,
        name: str,
        scopes: Iterable[Scope],
        branch_ids: Iterable[int] | None = None,
        allowed_ips: Iterable[str] | None = None,
    ) -> "IntegrationClient":
        client = cls(
            public_id=new_public_id(environment),
            name="",
            environment=environment,
            scopes=frozenset(),
        )
        client.configure(name, scopes, branch_ids, allowed_ips)
        return client

    @property
    def is_active(self) -> bool:
        return self.status is IntegrationClientStatus.ACTIVE

    def ensure_active(self) -> None:
        if not self.is_active:
            raise IntegrationClientRevokedError()

    def configure(
        self,
        name: str,
        scopes: Iterable[Scope],
        branch_ids: Iterable[int] | None,
        allowed_ips: Iterable[str] | None,
    ) -> None:
        """Its name, scopes, branches and addresses. No branches (or no
        addresses) means all of them"""
        self.ensure_active()
        name = name.strip()
        if not name or len(name) > NAME_MAX_LENGTH:
            raise InvalidValueError(
                f"The name must have 1 to {NAME_MAX_LENGTH} characters"
            )
        granted = frozenset(scopes)
        if not granted:
            raise InvalidValueError("The client needs at least one scope")
        self.name = name
        self.scopes = granted
        self.branch_ids = frozenset(branch_ids) if branch_ids else None
        self.allowed_ips = normalize_networks(allowed_ips)

    def revoke(self, now: datetime) -> None:
        self.ensure_active()
        self.status = IntegrationClientStatus.REVOKED
        self.revoked_at = now

    def allows_ip(self, ip: str | None) -> bool:
        return allows_ip(self.allowed_ips, ip)

    def record_use(self, now: datetime) -> None:
        self.last_used_at = now


@dataclass
class ClientSecret(Entity):
    """A secret of a client; only its hash is kept. Up to two are active at a
    time so the integration can switch to a new one without stopping."""

    client_id: int
    prefix: str
    secret_hash: str
    id: int | None = None
    created_at: datetime | None = None
    # Set when it is rotated with an expiry; None: until revoked
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None

    @classmethod
    def for_client(cls, client_id: int, secret: str) -> "ClientSecret":
        return cls(
            client_id=client_id,
            prefix=secret[:SECRET_PREFIX_LENGTH],
            secret_hash=hash_secret(secret),
        )

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > now
        )

    def matches(self, secret: str) -> bool:
        return secret_matches(secret, self.secret_hash)

    def revoke(self, now: datetime) -> None:
        if self.revoked_at is None:
            self.revoked_at = now

    def expire_at(self, when: datetime) -> None:
        """Stops working at `when`, unless it already expires earlier"""
        if self.expires_at is None or when < self.expires_at:
            self.expires_at = when

    def record_use(self, now: datetime) -> None:
        self.last_used_at = now


def normalize_networks(values: Iterable[str] | None) -> tuple[str, ...] | None:
    """The networks as CIDR (`203.0.113.7` becomes `203.0.113.7/32`), sorted
    and without repeats; none means any address"""
    if not values:
        return None
    networks = set()
    for value in values:
        try:
            networks.add(str(ip_network(value.strip(), strict=False)))
        except ValueError:
            raise InvalidValueError(f"Not an IP address or network: {value}") from None
    if len(networks) > MAX_ALLOWED_NETWORKS:
        raise InvalidValueError(
            f"At most {MAX_ALLOWED_NETWORKS} allowed addresses or networks"
        )
    return tuple(sorted(networks))


def allows_ip(networks: tuple[str, ...] | None, ip: str | None) -> bool:
    if networks is None:
        return True
    if ip is None:
        return False
    try:
        address = ip_address(ip)
    except ValueError:
        return False
    return any(address in ip_network(network) for network in networks)
