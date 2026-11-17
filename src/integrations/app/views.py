from collections.abc import Iterable
from datetime import datetime

from src.integrations.domain.entities import ClientSecret, IntegrationClient


def describe_client(
    client: IntegrationClient, secrets: Iterable[ClientSecret], now: datetime
) -> dict:
    """The client as the API shows it: never a secret nor its hash"""
    return {
        "id": client.id,
        "client_id": client.public_id,
        "name": client.name,
        "environment": client.environment,
        "status": client.status,
        "scopes": sorted(client.scopes),
        "branch_ids": sorted(client.branch_ids) if client.branch_ids else None,
        "allowed_ips": list(client.allowed_ips) if client.allowed_ips else None,
        "created_at": client.created_at,
        "updated_at": client.updated_at,
        "revoked_at": client.revoked_at,
        "last_used_at": client.last_used_at,
        "secrets": [
            describe_secret(secret, now)
            for secret in sorted(secrets, key=lambda s: s.id or 0)
        ],
    }


def describe_secret(secret: ClientSecret, now: datetime) -> dict:
    return {
        "id": secret.id,
        "prefix": secret.prefix,
        "is_active": secret.is_active(now),
        "created_at": secret.created_at,
        "expires_at": secret.expires_at,
        "revoked_at": secret.revoked_at,
        "last_used_at": secret.last_used_at,
    }
