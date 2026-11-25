from dataclasses import dataclass
from datetime import datetime

from src.shared.domain.entities import Entity


@dataclass
class PlatformOperator(Entity):
    """A user of the platform's team (S8.5). Users are global identities; this
    row says that one may log into the console. It is created with the CLI
    (`python -m src.platform_console.cli`), never over HTTP, and has no role or
    tenant: the console reaches every tenant."""

    user_id: int
    is_active: bool = True
    id: int | None = None
    created_at: datetime | None = None
