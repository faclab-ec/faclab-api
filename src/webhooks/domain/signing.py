"""Signatures of the Standard Webhooks specification (ADR-0009): an HMAC-SHA256
of `"{webhook-id}.{webhook-timestamp}.{body}"` with the endpoint's secret, in
base64, as `v1,<signature>`. During a rotation the header carries the
signatures of both secrets separated by a space; the receiver accepts the
message when one of them matches."""

import base64
import hashlib
import hmac
import secrets
from collections.abc import Iterable

SECRET_PREFIX = "whsec_"
SECRET_BYTES = 32
# What the listings show of a secret: the prefix and four characters
HINT_LENGTH = len(SECRET_PREFIX) + 4


def new_secret() -> str:
    """`whsec_` and 32 random bytes in base64, like the Standard Webhooks
    libraries expect"""
    return SECRET_PREFIX + base64.b64encode(secrets.token_bytes(SECRET_BYTES)).decode()


def secret_key(secret: str) -> bytes:
    """The bytes the HMAC is computed with: the base64 after the prefix"""
    return base64.b64decode(secret.removeprefix(SECRET_PREFIX))


def secret_hint(secret: str) -> str:
    return secret[:HINT_LENGTH]


def signature(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(
        secret_key(secret),
        f"{message_id}.{timestamp}.".encode() + body,
        hashlib.sha256,
    ).digest()
    return "v1," + base64.b64encode(digest).decode()


def signature_header(
    secrets_: Iterable[str], message_id: str, timestamp: int, body: bytes
) -> str:
    """The `webhook-signature` header: one signature per active secret"""
    return " ".join(signature(s, message_id, timestamp, body) for s in secrets_)
