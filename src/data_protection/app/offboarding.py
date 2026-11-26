"""What the termination of a company's contract does to its data (S8.7).

Three steps, each audited and none before its time:

1. start: the subscription is cancelled (read-only, the company still exports),
   a grace period runs, and the end of the tax retention is calculated.
2. anonymize (after the grace period): everything that isn't needed by tax law
   is deleted (sessions, integrations, webhooks, imports, memberships, outbox)
   and the personal data of what is kept is anonymized (names, emails, phones,
   addresses of customers and suppliers, the authors' names). Tax
   identifications stay: they identify the buyer of an invoice we must keep.
3. purge (after the retention): every row of the company, the tenant last.

`TenantDataCleaner` is the port of the data side; the SQL is in infra.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID


class TenantDataCleaner(ABC):
    @abstractmethod
    def last_fiscal_activity(self, tenant_id: UUID) -> datetime | None:
        """The date of the company's latest sale, from when the retention counts"""

    @abstractmethod
    def pending_outbox(self, tenant_id: UUID) -> int:
        """Messages still on their way to other services (not yet published)"""

    @abstractmethod
    def plan(self, tenant_id: UUID) -> dict[str, dict[str, int]]:
        """What anonymizing and purging would do, writing nothing: rows to
        `purge` and `anonymize` per table, and the rows `retain`ed"""

    @abstractmethod
    def anonymize(self, tenant_id: UUID) -> dict[str, dict[str, int]]:
        """Step 2; returns the rows it deleted (`purge`) and anonymized"""

    @abstractmethod
    def purge(self, tenant_id: UUID) -> dict[str, int]:
        """Step 3; returns the rows it deleted per table"""
