from .base import BaseConfig


class DeployedConfig(BaseConfig):
    """Settings for staging and production: no development fallbacks, so a
    missing variable stops the startup instead of running on SQLite or with the
    development signing key."""

    def __init__(self):
        super().__init__()
        # The outbox relay, the invoice consumer and the worker's purges work
        # across tenants, which the API's role can't do under row-level
        # security: without their own role they would silently see nothing
        required = {
            "DATABASE_URL": self.DB_CONNECTION_STRING,
            "DATABASE_URL_WORKER": self.DB_WORKER_URL,
            "CORS_ORIGINS": self.CORS_ORIGINS,
            # The key that signs the tokens (S6.1); JwtKeys checks it is an
            # Ed25519 key and not the development one
            "JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_FILE": (
                self.JWT_PRIVATE_KEY or self.JWT_PRIVATE_KEY_FILE
            ),
        }
        # The master key of the webhooks' secrets (S6.4); FernetSecretBox checks
        # they are Fernet keys and not the development one
        if self.WEBHOOKS_ENABLED:
            required["SECRET_ENCRYPTION_KEYS or SECRET_ENCRYPTION_KEYS_FILE"] = (
                self.SECRET_ENCRYPTION_KEYS or self.SECRET_ENCRYPTION_KEYS_FILE
            )
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"Missing required settings for {self.ENVIRONMENT}: "
                f"{', '.join(missing)}. Set them as environment variables."
            )
        # Quotes go out by email (S5.4): without a server or a sender, sending
        # one would fail on every request instead of at startup
        if self.EMAIL_ENABLED:
            unset = [
                name
                for name, value in (
                    ("SMTP_HOST", self.SMTP_HOST),
                    ("EMAIL_FROM", self.EMAIL_FROM),
                )
                if not value
            ]
            if unset:
                raise RuntimeError(
                    f"EMAIL_ENABLED needs {', '.join(unset)} in {self.ENVIRONMENT}"
                )
        # A webhook towards a private address would let a company make the
        # server call the internal network (SSRF)
        if self.WEBHOOK_ALLOW_PRIVATE_URLS:
            raise RuntimeError(
                f"WEBHOOK_ALLOW_PRIVATE_URLS can't be on in {self.ENVIRONMENT}"
            )
        # The API allows credentials, and with "*" the browser would accept
        # them from any site
        if "*" in self.CORS_ORIGINS:
            raise RuntimeError(
                f"CORS_ORIGINS must list explicit origins in {self.ENVIRONMENT}, not '*'"
            )
