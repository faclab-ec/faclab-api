"""The worker's sending of the webhooks (S6.4, ADR-0009).

A thread of its own polls every WEBHOOK_POLL_INTERVAL_SECONDS and sends in a
pool of WEBHOOK_CONCURRENCY threads, as faclab_worker (across tenants):

1. **Claim**, in a short transaction under an advisory lock: the oldest due
   delivery of each active endpoint that has none on its way, locked with
   SKIP LOCKED. Its lease (`locked_until`, the timeout plus a margin) keeps
   every other delivery of that endpoint waiting: one at a time per endpoint,
   so a slow receiver only holds back its own deliveries. Its attempt is
   counted here, so a worker that dies mid-send doesn't retry it forever.
2. **Send** without a transaction open: the body as stored, signed with the
   endpoint's secrets (both during a rotation), with WEBHOOK_TIMEOUT_SECONDS.
3. **Record** in another transaction: a 2xx is delivered; anything else
   waits for its next attempt of the schedule (5 s … 24 h, PUBLIC_API.md §7.2)
   or, the nine spent, is failed. A delivery that spends them without the
   endpoint answering any since it was created disables the endpoint, which
   is audited, logged and told to the company's administrators.

WEBHOOK_DELIVERY_ENABLED=false doesn't start it: the deliveries wait, pending.
"""

import json
import threading
import time
import zlib
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import structlog
from opentelemetry import trace
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from src.shared.domain.tenant import TenantContext, TenantSource
from src.shared.infra.events.scope import create_sync_scope
from src.shared.infra.telemetry_instruments import webhook_deliveries
from src.webhooks.app.commands.endpoints import (
    DisableFailingWebhookEndpointCommand,
    DisableFailingWebhookEndpointCommandHandler,
)
from src.webhooks.app.ports import SecretBox
from src.webhooks.app.views import url_host
from src.webhooks.domain.entities import (
    WebhookDeliveryStatus,
    WebhookEndpointStatus,
    retry_delay,
    should_disable,
)
from src.webhooks.domain.signing import signature_header
from src.webhooks.infra.http import SendResult, WebhookSender
from src.webhooks.infra.models import (
    WebhookDeliveryModel,
    WebhookEndpointModel,
    WebhookMessageModel,
)
from src.webhooks.infra.repositories import pending_criteria

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# One claimer at a time, across processes
DISPATCHER_LOCK_KEY = zlib.crc32(b"faclab.webhook_dispatcher")
LEASE_MARGIN = timedelta(seconds=30)

Delivery = WebhookDeliveryModel
Endpoint = WebhookEndpointModel
Message = WebhookMessageModel


@dataclass(frozen=True)
class Claim:
    delivery_id: int
    endpoint_id: int
    tenant_id: UUID


@dataclass(frozen=True)
class Outcome:
    delivery_id: int
    endpoint_id: int
    # delivered, pending (it waits for its next attempt) or failed
    status: str
    result: SendResult
    disabled: bool = False


# tenant, endpoint id -> the endpoint described, or None when it was disabled
# already
Disabler = Callable[[UUID, int], dict | None]
Notifier = Callable[[UUID, dict], object]


def disable_failing_endpoint(tenant_id: UUID, endpoint_id: int) -> dict | None:
    """In the tenant's context (its audit log), as a task"""
    with create_sync_scope(tenant=TenantContext(tenant_id, TenantSource.TASK)) as scope:
        return scope.get(DisableFailingWebhookEndpointCommandHandler).handle(
            DisableFailingWebhookEndpointCommand(endpoint_id=endpoint_id)
        )


def _take_lock(session: Session) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": DISPATCHER_LOCK_KEY},
        )
    )


def body_of(payload: dict) -> bytes:
    """The bytes that are signed and sent: the same in every attempt"""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


class WebhookDispatcher:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        sender: WebhookSender,
        box: SecretBox,
        concurrency: int = 8,
        poll_interval: float = 1.0,
        clock: Callable[[], datetime] = datetime.now,
        epoch: Callable[[], float] = time.time,
        disabler: Disabler = disable_failing_endpoint,
        notifier: Notifier | None = None,
        on_cycle: Callable[[], None] | None = None,
    ):
        self._session_factory = session_factory
        self._sender = sender
        self._box = box
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._clock = clock
        self._epoch = epoch
        self._disabler = disabler
        self._notifier = notifier
        self._on_cycle = on_cycle
        self._lease = timedelta(seconds=sender.timeout) + LEASE_MARGIN
        # The endpoints this process is sending to now
        self._in_flight: set[int] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool: ThreadPoolExecutor | None = None

    # The worker's service

    def start(self) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=self._concurrency, thread_name_prefix="webhook-send"
        )
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="webhook-dispatcher"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stops claiming and waits for the attempts on their way (each one ends
        within its timeout)"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        if self._pool is not None:
            self._pool.shutdown(wait=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.dispatch()
            except Exception:
                logger.exception("webhook_dispatcher_error")
            else:
                if self._on_cycle is not None:
                    self._on_cycle()
            self._stop.wait(timeout=self._poll_interval)

    def dispatch(self) -> list[Future[Outcome | None]]:
        """One poll: claims what the free threads can send and sends it in the
        pool; the attempts on their way"""
        if self._pool is None:
            raise RuntimeError("the dispatcher is not started")
        with self._lock:
            free = self._concurrency - len(self._in_flight)
        if free <= 0:
            return []
        futures = []
        for claim in self.claim(free):
            with self._lock:
                self._in_flight.add(claim.endpoint_id)
            future = self._pool.submit(self._deliver_safely, claim)
            future.add_done_callback(
                lambda _, endpoint_id=claim.endpoint_id: self._release(endpoint_id)
            )
            futures.append(future)
        return futures

    def run_once(self) -> list[Outcome]:
        """Claims and sends in this thread, one after another (tests, a CLI)"""
        outcomes = []
        for claim in self.claim(self._concurrency):
            outcome = self.deliver(claim)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    def _release(self, endpoint_id: int) -> None:
        with self._lock:
            self._in_flight.discard(endpoint_id)

    def _deliver_safely(self, claim: Claim) -> Outcome | None:
        try:
            return self.deliver(claim)
        except Exception:
            # Its lease expires and it is claimed again with its next attempt
            logger.exception(
                "webhook_delivery_error",
                delivery_id=claim.delivery_id,
                endpoint_id=claim.endpoint_id,
            )
            return None

    # 1. Claim

    def claim(self, limit: int) -> list[Claim]:
        now = self._clock()
        with self._session_factory() as session:
            if not _take_lock(session):
                return []
            busy = select(Delivery.endpoint_id).where(
                Delivery.locked_until.is_not(None), Delivery.locked_until > now
            )
            # The oldest due delivery first: the endpoints in that order
            endpoints = session.execute(
                select(Delivery.endpoint_id)
                .join(
                    Endpoint,
                    (Endpoint.id == Delivery.endpoint_id)
                    & (Endpoint.tenant_id == Delivery.tenant_id),
                )
                .where(
                    *pending_criteria(now),
                    Endpoint.status == WebhookEndpointStatus.ACTIVE.value,
                    Delivery.endpoint_id.not_in(busy),
                )
                .group_by(Delivery.endpoint_id)
                .order_by(func.min(Delivery.id))
                .limit(limit)
            ).scalars()
            claims = []
            for endpoint_id in list(endpoints):
                delivery = session.scalars(
                    select(Delivery)
                    .where(Delivery.endpoint_id == endpoint_id, *pending_criteria(now))
                    .order_by(Delivery.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                ).first()
                if delivery is None:
                    continue
                delivery.locked_until = now + self._lease
                delivery.attempts += 1
                delivery.last_attempt_at = now
                claims.append(Claim(delivery.id, endpoint_id, delivery.tenant_id))
            session.commit()
        return claims

    # 2. Send

    def deliver(self, claim: Claim) -> Outcome | None:
        with self._session_factory() as session:
            row = session.execute(
                select(
                    Message.public_id,
                    Message.event_type,
                    Message.payload,
                    Endpoint.url,
                    Endpoint.secret_ciphertext,
                    Endpoint.previous_secret_ciphertext,
                    Endpoint.previous_secret_expires_at,
                    Delivery.attempts,
                )
                .select_from(Delivery)
                .join(Message, Message.id == Delivery.message_id)
                .join(Endpoint, Endpoint.id == Delivery.endpoint_id)
                .where(Delivery.id == claim.delivery_id)
            ).first()
        if row is None:
            # Its endpoint was deleted meanwhile
            return None
        sealed = [row.secret_ciphertext]
        expires = row.previous_secret_expires_at
        if row.previous_secret_ciphertext and expires and expires > self._clock():
            sealed.append(row.previous_secret_ciphertext)
        body = body_of(row.payload)
        timestamp = int(self._epoch())
        headers = {
            "webhook-id": row.public_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": signature_header(
                [self._box.open(secret) for secret in sealed],
                row.public_id,
                timestamp,
                body,
            ),
        }
        with tracer.start_as_current_span(
            "webhook.deliver",
            kind=trace.SpanKind.CLIENT,
            attributes={
                "faclab.webhook.event_type": row.event_type,
                "faclab.webhook.endpoint_id": claim.endpoint_id,
                "faclab.tenant.id": str(claim.tenant_id),
                "server.address": url_host(row.url),
                # This attempt's number: claim() counted it
                "faclab.retry.attempt": row.attempts,
            },
        ) as span:
            result = self._sender.post(row.url, headers, body)
            if result.status is not None:
                span.set_attribute("http.response.status_code", result.status)
            if not result.ok:
                span.set_status(trace.Status(trace.StatusCode.ERROR, result.error))
            # Inside the span, so the log of the result carries its trace
            return self._record(claim, result, row.event_type, row.url)

    # 3. Record

    def _record(
        self, claim: Claim, result: SendResult, event_type: str, url: str
    ) -> Outcome | None:
        now = self._clock()
        exhausted = False
        with self._session_factory() as session:
            delivery = session.get(Delivery, claim.delivery_id, with_for_update=True)
            if delivery is None:
                return None
            delivery.locked_until = None
            delivery.response_status = result.status
            delivery.duration_ms = result.duration_ms
            # The endpoint's columns one by one: its updatedAt is its settings'
            endpoint = update(Endpoint).where(Endpoint.id == claim.endpoint_id)
            if result.ok:
                delivery.status = WebhookDeliveryStatus.DELIVERED.value
                delivery.delivered_at = now
                delivery.next_attempt_at = None
                delivery.last_error = None
                session.execute(
                    endpoint.values(
                        last_success_at=now,
                        failing_since=None,
                        updated_at=Endpoint.updated_at,
                    )
                )
            else:
                delivery.last_error = (result.error or "")[:500]
                delay = retry_delay(delivery.attempts)
                if delay is None:
                    delivery.status = WebhookDeliveryStatus.FAILED.value
                    delivery.next_attempt_at = None
                    exhausted = True
                else:
                    delivery.next_attempt_at = now + delay
                session.execute(
                    endpoint.where(Endpoint.failing_since.is_(None)).values(
                        failing_since=now, updated_at=Endpoint.updated_at
                    )
                )
            disable = exhausted and should_disable(
                session.scalar(
                    select(Endpoint.last_success_at).where(
                        Endpoint.id == claim.endpoint_id
                    )
                ),
                delivery.retried_at or delivery.created_at,
            )
            status, attempts = delivery.status, delivery.attempts
            session.commit()

        outcome = "delivered" if result.ok else ("failed" if exhausted else "retry")
        webhook_deliveries.add(1, {"result": outcome})
        log = logger.info if result.ok else logger.warning
        log(
            f"webhook_{outcome}",
            delivery_id=claim.delivery_id,
            endpoint_id=claim.endpoint_id,
            tenant_id=str(claim.tenant_id),
            event_type=event_type,
            host=url_host(url),
            attempts=attempts,
            response_status=result.status,
            error=result.error,
            duration_ms=result.duration_ms,
        )
        disabled = disable and self._disable(claim, url)
        return Outcome(claim.delivery_id, claim.endpoint_id, status, result, disabled)

    def _disable(self, claim: Claim, url: str) -> bool:
        endpoint = self._disabler(claim.tenant_id, claim.endpoint_id)
        if endpoint is None:
            return False
        logger.error(
            "webhook_endpoint_disabled",
            hint=(
                f"Webhook endpoint {claim.endpoint_id} answered no delivery for "
                "about three days and was disabled; its pending deliveries wait "
                "until it is enabled again"
            ),
            endpoint_id=claim.endpoint_id,
            tenant_id=str(claim.tenant_id),
            host=url_host(url),
        )
        if self._notifier is not None:
            self._notifier(claim.tenant_id, endpoint)
        return True


def create_dispatcher(on_cycle: Callable[[], None] | None = None) -> WebhookDispatcher:
    """The worker's, from the settings"""
    from config import config
    from src.shared.infra.database import worker_session_maker
    from src.shared.infra.mail import mailer
    from src.webhooks.infra.notifications import DisabledEndpointNotifier
    from src.webhooks.infra.secrets import secret_box
    from src.webhooks.infra.urls import DnsUrlGuard

    session_maker = worker_session_maker()
    return WebhookDispatcher(
        session_maker,
        WebhookSender(
            DnsUrlGuard(allow_private=config.WEBHOOK_ALLOW_PRIVATE_URLS),
            timeout=config.WEBHOOK_TIMEOUT_SECONDS,
        ),
        secret_box(),
        concurrency=config.WEBHOOK_CONCURRENCY,
        poll_interval=config.WEBHOOK_POLL_INTERVAL_SECONDS,
        notifier=DisabledEndpointNotifier(session_maker, mailer()),
        on_cycle=on_cycle,
    )
