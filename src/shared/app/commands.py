import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

import structlog
from opentelemetry import trace

from src.shared.domain.exceptions import BaseError
from src.shared.infra.telemetry_instruments import (
    handler_duration,
    handler_errors,
    handler_invocations,
)

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class Command:
    pass


TCommand = TypeVar("TCommand", bound=Command)
TResult = TypeVar("TResult")


class CommandHandler(Generic[TCommand, TResult], ABC):
    def handle(self, command: TCommand) -> TResult:
        command_name = type(command).__name__
        handler_name = type(self).__name__
        attributes = {
            "handler.type": "command",
            "handler.name": handler_name,
            "command.name": command_name,
        }

        # The status is set below: a domain error is an expected outcome, not
        # a failure of the system
        with tracer.start_as_current_span(
            f"command.{command_name}",
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            logger.info(
                "command_started",
                command=command_name,
                handler=handler_name,
            )
            handler_invocations.add(1, attributes)
            start = time.perf_counter()
            try:
                result = self._handle(command)
                elapsed = time.perf_counter() - start
                elapsed_ms = round(elapsed * 1000, 2)
                logger.info(
                    "command_completed",
                    command=command_name,
                    handler=handler_name,
                    duration_ms=elapsed_ms,
                )
                handler_duration.record(elapsed_ms, attributes)
                span.set_status(trace.StatusCode.OK)
                return result
            except BaseError as exc:
                elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                logger.warning(
                    "command_rejected",
                    command=command_name,
                    handler=handler_name,
                    error_code=exc.error_code,
                    error_type=type(exc).__name__,
                    duration_ms=elapsed_ms,
                )
                handler_errors.add(1, {**attributes, "error.kind": "domain"})
                handler_duration.record(elapsed_ms, attributes)
                span.set_attribute("faclab.error.code", exc.error_code)
                raise
            except Exception as exc:
                elapsed = time.perf_counter() - start
                elapsed_ms = round(elapsed * 1000, 2)
                logger.error(
                    "command_failed",
                    command=command_name,
                    handler=handler_name,
                    error=str(exc),
                    error_type=type(exc).__name__,
                    duration_ms=elapsed_ms,
                )
                handler_errors.add(1, {**attributes, "error.kind": "unexpected"})
                handler_duration.record(elapsed_ms, attributes)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise

    @abstractmethod
    def _handle(self, command: TCommand) -> TResult:
        raise NotImplementedError
