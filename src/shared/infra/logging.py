import logging
import sys

import structlog


def _extract_otel_context(logger, method_name, event_dict):
    record = event_dict.get("_record")
    if record:
        trace_id = getattr(record, "otelTraceID", "0")
        span_id = getattr(record, "otelSpanID", "0")
        if trace_id != "0":
            event_dict["trace_id"] = trace_id
            event_dict["span_id"] = span_id
    return event_dict


# Keys whose value never reaches a log, compared without case, "_" or "-"
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "currentpassword",
        "newpassword",
        "secret",
        "jwtsecret",
        "token",
        "accesstoken",
        "refreshtoken",
        "authorization",
        "cookie",
        "setcookie",
        "apikey",
    }
)
_REDACTED = "[REDACTED]"


def _is_sensitive(key) -> bool:
    return (
        isinstance(key, str)
        and key.lower().replace("_", "").replace("-", "") in _SENSITIVE_KEYS
    )


def _redact(value):
    if isinstance(value, dict):
        return {
            key: _REDACTED if _is_sensitive(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return value


def redact_sensitive(logger, method_name, event_dict):
    """Masks passwords, tokens and secrets in any field of the event, at any
    depth. A minimal net for S1.4; S1.5 completes the redaction policy."""
    return _redact(event_dict)


def configure_logging(log_level: str = "INFO", json_output: bool = False):
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        redact_sensitive,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _extract_otel_context,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    logging.getLogger("opentelemetry.attributes").setLevel(logging.ERROR)
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
