from urllib.parse import urlsplit, urlunsplit

from src.webhooks.domain.entities import WebhookEndpoint


def describe_endpoint(endpoint: WebhookEndpoint) -> dict:
    """The endpoint as the API shows it: its secret only by its hint"""
    return {
        "id": endpoint.id,
        "url": endpoint.url,
        "description": endpoint.description,
        "event_types": sorted(endpoint.event_types),
        "status": endpoint.status,
        "disabled_reason": endpoint.disabled_reason,
        "disabled_at": endpoint.disabled_at,
        "integration_client_id": endpoint.integration_client_id,
        "exclude_own_changes": endpoint.exclude_own_changes,
        "secret_hint": endpoint.secret_hint,
        "previous_secret_expires_at": endpoint.previous_secret_expires_at,
        "last_success_at": endpoint.last_success_at,
        "failing_since": endpoint.failing_since,
        "created_at": endpoint.created_at,
        "updated_at": endpoint.updated_at,
    }


def redacted_url(url: str) -> str:
    """The URL without its query, which may carry a token of the receiver: what
    the audit log and the logs keep"""
    parts = urlsplit(url)
    query = "…" if parts.query else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def url_host(url: str) -> str:
    return urlsplit(url).hostname or ""
