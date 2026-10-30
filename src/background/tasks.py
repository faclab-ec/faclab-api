"""Periodic tasks of the worker. Each one works across tenants as
faclab_worker; the purges are idempotent DELETEs and the reconciliation can't
open a discrepancy twice, so two workers only repeat work."""

from config import config
from src.auth.infra import session_purge
from src.invoicing.infra import reconciliation
from src.shared.infra.idempotency import purge as idempotency_purge
from src.shared.infra.outbox import purge as outbox_purge
from src.shared.infra.worker.runner import PeriodicTask


def periodic_tasks() -> list[PeriodicTask]:
    interval = config.WORKER_PURGE_INTERVAL_SECONDS
    tasks = [
        PeriodicTask("outbox_purge", interval, outbox_purge.purge),
        PeriodicTask("idempotency_keys_purge", interval, idempotency_purge.purge),
        PeriodicTask("auth_sessions_purge", interval, session_purge.purge),
    ]
    # Without Kafka nothing is sent to faclab-invoicing, so nothing to reconcile
    if config.KAFKA_ENABLED and config.INVOICE_RECONCILIATION_ENABLED:
        tasks.append(
            PeriodicTask(
                "invoice_reconciliation",
                config.INVOICE_RECONCILIATION_INTERVAL_SECONDS,
                reconciliation.reconcile,
            )
        )
    return tasks
