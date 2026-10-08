import inspect
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import structlog
from opentelemetry import trace

from src.shared.domain.events import DomainEvent
from src.shared.infra.telemetry_instruments import (
    event_handler_errors,
    events_published,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class EventBus:
    _subscribers: dict[type[DomainEvent], list[Callable]] = defaultdict(list)
    _accepts_session: dict[int, bool] = {}

    @classmethod
    def subscribe(cls, event_type: type[DomainEvent], handler: Callable) -> None:
        cls._subscribers[event_type].append(handler)
        try:
            sig = inspect.signature(handler)
            cls._accepts_session[id(handler)] = "session" in sig.parameters
        except (ValueError, TypeError):
            cls._accepts_session[id(handler)] = False

    @classmethod
    def publish(cls, event: DomainEvent, session: Any = None) -> None:
        event_type = type(event)
        event_type_name = event_type.__name__
        handlers = cls._subscribers.get(event_type, [])

        with tracer.start_as_current_span(
            f"event.publish.{event_type_name}",
            attributes={
                "event.type": event_type_name,
                "event.handler_count": len(handlers),
            },
        ):
            logger.info(
                "event_published",
                event_type=event_type_name,
                handler_count=len(handlers),
            )
            events_published.add(1, {"event.type": event_type_name})

            for handler in handlers:
                handler_name = getattr(handler, "__name__", repr(handler))
                with tracer.start_as_current_span(
                    f"event.handle.{handler_name}",
                    attributes={
                        "event.type": event_type_name,
                        "event.handler": handler_name,
                    },
                ) as span:
                    try:
                        if cls._accepts_session.get(id(handler), False):
                            handler(event, session=session)
                        else:
                            handler(event)
                        span.set_status(trace.StatusCode.OK)
                    except Exception as e:
                        logger.error(
                            "event_handler_error",
                            handler=handler_name,
                            event_type=event_type_name,
                            error=str(e),
                        )
                        event_handler_errors.add(
                            1,
                            {
                                "event.type": event_type_name,
                                "event.handler": handler_name,
                            },
                        )
                        span.set_status(trace.StatusCode.ERROR, str(e))
                        span.record_exception(e)
                        raise

    @classmethod
    def clear(cls) -> None:
        cls._subscribers.clear()
        cls._accepts_session.clear()
