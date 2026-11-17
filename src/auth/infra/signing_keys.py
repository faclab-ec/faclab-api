"""The Ed25519 keys that sign and verify the tokens (S6.1) and their JWKS.

One private key signs; its public key and the ones of `JWT_PUBLIC_KEYS` verify
and are published in `/.well-known/jwks.json`, so other services (faclab-invoicing)
check tokens without holding anything that could issue them. Each key is known
by its `kid`, the RFC 7638 thumbprint of its public JWK: nothing to configure
and two keys never share one, which lets a rotation keep both keys active.
"""

import base64
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from wireup import injectable

from config import config
from config.base import BaseConfig

ALGORITHM = "EdDSA"

_PUBLIC_PEM = re.compile(
    r"-----BEGIN PUBLIC KEY-----.+?-----END PUBLIC KEY-----", re.DOTALL
)

# Signs locally when no key is configured, so tokens survive a reload. Anyone
# can derive it, so any other environment refuses it
_DEVELOPMENT_SEED = hashlib.sha256(b"faclab-core development-only JWT key").digest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def public_jwk(key: Ed25519PublicKey) -> dict[str, str]:
    raw = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}


def key_id(key: Ed25519PublicKey) -> str:
    """RFC 7638 thumbprint: SHA-256 of the key's required members, sorted and
    without whitespace, in base64url"""
    canonical = json.dumps(public_jwk(key), sort_keys=True, separators=(",", ":"))
    return _b64url(hashlib.sha256(canonical.encode("utf-8")).digest())


def development_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_DEVELOPMENT_SEED)


DEVELOPMENT_KID = key_id(development_key().public_key())


class JwtKeys:
    """The key that signs and every key that verifies, by `kid`"""

    def __init__(
        self,
        signing_key: Ed25519PrivateKey,
        public_keys: Iterable[Ed25519PublicKey] = (),
    ):
        self._signing_key = signing_key
        self._signing_kid = key_id(signing_key.public_key())
        # The signing key first: the JWKS lists it before the others
        self._verification: dict[str, Ed25519PublicKey] = {
            self._signing_kid: signing_key.public_key()
        }
        for key in public_keys:
            self._verification.setdefault(key_id(key), key)

    @property
    def signing_key(self) -> Ed25519PrivateKey:
        return self._signing_key

    @property
    def signing_kid(self) -> str:
        return self._signing_kid

    @property
    def kids(self) -> tuple[str, ...]:
        return tuple(self._verification)

    def verification_key(self, kid: str) -> Ed25519PublicKey | None:
        return self._verification.get(kid)

    def jwks(self) -> dict[str, list[dict[str, Any]]]:
        """The public keys as a JWK set (RFC 7517); never the private part"""
        return {
            "keys": [
                {**public_jwk(key), "kid": kid, "alg": ALGORITHM, "use": "sig"}
                for kid, key in self._verification.items()
            ]
        }

    @classmethod
    def from_config(cls, cfg: BaseConfig) -> "JwtKeys":
        """Reads the keys of `JWT_PRIVATE_KEY(_FILE)` and `JWT_PUBLIC_KEYS(_FILE)`.

        Raises `RuntimeError` naming the variable, never its value, when a key
        is missing outside local, unreadable, not Ed25519 or the development one
        outside local."""
        local = cfg.ENVIRONMENT == "local"
        private_pem = _setting(cfg, "JWT_PRIVATE_KEY")
        if private_pem is None:
            if not local:
                raise RuntimeError(
                    "JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_FILE is required in "
                    f"{cfg.ENVIRONMENT}"
                )
            signing_key = development_key()
        else:
            signing_key = _private_key(private_pem)

        public_pem = _setting(cfg, "JWT_PUBLIC_KEYS")
        public_keys = _public_keys(public_pem) if public_pem is not None else []

        keys = cls(signing_key, public_keys)
        if not local and DEVELOPMENT_KID in keys.kids:
            raise RuntimeError(
                f"The development JWT key can't be used in {cfg.ENVIRONMENT}: "
                "generate one with `openssl genpkey -algorithm ed25519`"
            )
        return keys


@injectable(lifetime="singleton")
def jwt_keys() -> JwtKeys:
    return JwtKeys.from_config(config)


def _setting(cfg: BaseConfig, name: str) -> str | None:
    """The PEM of `name`, or of the file `name_FILE` names; None when neither"""
    value: str = getattr(cfg, name)
    path: str = getattr(cfg, f"{name}_FILE")
    if value and path:
        raise RuntimeError(f"Set {name} or {name}_FILE, not both")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            reason = exc.strerror or type(exc).__name__
            raise RuntimeError(f"{name}_FILE can't be read: {reason}") from None
    if value:
        # An environment variable that can't hold newlines carries them as \n
        return value.replace("\\n", "\n")
    return None


def _private_key(pem: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        # The key's text never reaches the message
        raise RuntimeError(
            "JWT_PRIVATE_KEY is not an unencrypted PEM private key (PKCS#8)"
        ) from None
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("JWT_PRIVATE_KEY must be an Ed25519 key")
    return key


def _public_keys(pem: str) -> list[Ed25519PublicKey]:
    blocks = _PUBLIC_PEM.findall(pem)
    if not blocks:
        raise RuntimeError("JWT_PUBLIC_KEYS holds no PEM public key")
    keys = []
    for block in blocks:
        try:
            key = serialization.load_pem_public_key(block.encode("utf-8"))
        except (ValueError, UnsupportedAlgorithm):
            raise RuntimeError("JWT_PUBLIC_KEYS holds an unreadable key") from None
        if not isinstance(key, Ed25519PublicKey):
            raise RuntimeError("JWT_PUBLIC_KEYS must hold Ed25519 keys")
        keys.append(key)
    return keys
