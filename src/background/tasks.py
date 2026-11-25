"""Periodic tasks of the worker. Each one works across tenants as
faclab_worker; the purges are idempotent DELETEs, the quote expiration an
idempotent UPDATE and the reconciliation can't open a discrepancy twice, so two
workers only repeat work. The imports lock each one while they run a batch of
it, so two workers never run the same batch."""

from config import config
from src.auth.infra import session_purge
from src.background import queue_metrics
from src.data_protection.infra import purge as export_purge, runner as export_runner
from src.imports.infra import purge as import_purge, runner as import_runner
from src.invoicing.infra import reconciliation
from src.public_api.infra import rate_limit as public_api_rate_limit
from src.quotes.infra import expiration as quote_expiration
from src.shared.infra.idempotency import purge as idempotency_purge
from src.shared.infra.outbox import purge as outbox_purge
from src.shared.infra.worker.runner import PeriodicTask
from src.webhooks.infra import (
    purge as webhook_purge,
    stock_changes as webhook_stock_changes,
)


def periodic_tasks() -> list[PeriodicTask]:
    interval = config.WORKER_PURGE_INTERVAL_SECONDS
    tasks = [
        PeriodicTask("outbox_purge", interval, outbox_purge.purge),
        PeriodicTask("idempotency_keys_purge", interval, idempotency_purge.purge),
        PeriodicTask("auth_sessions_purge", interval, session_purge.purge),
        # Quotes past their validity (S5.4); with the purges' interval
        PeriodicTask("quote_expiration", interval, quote_expiration.expire),
        # Bulk imports (S5.8): the confirmed ones in batches, and their rows
        # once old
        PeriodicTask(
            "imports", config.IMPORT_POLL_INTERVAL_SECONDS, import_runner.run_imports
        ),
        PeriodicTask("import_rows_purge", interval, import_purge.purge),
        # The data export of a company (S8.7): the ZIP is written in a thread
        # of its own, so the task returns at once; its files expire
        PeriodicTask(
            "data_exports",
            config.DATA_EXPORT_POLL_INTERVAL_SECONDS,
            export_runner.run_exports,
        ),
        PeriodicTask("data_export_files_purge", interval, export_purge.purge),
        # The public API's rate limit counters whose bucket is full (S6.3)
        PeriodicTask("api_rate_limits_purge", interval, public_api_rate_limit.purge),
        # The outbox and dead letter gauges (S7.1); also without Kafka: a
        # message left pending is still worth seeing
        PeriodicTask(
            "queue_metrics",
            config.WORKER_METRICS_INTERVAL_SECONDS,
            queue_metrics.sample,
        ),
    ]
    # The webhooks' stock.changed, grouped by product and branch (S6.4): while
    # the sending is paused they keep piling up as pending deliveries
    if config.WEBHOOKS_ENABLED:
        tasks.append(
            PeriodicTask(
                "webhook_stock_changes",
                config.WEBHOOK_STOCK_BATCH_SECONDS,
                webhook_stock_changes.flush_stock_changes,
            )
        )
    # The webhooks' history of WEBHOOK_RETENTION_DAYS
    tasks.append(
        PeriodicTask("webhook_deliveries_purge", interval, webhook_purge.purge)
    )
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
