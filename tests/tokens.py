"""Tokens for tests that need one faclab-core never issues (no tenant, a role
that doesn't exist): signed like the core does (EdDSA, S6.1), by default with
the development key the local configuration signs with."""

from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.auth.infra.signing_keys import ALGORITHM, development_key, jwt_keys, key_id
from src.auth.infra.token_service import JwtTokenService


def sign_token(
    payload: dict[str, Any],
    key: Ed25519PrivateKey | None = None,
    *,
    kid: str | None = None,
) -> str:
    key = key or development_key()
    return jwt.encode(
        payload,
        key,
        algorithm=ALGORITHM,
        headers={"kid": kid or key_id(key.public_key())},
    )


def token_service() -> JwtTokenService:
    """The token service of the configuration, as the API builds it"""
    return JwtTokenService(jwt_keys())
