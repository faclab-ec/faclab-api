"""The endpoints' secrets, encrypted in the database with the environment's
master key (TARGET_ARCHITECTURE.md §6): Fernet (AES-128-CBC with an
HMAC-SHA256), from `cryptography`.

SECRET_ENCRYPTION_KEYS lists Fernet keys separated by commas (or the file of
SECRET_ENCRYPTION_KEYS_FILE does): the first one encrypts and any of them
decrypts, so the master key is rotated by putting a new one first and keeping
the old one until every secret was encrypted again. Locally, without one, a
fixed development key is used, refused anywhere else.
"""

import base64
import functools
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from wireup import injectable

from config import config
from config.base import BaseConfig
from src.webhooks.app.ports import SecretBox

DEVELOPMENT_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(b"faclab-core development-only secret encryption key").digest()
).decode()


class FernetSecretBox(SecretBox):
    def __init__(self, keys: list[str]):
        if not keys:
            raise RuntimeError("SECRET_ENCRYPTION_KEYS needs at least one key")
        try:
            self._fernet = MultiFernet([Fernet(key.encode()) for key in keys])
        except ValueError:
            raise RuntimeError(
                "SECRET_ENCRYPTION_KEYS holds a key that is not a Fernet key: "
                "generate one with `python -c 'from cryptography.fernet import "
                "Fernet; print(Fernet.generate_key().decode())'`"
            ) from None
        self.keys = keys

    def seal(self, plain: str) -> str:
        return self._fernet.encrypt(plain.encode()).decode()

    def open(self, sealed: str) -> str:
        try:
            return self._fernet.decrypt(sealed.encode()).decode()
        except InvalidToken:
            raise RuntimeError(
                "A webhook secret can't be decrypted with SECRET_ENCRYPTION_KEYS: "
                "the key that encrypted it is missing"
            ) from None

    @classmethod
    def from_config(cls, cfg: BaseConfig) -> "FernetSecretBox":
        """Raises `RuntimeError` naming the variable, never its value, when the
        keys are missing outside local, unreadable or the development one
        outside local"""
        local = cfg.ENVIRONMENT == "local"
        keys = _keys(cfg)
        if not keys:
            if not local:
                raise RuntimeError(
                    "SECRET_ENCRYPTION_KEYS or SECRET_ENCRYPTION_KEYS_FILE is "
                    f"required in {cfg.ENVIRONMENT}"
                )
            keys = [DEVELOPMENT_KEY]
        if not local and DEVELOPMENT_KEY in keys:
            raise RuntimeError(
                f"The development secret encryption key can't be used in "
                f"{cfg.ENVIRONMENT}"
            )
        return cls(keys)


def _keys(cfg: BaseConfig) -> list[str]:
    value: str = cfg.SECRET_ENCRYPTION_KEYS
    path: str = cfg.SECRET_ENCRYPTION_KEYS_FILE
    if value and path:
        raise RuntimeError(
            "Set SECRET_ENCRYPTION_KEYS or SECRET_ENCRYPTION_KEYS_FILE, not both"
        )
    if path:
        try:
            value = Path(path).read_text()
        except OSError as exc:
            raise RuntimeError(
                f"SECRET_ENCRYPTION_KEYS_FILE can't be read: {exc.strerror}"
            ) from None
    return [key.strip() for key in value.replace("\n", ",").split(",") if key.strip()]


@functools.cache
def _box() -> FernetSecretBox:
    return FernetSecretBox.from_config(config)


@injectable(lifetime="singleton")
def secret_box() -> SecretBox:
    return _box()
