"""The rules of the webhook endpoints and deliveries (S6.4)."""

from datetime import datetime, timedelta

import pytest

from src.auth.domain.scopes import Scope
from src.webhooks.domain.entities import (
    MAX_ATTEMPTS,
    RETRY_SCHEDULE,
    DisabledReason,
    Subscriber,
    WebhookDelivery,
    WebhookDeliveryStatus,
    WebhookEndpoint,
    retry_delay,
    should_disable,
)
from src.webhooks.domain.exceptions import (
    WebhookDeliveryPendingError,
    WebhookEndpointDisabledError,
    WebhookOwnerRequiredError,
)
from src.webhooks.domain.types import REQUIRED_SCOPE, WebhookEventType, missing_scopes

NOW = datetime(2026, 11, 18, 12, 0)
SALE = WebhookEventType.SALE_CONFIRMED
PRODUCT = WebhookEventType.PRODUCT_UPDATED


def _endpoint(**kw) -> WebhookEndpoint:
    endpoint = WebhookEndpoint.new(
        "https://hooks.example/faclab",
        kw.pop("event_types", [SALE]),
        "sealed",
        "whsec_abcd",
        **kw,
    )
    endpoint.id = 1
    return endpoint


def test_the_retry_schedule_is_the_one_of_public_api():
    """5 s, 5 min, 30 min, 2 h, 5 h, 10 h, 24 h, 24 h: about three days"""
    assert [delay.total_seconds() for delay in RETRY_SCHEDULE] == [
        5,
        300,
        1800,
        7200,
        18000,
        36000,
        86400,
        86400,
    ]
    assert MAX_ATTEMPTS == 9
    assert (
        timedelta(days=2, hours=12)
        < sum(RETRY_SCHEDULE, timedelta())
        < timedelta(days=3)
    )
    assert retry_delay(1) == timedelta(seconds=5)
    assert retry_delay(8) == timedelta(hours=24)
    assert retry_delay(9) is None


def test_an_endpoint_is_disabled_only_when_nothing_succeeded_since_the_delivery():
    created = NOW - timedelta(days=3)

    assert should_disable(None, created)
    assert should_disable(created - timedelta(hours=1), created)
    assert not should_disable(created + timedelta(hours=1), created)


def test_an_endpoint_needs_some_event_and_an_owner_to_exclude_its_changes():
    with pytest.raises(ValueError):
        _endpoint(event_types=[])
    with pytest.raises(WebhookOwnerRequiredError):
        _endpoint(exclude_own_changes=True)

    assert _endpoint(exclude_own_changes=True, integration_client_id=7)


def test_disabling_and_enabling_an_endpoint():
    endpoint = _endpoint()
    endpoint.failing_since = NOW

    assert endpoint.disable(DisabledReason.FAILING, NOW)
    assert not endpoint.disable(DisabledReason.MANUAL, NOW)
    assert endpoint.disabled_reason is DisabledReason.FAILING
    with pytest.raises(WebhookEndpointDisabledError):
        endpoint.ensure_active()

    assert endpoint.enable()
    assert not endpoint.enable()
    assert (endpoint.disabled_reason, endpoint.disabled_at) == (None, None)
    assert endpoint.failing_since is None


def test_after_a_rotation_both_secrets_sign_until_the_previous_one_expires():
    endpoint = _endpoint()

    endpoint.rotate("sealed-new", "whsec_wxyz", NOW + timedelta(hours=24))

    assert endpoint.signing_secrets(NOW) == ["sealed-new", "sealed"]
    assert endpoint.signing_secrets(NOW + timedelta(hours=25)) == ["sealed-new"]
    assert endpoint.secret_hint == "whsec_wxyz"


def test_a_delivery_is_resent_with_its_attempts_from_the_start():
    delivery = WebhookDelivery(message_id=1, endpoint_id=1, id=3, attempts=9)
    delivery.status = WebhookDeliveryStatus.FAILED

    delivery.retry(NOW)

    assert delivery.status is WebhookDeliveryStatus.PENDING
    assert (delivery.attempts, delivery.next_attempt_at) == (0, NOW)
    assert delivery.attempts_since == NOW
    with pytest.raises(WebhookDeliveryPendingError):
        delivery.retry(NOW)


def test_the_company_s_endpoint_gets_every_event_it_subscribes_to():
    subscriber = Subscriber(endpoint_id=1, event_types=frozenset({SALE}))

    assert subscriber.wants(SALE, branch_id=None, origin_integration_id=7)
    assert not subscriber.wants(PRODUCT, branch_id=None, origin_integration_id=None)


def test_a_client_s_endpoint_gets_only_what_its_client_may_read():
    subscriber = Subscriber(
        endpoint_id=1,
        event_types=frozenset({SALE, PRODUCT}),
        owner_id=7,
        owner_scopes=frozenset({Scope.SALES_READ}),
        owner_branch_ids=frozenset({12}),
    )

    assert subscriber.wants(SALE, branch_id=12, origin_integration_id=None)
    # Another branch, or a sale without branch (older than S2.6)
    assert not subscriber.wants(SALE, branch_id=15, origin_integration_id=None)
    assert not subscriber.wants(SALE, branch_id=None, origin_integration_id=None)
    # Without products:read
    assert not subscriber.wants(PRODUCT, branch_id=None, origin_integration_id=None)


def test_exclude_own_changes_skips_what_its_client_caused():
    subscriber = Subscriber(
        endpoint_id=1,
        event_types=frozenset({SALE}),
        exclude_own_changes=True,
        owner_id=7,
        owner_scopes=frozenset({Scope.SALES_READ}),
    )

    assert not subscriber.wants(SALE, branch_id=12, origin_integration_id=7)
    assert subscriber.wants(SALE, branch_id=12, origin_integration_id=8)
    assert subscriber.wants(SALE, branch_id=12, origin_integration_id=None)


def test_every_event_needs_a_read_scope():
    assert set(REQUIRED_SCOPE) == set(WebhookEventType)
    assert missing_scopes(
        frozenset({SALE, PRODUCT}), frozenset({Scope.SALES_READ})
    ) == ["products:read"]
