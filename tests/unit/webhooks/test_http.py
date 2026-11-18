"""The webhooks' HTTP client (S6.4) against a local HTTPS receiver."""

import socket
import ssl

from src.webhooks.infra.http import WebhookSender
from src.webhooks.infra.urls import DnsUrlGuard
from tests.webhooks_kit import table_resolver

LOCAL = {"localhost": ["127.0.0.1"]}


def _sender(certificate, timeout=2.0, table=None, allow_private=True, tls=None):
    return WebhookSender(
        DnsUrlGuard(
            resolver=table_resolver(table or LOCAL), allow_private=allow_private
        ),
        timeout=timeout,
        tls=tls or certificate.client_context(),
    )


def test_a_post_reaches_the_receiver_with_its_headers(certificate, receiver):
    result = _sender(certificate).post(
        receiver.url + "?token=abc", {"webhook-id": "msg_1"}, b'{"a":1}'
    )

    assert result.ok and result.status == 204 and result.error is None
    [got] = receiver.received
    assert got.path == "/hooks?token=abc"
    assert got.body == b'{"a":1}'
    assert got.headers["webhook-id"] == "msg_1"
    assert got.headers["content-type"] == "application/json"
    assert got.headers["user-agent"].startswith("Faclab-Webhooks/")
    assert got.headers["host"] == f"localhost:{receiver.port}"


def test_an_error_answer_is_a_failed_attempt(certificate, receiver):
    receiver.status = 500

    result = _sender(certificate).post(receiver.url, {}, b"{}")

    assert (result.ok, result.status, result.error) == (False, 500, "HTTP 500")


def test_a_redirect_is_not_followed(certificate, receiver):
    receiver.status = 302

    result = _sender(certificate).post(receiver.url, {}, b"{}")

    assert (result.ok, result.status) == (False, 302)
    assert len(receiver.received) == 1


def test_a_slow_receiver_runs_out_of_time(certificate, receiver):
    receiver.delay = 1.5

    result = _sender(certificate, timeout=0.5).post(receiver.url, {}, b"{}")

    assert (result.status, result.error) == (None, "timeout")
    assert result.duration_ms < 1400


def test_a_closed_port_is_a_connection_error(certificate):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    result = _sender(certificate).post(f"https://localhost:{port}/hooks", {}, b"{}")

    assert result.status is None
    assert result.error is not None and result.error.startswith("connection error")


def test_a_certificate_the_sender_doesnt_trust_is_refused(certificate, receiver):
    untrusted = ssl.create_default_context()

    result = _sender(certificate, tls=untrusted).post(receiver.url, {}, b"{}")

    assert result.status is None
    assert result.error is not None and result.error.startswith("TLS error")
    assert receiver.received == []


def test_a_name_that_now_resolves_to_a_private_address_is_not_called(
    certificate, receiver
):
    """DNS rebinding: public when registered, local when sent"""
    sender = _sender(
        certificate, table={"hooks.tienda.example": ["127.0.0.1"]}, allow_private=False
    )

    result = sender.post(
        f"https://hooks.tienda.example:{receiver.port}/hooks", {}, b"{}"
    )

    assert result.status is None
    assert result.error == (
        "address not allowed: it resolves to a private or local address"
    )
    assert receiver.received == []


def test_the_connection_goes_to_the_checked_address_with_the_host_s_name(
    certificate, receiver
):
    """Another name resolved by the guard to 127.0.0.1: the TLS name is the
    host's, so a certificate of localhost doesn't do for it"""
    sender = _sender(certificate, table={"otro.example": ["127.0.0.1"]})

    result = sender.post(f"https://otro.example:{receiver.port}/hooks", {}, b"{}")

    assert result.error is not None and result.error.startswith("TLS error")
