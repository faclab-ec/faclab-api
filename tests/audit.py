from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.shared.app.audit import AuditAction, AuditTrail


@dataclass
class AuditEntry:
    action: AuditAction
    resource_id: int | None
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    branch_id: int | None


class FakeAuditTrail(AuditTrail):
    """Keeps what a handler records, for unit tests"""

    def __init__(self):
        self.entries: list[AuditEntry] = []

    def record(
        self,
        action: AuditAction,
        resource_id: int | None,
        *,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        branch_id: int | None = None,
    ) -> None:
        self.entries.append(AuditEntry(action, resource_id, before, after, branch_id))

    @property
    def actions(self) -> list[AuditAction]:
        return [entry.action for entry in self.entries]
