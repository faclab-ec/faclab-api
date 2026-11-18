from dataclasses import dataclass
from typing import Any

from src.shared.domain.events import DomainEvent


@dataclass
class IntegrationClientRevoked(DomainEvent):
    """An integration client was revoked: what it had stops working, its
    webhook endpoints too (S6.4)"""

    client_id: int = 0

    def _payload(self) -> dict[str, Any]:
        return {"client_id": self.client_id}
