from dataclasses import dataclass

import pytest
from opentelemetry.trace import StatusCode

from src.shared.app.commands import Command, CommandHandler
from src.shared.app.queries import Query, QueryHandler
from src.shared.domain.exceptions import NotFoundError


@dataclass
class CreateOrder(Command):
    product_id: int
    quantity: int


class CreateOrderHandler(CommandHandler[CreateOrder, int]):
    def _handle(self, command: CreateOrder) -> int:
        return command.product_id * command.quantity


def test_command_handler():
    handler = CreateOrderHandler()
    result = handler.handle(CreateOrder(product_id=5, quantity=3))
    assert result == 15


@dataclass
class GetOrder(Query):
    order_id: int


class MissingOrderHandler(QueryHandler[GetOrder, dict]):
    def _handle(self, query: GetOrder) -> dict:
        raise NotFoundError(f"Order {query.order_id} not found")


class BrokenOrderHandler(CommandHandler[CreateOrder, int]):
    def _handle(self, command: CreateOrder) -> int:
        raise ConnectionError("database is down")


def test_a_domain_error_is_a_warning_not_a_failed_span(span_exporter, json_logs):
    with pytest.raises(NotFoundError):
        MissingOrderHandler().handle(GetOrder(order_id=9))

    (span,) = span_exporter.get_finished_spans()
    assert span.name == "query.GetOrder"
    assert span.status.status_code == StatusCode.UNSET
    assert span.attributes is not None
    assert span.attributes["faclab.error.code"] == "NOT_FOUND"
    assert span.events == ()
    line = next(line for line in json_logs() if line["event"] == "query_rejected")
    assert line["level"] == "warning"
    assert line["error_code"] == "NOT_FOUND"


def test_an_unexpected_error_fails_the_span(span_exporter, json_logs):
    with pytest.raises(ConnectionError):
        BrokenOrderHandler().handle(CreateOrder(product_id=1, quantity=1))

    (span,) = span_exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert [event.name for event in span.events] == ["exception"]
    line = next(line for line in json_logs() if line["event"] == "command_failed")
    assert line["level"] == "error"
