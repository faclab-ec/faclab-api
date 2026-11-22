"""The core's metrics, all in one place (OBSERVABILITY.md §6).

Attributes stay bounded: never the id of a tenant, sale, user, customer,
product or invoice (`tests/unit/shared/test_metric_attributes.py` checks every
attribute the code emits). Units follow UCUM: `s`, `ms`, `{message}`.

The gauges the database feeds are observable: a task of the worker samples it
at its own interval (`ObservedValues.replace`) and every export reads the last
sample, so the series stays continuous while the database is queried only by
the task. A synchronous gauge would be exported once after each `set()`.
"""

import threading
import time
import weakref
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

if TYPE_CHECKING:
    from sqlalchemy import Engine

_meter = metrics.get_meter("faclab-core", "1.0.0")


class ObservedValues:
    """The last sample of an observable instrument: `(value, attributes)` points
    a periodic task replaces. Past its `max_age` the sample is dropped, so a
    task that stopped running cuts the series instead of freezing it."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._observations: list[Observation] = []
        self._expires_at = 0.0

    def replace(
        self, points: Iterable[tuple[float, Mapping[str, str]]], max_age: float
    ) -> None:
        observations = [Observation(value, dict(attrs)) for value, attrs in points]
        with self._lock:
            self._observations = observations
            self._expires_at = self._clock() + max_age

    def observe(self, _options: CallbackOptions | None = None) -> list[Observation]:
        with self._lock:
            if self._clock() > self._expires_at:
                return []
            return list(self._observations)


# --- Handlers and events ----------------------------------------------------

handler_duration = _meter.create_histogram(
    "handler.duration",
    unit="ms",
    description="Duration of handler execution in milliseconds",
)

handler_invocations = _meter.create_counter(
    "handler.invocations",
    description="Number of handler invocations",
)

handler_errors = _meter.create_counter(
    "handler.errors",
    description=(
        "Number of handler errors, by error.kind: domain (an expected "
        "rejection) or unexpected"
    ),
)

events_published = _meter.create_counter(
    "events.published",
    description="Number of domain events published",
)

event_handler_errors = _meter.create_counter(
    "events.handler_errors",
    description="Number of event handler errors",
)

# --- Messaging (OTel messaging conventions) ----------------------------------

messaging_sent_messages = _meter.create_counter(
    "messaging.client.sent.messages",
    unit="{message}",
    description=(
        "Messages the relay tried to send to Kafka; error.type on the ones that failed"
    ),
)

messaging_process_duration = _meter.create_histogram(
    "messaging.process.duration",
    unit="s",
    description=(
        "Duration of the consumer's handler per Kafka message; error.type when "
        "it failed (it is retried)"
    ),
)

# Sampled by the worker's queue_metrics task, across tenants (S7.1)
outbox_pending_values = ObservedValues()
outbox_oldest_age_values = ObservedValues()
outbox_failed_values = ObservedValues()
dead_letters_pending_values = ObservedValues()

outbox_pending = _meter.create_observable_gauge(
    "faclab.outbox.pending",
    callbacks=[outbox_pending_values.observe],
    unit="{message}",
    description="Outbox messages waiting to be published, by topic",
)

outbox_oldest_age = _meter.create_observable_gauge(
    "faclab.outbox.oldest_age",
    callbacks=[outbox_oldest_age_values.observe],
    unit="s",
    description="Age of the oldest outbox message waiting, by topic (0: none)",
)

outbox_failed = _meter.create_observable_gauge(
    "faclab.outbox.failed",
    callbacks=[outbox_failed_values.observe],
    unit="{message}",
    description="Outbox messages that spent their attempts and wait for a retry",
)

dead_letters_pending = _meter.create_observable_gauge(
    "faclab.dead_letters.pending",
    callbacks=[dead_letters_pending_values.observe],
    unit="{message}",
    description="Kafka messages the consumer kept in dead_letters, by topic",
)

# --- Database pool -----------------------------------------------------------

_engines: "weakref.WeakKeyDictionary[Engine, str]" = weakref.WeakKeyDictionary()


def watch_pool(engine: "Engine", name: str) -> None:
    """Report the connections of this engine's pool under `name`: `request`
    (the units of work: the API's requests, the worker's task scopes), `app`
    or `worker`. A fixed name, never the database URL"""
    _engines[engine] = name


def observe_pools(_options: CallbackOptions | None = None) -> list[Observation]:
    """Used and idle connections per pool name. Pools that don't count their
    connections (SQLite's) are left out"""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for engine, name in list(_engines.items()):
        pool = engine.pool
        checkedout = getattr(pool, "checkedout", None)
        checkedin = getattr(pool, "checkedin", None)
        if not callable(checkedout) or not callable(checkedin):
            continue
        counts[(name, "used")] += checkedout()
        counts[(name, "idle")] += checkedin()
    return [
        Observation(
            value,
            {
                "db.client.connection.pool.name": name,
                "db.client.connection.state": state,
            },
        )
        for (name, state), value in sorted(counts.items())
    ]


db_connection_count = _meter.create_observable_up_down_counter(
    "db.client.connection.count",
    callbacks=[observe_pools],
    unit="{connection}",
    description="Connections of each SQLAlchemy pool, by state (idle, used)",
)

# --- Auth ----------------------------------------------------------------------

LOGIN_RESULTS = ("success", "invalid", "locked", "no_tenant")

login_attempts = _meter.create_counter(
    "faclab.auth.login.attempts",
    unit="{attempt}",
    description=(
        "Login attempts by result: success, invalid (wrong username or "
        "password), locked (refused by the lockout) or no_tenant (right "
        "password, no active tenant)"
    ),
)

# --- Sales and refunds -------------------------------------------------------

sales_confirmed = _meter.create_counter(
    "faclab.sales.confirmed",
    unit="{sale}",
    description="Sales confirmed (committed), by faclab.sale.source (pos, api)",
)

sales_failed = _meter.create_counter(
    "faclab.sales.failed",
    unit="{sale}",
    description=(
        "Sales that could not be confirmed (quick sale, confirm, API sale), by "
        "error.code and faclab.sale.source"
    ),
)

sales_cancelled = _meter.create_counter(
    "faclab.sales.cancelled",
    unit="{sale}",
    description="Confirmed sales voided (committed), by faclab.sale.source",
)

refunds_completed = _meter.create_counter(
    "faclab.refunds.completed",
    unit="{refund}",
    description="Refunds processed (committed), by faclab.sale.source",
)

# --- Inventory ---------------------------------------------------------------

inventory_movements = _meter.create_counter(
    "faclab.inventory.movements",
    unit="{movement}",
    description=(
        "Stock movements written (committed), by faclab.movement.type (in, "
        "out) and faclab.movement.source (the document that moved it)"
    ),
)

stock_rejections = _meter.create_counter(
    "faclab.inventory.stock_rejections",
    unit="{rejection}",
    description=(
        "Attempts to take stock a location doesn't have available "
        "(INSUFFICIENT_STOCK), by faclab.movement.source"
    ),
)

# --- Invoicing and webhooks --------------------------------------------------

# Set by the worker's invoice_reconciliation task after each pass (S4.3)
reconciliation_discrepancy_values = ObservedValues()

reconciliation_discrepancies = _meter.create_observable_gauge(
    "faclab.reconciliation.discrepancies",
    callbacks=[reconciliation_discrepancy_values.observe],
    unit="{discrepancy}",
    description="Open invoice discrepancies of every tenant, by kind (S4.3)",
)

webhook_deliveries = _meter.create_counter(
    "faclab.webhooks.deliveries",
    unit="{delivery}",
    description=(
        "Webhook attempts by result: delivered, retry (it fails and waits for "
        "the next one) or failed (it spent its attempts) (S6.4)"
    ),
)


# --- Counters that start at 0 (S7.6) -----------------------------------------


def initialize_counters() -> None:
    """Export 0 for every series an alert reads with `increase`, as soon as the
    process starts. A series' first point has nothing before it to increase
    from, so without this the first brute-force attempt after a restart would
    not fire the alert. Call it once the meter provider is set."""
    for result in LOGIN_RESULTS:
        login_attempts.add(0, {"result": result})
