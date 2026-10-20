from .base import BaseConfig, env


class Config(BaseConfig):
    LOG_LEVEL = env("LOG_LEVEL", "DEBUG")
    DB_CONNECTION_STRING = env.str("DATABASE_URL", "sqlite:///./warehouse.db")
    CORS_ORIGINS: list[str] = env.list(
        "CORS_ORIGINS", ["http://localhost:3000", "http://localhost:5173"]
    )
    DOCS_ENABLED = env.bool("DOCS_ENABLED", True)
    # The web doesn't send the POS headers yet (S2.9)
    POS_TERMINAL_FALLBACK = env.bool("POS_TERMINAL_FALLBACK", True)
    # Local runs over plain HTTP, also towards the SigNoz collector
    AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", False)
    OTEL_EXPORTER_OTLP_INSECURE = env.bool("OTEL_EXPORTER_OTLP_INSECURE", True)
