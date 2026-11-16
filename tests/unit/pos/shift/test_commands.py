from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.organization.domain.entities import Branch
from src.pos.shift.app.commands.close_shift import (
    CloseShiftCommand,
    CloseShiftCommandHandler,
)
from src.pos.shift.app.commands.open_shift import (
    OpenShiftCommand,
    OpenShiftCommandHandler,
)
from src.pos.shift.domain.closing import ItemSold, MethodTotal, ShiftTotals
from src.pos.shift.domain.entities import Shift, ShiftStatus
from src.pos.shift.domain.events import ShiftClosed
from src.pos.shift.domain.exceptions import (
    ClosingCountMissingError,
    ClosingJustificationRequiredError,
    ShiftAlreadyClosedError,
    ShiftAlreadyOpenError,
)
from src.shared.app.audit import AuditAction
from src.shared.domain.exceptions import NotFoundError
from tests.audit import FakeAuditTrail
from tests.unit.pos.closings import FakeShiftTotals, InMemoryShiftClosings, make_closing
from tests.unit.pos.terminals import AT_TERMINAL, TERMINAL, terminal_resolver


def _make_shift(**overrides) -> Shift:
    defaults: dict[str, Any] = {
        "id": 1,
        "cashier_name": "Juan",
        "opening_balance": Decimal("500.00"),
        "status": ShiftStatus.OPEN,
    }
    defaults.update(overrides)
    return Shift(**defaults)


def _mock_repo(entity=None):
    repo = MagicMock()
    if entity is not None:
        repo.create.return_value = entity
        repo.update.return_value = entity
        repo.get_by_id.return_value = entity
        repo.first.return_value = entity
    else:
        repo.first.return_value = None
        repo.get_by_id.return_value = None
    return repo


# --- OpenShift ---


def test_open_shift_command_handler():
    """Test abrir un turno exitosamente"""
    repo = _mock_repo()
    repo.create.side_effect = lambda shift: replace(shift, id=1)
    event_publisher = MagicMock()
    resolver = terminal_resolver()
    handler = OpenShiftCommandHandler(repo, resolver, event_publisher, FakeAuditTrail())

    command = OpenShiftCommand(
        terminal=AT_TERMINAL,
        cashier_name="Juan",
        user_id=9,
        opening_balance=Decimal("500.00"),
    )
    result = handler.handle(command)

    resolver.terminal.assert_called_once_with(AT_TERMINAL)
    repo.first.assert_called_once_with(terminal_id=TERMINAL.id, status="OPEN")
    created = repo.create.call_args.args[0]
    assert (created.terminal_id, created.branch_id) == (TERMINAL.id, 1)
    assert created.opened_by_user_id == 9
    assert result["cashier_name"] == "Juan"
    assert result["status"] == "OPEN"


def test_open_shift_publishes_event():
    """Test que abrir un turno publica evento"""
    from src.pos.shift.domain.events import ShiftOpened

    shift = _make_shift(terminal_id=TERMINAL.id)
    repo = _mock_repo()
    repo.create.return_value = shift
    event_publisher = MagicMock()
    handler = OpenShiftCommandHandler(
        repo, terminal_resolver(), event_publisher, FakeAuditTrail()
    )

    handler.handle(
        OpenShiftCommand(
            terminal=AT_TERMINAL, cashier_name="Juan", opening_balance=Decimal("500.00")
        )
    )

    event_publisher.publish.assert_called_once()
    published_event = event_publisher.publish.call_args[0][0]
    assert isinstance(published_event, ShiftOpened)
    assert published_event.shift_id == 1
    assert published_event.terminal_id == TERMINAL.id
    assert published_event.cashier_name == "Juan"


def test_open_shift_fails_if_already_open():
    """Test que falla si la terminal ya tiene un turno abierto"""
    existing_shift = _make_shift()
    repo = _mock_repo(entity=existing_shift)
    handler = OpenShiftCommandHandler(
        repo, terminal_resolver(), MagicMock(), FakeAuditTrail()
    )

    command = OpenShiftCommand(
        terminal=AT_TERMINAL,
        cashier_name="Maria",
        opening_balance=Decimal("300.00"),
    )

    with pytest.raises(ShiftAlreadyOpenError):
        handler.handle(command)


# --- CloseShift ---


def _cash_sales(amount: str, card: str | None = None) -> ShiftTotals:
    """A shift that sold `amount` in cash and, optionally, `card` by card"""
    payments = [MethodTotal("CASH", 1, Decimal(amount))]
    if card is not None:
        payments.append(MethodTotal("CREDIT_CARD", 1, Decimal(card)))
    total = sum((p.total for p in payments), Decimal("0"))
    return ShiftTotals(
        sales_count=len(payments),
        sales_subtotal=total,
        sales_total=total,
        payments=payments,
        items_sold=[ItemSold("Martillo", "MAR-01", Decimal("2"), total)],
    )


class _Closer:
    def __init__(
        self,
        shift: Shift | None = None,
        totals: ShiftTotals | None = None,
        closings: InMemoryShiftClosings | None = None,
    ):
        self.repo = _mock_repo(entity=shift)
        self.repo.first_for_update.return_value = shift
        self.closings = closings or InMemoryShiftClosings()
        self.event_publisher = MagicMock()
        self.audit = FakeAuditTrail()
        terminals = MagicMock()
        terminals.get_by_id.return_value = TERMINAL
        branches = MagicMock()
        branches.get_by_id.return_value = Branch(
            id=1, establishment_code="001", name="Matriz"
        )
        self.handler = CloseShiftCommandHandler(
            self.repo,
            self.closings,
            FakeShiftTotals(totals),
            terminals,
            branches,
            self.event_publisher,
            self.audit,
        )

    def close(self, *counts: tuple, **kwargs) -> dict:
        command = CloseShiftCommand(
            shift_id=1,
            counts=[
                {
                    "payment_method": method,
                    "counted": Decimal(counted),
                    "justification": rest[0] if rest else None,
                }
                for method, counted, *rest in counts
            ],
            justification_threshold=Decimal("1.00"),
            **kwargs,
        )
        return self.handler.handle(command)


def _open_at_terminal(**overrides) -> Shift:
    return _make_shift(terminal_id=TERMINAL.id, branch_id=1, **overrides)


def test_closing_writes_its_numbered_z_closing():
    closer = _Closer(_open_at_terminal(), _cash_sales("100.00", card="40.00"))

    result = closer.close(
        ("CASH", "600.00"),
        ("CREDIT_CARD", "40.00"),
        closed_by="Maria",
        closed_by_user_id=9,
    )

    # Locked before reading what it moved
    closer.repo.first_for_update.assert_called_once_with(id=1)
    [closing] = closer.closings.closings
    assert (closing.number, closing.sequence) == ("Z-001-CAJA-01-000001", 1)
    assert (closing.closed_by, closing.closed_by_user_id) == ("Maria", 9)
    assert closing.sales_total == Decimal("140.00")
    assert closing.cash_sales == Decimal("100.00")
    assert closing.justification_threshold == Decimal("1.00")
    assert [i.product_name for i in closing.items_sold] == ["Martillo"]
    assert [
        (str(line.payment_method), line.expected, line.counted, line.difference)
        for line in closing.lines
    ] == [
        ("CASH", Decimal("600.00"), Decimal("600.00"), Decimal("0.00")),
        ("CREDIT_CARD", Decimal("40.00"), Decimal("40.00"), Decimal("0.00")),
    ]
    # The shift keeps the cash line, as before S5.9
    assert result["status"] == "CLOSED"
    assert result["closing_number"] == "Z-001-CAJA-01-000001"
    assert (result["closing_balance"], result["expected_balance"]) == (
        Decimal("600.00"),
        Decimal("600.00"),
    )
    assert result["discrepancy"] == Decimal("0.00")
    closer.repo.update.assert_called_once()


def test_the_z_number_is_a_correlative_of_the_terminal():
    earlier = make_closing(shift_id=7, terminal_id=TERMINAL.id, sequence=4)
    elsewhere = make_closing(shift_id=8, terminal_id=99, sequence=9)
    closer = _Closer(
        _open_at_terminal(),
        closings=InMemoryShiftClosings([earlier, elsewhere]),
    )

    result = closer.close(("CASH", "500.00"))

    assert result["closing_number"] == "Z-001-CAJA-01-000005"


def test_a_difference_over_the_threshold_needs_a_justification():
    closer = _Closer(_open_at_terminal(), _cash_sales("100.00"))

    with pytest.raises(ClosingJustificationRequiredError) as error:
        closer.close(("CASH", "590.00"))

    assert error.value.methods == ["CASH"]
    assert closer.closings.closings == []
    closer.repo.update.assert_not_called()


def test_a_justified_difference_is_kept_and_audited():
    closer = _Closer(_open_at_terminal(), _cash_sales("100.00"))

    closer.close(("CASH", "590.00", "  Cambio mal dado  "))

    [closing] = closer.closings.closings
    assert closing.cash_line.difference == Decimal("-10.00")
    assert closing.cash_line.justification == "Cambio mal dado"
    [entry] = closer.audit.entries
    assert entry.action == AuditAction.SHIFT_CLOSED
    assert entry.after is not None
    assert entry.after["closing_number"] == "Z-001-CAJA-01-000001"
    assert entry.after["justification_threshold"] == Decimal("1.00")
    assert entry.after["counts"] == [
        {
            "payment_method": "CASH",
            "expected": Decimal("600.00"),
            "counted": Decimal("590.00"),
            "difference": Decimal("-10.00"),
            "justification": "Cambio mal dado",
        }
    ]


def test_every_method_the_shift_moved_must_be_counted():
    closer = _Closer(_open_at_terminal(), _cash_sales("100.00", card="40.00"))

    with pytest.raises(ClosingCountMissingError) as error:
        closer.close(("CASH", "600.00"))

    assert error.value.methods == ["CREDIT_CARD"]


def test_a_client_before_s5_9_sends_the_cash_as_closing_balance():
    closer = _Closer(_open_at_terminal())

    result = closer.close(closing_balance=Decimal("500.00"), notes="Sin novedad")

    assert result["closing_balance"] == Decimal("500.00")
    assert result["notes"] == "Sin novedad"
    assert closer.closings.closings[0].notes == "Sin novedad"


def test_close_shift_publishes_event():
    closer = _Closer(_open_at_terminal())

    closer.close(("CASH", "500.00"))

    closer.event_publisher.publish.assert_called_once()
    published = closer.event_publisher.publish.call_args[0][0]
    assert isinstance(published, ShiftClosed)
    assert (published.shift_id, published.closing_number) == (
        1,
        "Z-001-CAJA-01-000001",
    )


def test_close_shift_not_found():
    closer = _Closer(None)

    with pytest.raises(NotFoundError):
        closer.close(("CASH", "500.00"))


def test_close_shift_already_closed():
    closer = _Closer(_open_at_terminal(status=ShiftStatus.CLOSED))

    with pytest.raises(ShiftAlreadyClosedError):
        closer.close(("CASH", "500.00"))
    assert closer.closings.closings == []


def test_a_shift_from_before_s2_6_closes_without_codes_in_its_number():
    closer = _Closer(_make_shift())

    result = closer.close(("CASH", "500.00"))

    assert result["closing_number"] == "Z-000001"
