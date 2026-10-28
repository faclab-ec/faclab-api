"""Periodic tasks of the worker. Each one works across tenants as
faclab_worker; they are idempotent DELETEs, so two workers only repeat work."""

from config import config
from src.auth.infra import session_purge
from src.shared.infra.idempotency import purge as idempotency_purge
from src.shared.infra.outbox import purge as outbox_purge
from src.shared.infra.worker.runner import PeriodicTask


def periodic_tasks() -> list[PeriodicTask]:
    interval = config.WORKER_PURGE_INTERVAL_SECONDS
    return [
        PeriodicTask("outbox_purge", interval, outbox_purge.purge),
        PeriodicTask("idempotency_keys_purge", interval, idempotency_purge.purge),
        PeriodicTask("auth_sessions_purge", interval, session_purge.purge),
    ]
