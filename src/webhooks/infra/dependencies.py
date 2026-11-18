from config import config
from src.webhooks.domain.exceptions import WebhooksDisabledError


def webhooks_enabled() -> None:
    """WEBHOOKS_ENABLED=false turns the webhook routes off (503), the rollback"""
    if not config.WEBHOOKS_ENABLED:
        raise WebhooksDisabledError()
