from .base import BaseConfig, env

_DEV_JWT_SECRET = "dev-only-change-me"
_MIN_JWT_SECRET_LENGTH = 32


class DeployedConfig(BaseConfig):
    """Settings for staging and production: no development fallbacks, so a
    missing variable stops the startup instead of running on SQLite or with the
    development secret."""

    JWT_SECRET = env.str("JWT_SECRET", "")

    def __init__(self):
        required = {
            "DATABASE_URL": self.DB_CONNECTION_STRING,
            "CORS_ORIGINS": self.CORS_ORIGINS,
            "JWT_SECRET": self.JWT_SECRET,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"Missing required settings for {self.ENVIRONMENT}: "
                f"{', '.join(missing)}. Set them as environment variables."
            )
        if (
            self.JWT_SECRET == _DEV_JWT_SECRET
            or len(self.JWT_SECRET) < _MIN_JWT_SECRET_LENGTH
        ):
            raise RuntimeError(
                "JWT_SECRET must be unique and at least "
                f"{_MIN_JWT_SECRET_LENGTH} characters in {self.ENVIRONMENT}"
            )
        # The API allows credentials, and with "*" the browser would accept
        # them from any site
        if "*" in self.CORS_ORIGINS:
            raise RuntimeError(
                f"CORS_ORIGINS must list explicit origins in {self.ENVIRONMENT}, not '*'"
            )
