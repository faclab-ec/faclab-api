"""The signatures of the webhooks (S6.4): the Standard Webhooks scheme, checked
with the receiver of PUBLIC_API.md §7.2 as it is published."""

import base64
import hashlib
import hmac
import time

from src.webhooks.domain.signing import (
    SECRET_PREFIX,
    new_secret,
    secret_hint,
    secret_key,
    signature,
    signature_header,
)


def verify(secret: bytes, msg_id: str, ts: str, body: bytes, header: str) -> bool:
    """PUBLIC_API.md §7.2, as an integrator copies it"""
    if abs(time.time() - int(ts)) > 300:
        return False
    expected = base64.b64encode(
        hmac.new(secret, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return any(
        hmac.compare_digest(expected, sig.split(",", 1)[1]) for sig in header.split(" ")
    )


def test_the_signature_is_the_one_of_the_standard_webhooks_specification():
    """Its test vector: any of its libraries accepts our messages"""
    assert (
        signature(
            "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw",
            "msg_p5jXN8AQM9LWM0D4loKWxJek",
            1614265330,
            b'{"test": 2432232314}',
        )
        == "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="
    )


def test_a_new_secret_is_whsec_and_32_random_bytes():
    secret = new_secret()

    assert secret.startswith(SECRET_PREFIX)
    assert len(secret_key(secret)) == 32
    assert new_secret() != secret
    assert secret_hint(secret) == secret[:10]


def test_the_published_receiver_accepts_the_message_and_refuses_a_tampered_one():
    secret = new_secret()
    body = b'{"id":"msg_1","type":"sale.confirmed","data":{}}'
    now = int(time.time())
    header = signature_header([secret], "msg_1", now, body)

    assert verify(secret_key(secret), "msg_1", str(now), body, header)
    assert not verify(secret_key(secret), "msg_1", str(now), body + b" ", header)
    assert not verify(secret_key(secret), "msg_2", str(now), body, header)
    assert not verify(secret_key(new_secret()), "msg_1", str(now), body, header)
    # Older than five minutes
    old = now - 301
    assert not verify(
        secret_key(secret),
        "msg_1",
        str(old),
        body,
        signature_header([secret], "msg_1", old, body),
    )


def test_during_a_rotation_both_secrets_sign_and_either_verifies():
    new, previous = new_secret(), new_secret()
    body = b"{}"
    now = int(time.time())
    header = signature_header([new, previous], "msg_1", now, body)

    assert len(header.split(" ")) == 2
    assert all(part.startswith("v1,") for part in header.split(" "))
    assert verify(secret_key(new), "msg_1", str(now), body, header)
    assert verify(secret_key(previous), "msg_1", str(now), body, header)
