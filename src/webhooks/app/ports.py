"""What the webhooks need from the infrastructure (S6.4)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class SecretBox(ABC):
    """Encrypts the endpoints' secrets with the environment's master key: a
    signature needs the secret itself, so it can't be kept as a hash like an
    integration client's"""

    @abstractmethod
    def seal(self, plain: str) -> str: ...

    @abstractmethod
    def open(self, sealed: str) -> str: ...


class WebhookUrlPolicy(ABC):
    """Which URLs the server may call (SSRF): HTTPS towards public addresses"""

    @abstractmethod
    def ensure_allowed(self, url: str) -> None:
        """Raises `WebhookUrlNotAllowedError` with the reason"""


@dataclass(frozen=True)
class WebhookSettings:
    # WEBHOOKS_ENABLED: false enqueues nothing and turns the routes off
    enabled: bool = True
    # The deliveries the history shows (and the purge keeps)
    retention_days: int = 30
