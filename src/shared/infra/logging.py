import logging
import re
import sys

import structlog
from opentelemetry import trace


def add_trace_context(logger, method_name, event_dict):
    """Correlates the log with its trace: ids of the span active when the log
    was written (the request, command, query or Kafka message)."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


_EVENT_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")


def add_event_name(logger, method_name, event_dict):
    """Stable `event.name` to search logs by: `outbox_publish_failed` becomes
    `outbox.publish.failed`. A log from another library (uvicorn, aiokafka)
    carries free text, so it takes the name of its logger."""
    event = event_dict.get("event")
    if isinstance(event, str) and _EVENT_IDENTIFIER.fullmatch(event):
        name = event.replace("_", ".")
    else:
        name = event_dict.get("logger") or "log"
    event_dict.setdefault("event.name", name)
    return event_dict


def service_fields(fields: dict[str, str]):
    """Processor that stamps the service on every line. Only for JSON output:
    OTLP logs already carry it in their resource, and the local console would
    repeat it on every line."""

    def add_service_fields(logger, method_name, event_dict):
        for key, value in fields.items():
            event_dict.setdefault(key, value)
        return event_dict

    return add_service_fields


# Keys whose value never reaches a log, compared without case, "_" or "-"
# (docs/architecture/OBSERVABILITY.md §4.6)
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "currentpassword",
        "newpassword",
        "secret",
        "jwtsecret",
        "clientsecret",
        "token",
        "accesstoken",
        "refreshtoken",
        "authorization",
        "cookie",
        "setcookie",
        "apikey",
        "p12",
        "certificate",
        "privatekey",
        "xml",
        "signature",
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
    """Masks passwords, tokens, secrets, certificates and signed XML in any
    field of the event, at any depth."""
    return _redact(event_dict)


def configure_logging(
    log_level: str = "INFO",
    json_output: bool = False,
    service_name: str | None = None,
    service_version: str | None = None,
    environment: str | None = None,
):
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        add_trace_context,
        add_event_name,
        # Last, so nothing added above escapes it
        redact_sensitive,
    ]

    if json_output:
        service = {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment.name": environment,
        }
        render = [
            service_fields({k: v for k, v in service.items() if v}),
            # JSONRenderer only prints `exc_info: true`; this adds the traceback
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        render = [structlog.dev.ConsoleRenderer()]

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
            *render,
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
