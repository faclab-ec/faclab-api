"""Identifiers and secrets of the integration clients (S6.2).

The client_id is public and says the environment (`fl_live_…` in production,
`fl_test_…` in a sandbox). The secret is 256 random bits shown once; only its
SHA-256 is kept. A slow hash (bcrypt, argon2) protects passwords people choose
from a dictionary attack; a random 256-bit secret can't be guessed either way,
and a fast hash keeps the token endpoint from spending CPU on every attempt
(PUBLIC_API.md §3.2).
"""

import hashlib
import hmac
import re
import secrets
from enum import StrEnum

# Visible part of a secret, to tell the client's secrets apart in a listing
SECRET_PREFIX_LENGTH = 6
_PUBLIC_ID = re.compile(r"fl_(live|test)_[0-9a-f]{12}")
# A secret no client has: an unknown client_id is checked against it too
_DECOY_HASH = hashlib.sha256(b"no client has this secret").hexdigest()


class IntegrationEnvironment(StrEnum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"

    @property
    def prefix(self) -> str:
        return "fl_live_" if self is IntegrationEnvironment.PRODUCTION else "fl_test_"


def new_public_id(environment: IntegrationEnvironment) -> str:
    return f"{environment.prefix}{secrets.token_hex(6)}"


def is_public_id(value: str) -> bool:
    return _PUBLIC_ID.fullmatch(value) is not None


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secret_matches(secret: str, secret_hash: str) -> bool:
    """Compares in constant time"""
    return hmac.compare_digest(hash_secret(secret), secret_hash)


def decoy_check(secret: str) -> None:
    """The same work as checking a real secret, for an unknown client"""
    secret_matches(secret, _DECOY_HASH)
