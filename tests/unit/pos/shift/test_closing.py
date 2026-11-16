"""The count of a shift's closing (S5.9): what each method should have, what
must be counted and when a difference needs a justification"""

from decimal import Decimal

import pytest

from src.pos.shift.domain.closing import (
    MethodCount,
    MethodTotal,
    ShiftTotals,
    closing_number,
    count_lines,
)
from src.pos.shift.domain.exceptions import (
    ClosingCountInvalidError,
    ClosingCountMissingError,
    ClosingJustificationRequiredError,
)

OPENING = Decimal("50.00")
THRESHOLD = Decimal("1.00")


def _totals() -> ShiftTotals:
    """Cash, card, credit and transfer sales; payments on account in cash and
    transfer; a refund in cash; cash in and out"""
    return ShiftTotals(
        payments=[
            MethodTotal("CASH", 3, Decimal("120.00")),
            MethodTotal("CREDIT", 1, Decimal("80.00")),
            MethodTotal("CREDIT_CARD", 2, Decimal("45.50")),
        ],
        customer_payments=[
            MethodTotal("CASH", 1, Decimal("20.00")),
            MethodTotal("TRANSFER", 1, Decimal("30.00")),
        ],
        refund_payments=[MethodTotal("CASH", 1, Decimal("10.00"))],
        cash_in=Decimal("5.00"),
        cash_out=Decimal("15.00"),
    )


def _counts(**counted: str) -> list[MethodCount]:
    return [MethodCount(method, Decimal(amount)) for method, amount in counted.items()]


def test_each_method_the_shift_moved_has_its_line_and_cash_always():
    lines = _totals().lines(OPENING)

    assert [(str(line.payment_method), line.expected) for line in lines] == [
        # 50 + 120 - 10 + 20 + 5 - 15
        ("CASH", Decimal("170.00")),
        ("CREDIT_CARD", Decimal("45.50")),
        ("TRANSFER", Decimal("30.00")),
        # Owed by customers: not in the till, not counted
        ("CREDIT", None),
    ]
    assert [line.payments_count for line in lines] == [3, 2, 0, 1]
    assert ShiftTotals().lines(OPENING)[0].expected == OPENING


def test_the_count_keeps_counted_and_difference_of_each_method():
    lines = count_lines(
        _totals().lines(OPENING),
        _counts(CASH="170.50", CREDIT_CARD="45.50", TRANSFER="30.00"),
        THRESHOLD,
    )

    assert [(line.counted, line.difference) for line in lines] == [
        (Decimal("170.50"), Decimal("0.50")),
        (Decimal("45.50"), Decimal("0.00")),
        (Decimal("30.00"), Decimal("0.00")),
        (None, None),
    ]


def test_cash_and_every_method_moved_must_be_counted():
    with pytest.raises(ClosingCountMissingError) as error:
        count_lines(_totals().lines(OPENING), _counts(CREDIT_CARD="45.50"), THRESHOLD)

    assert error.value.methods == ["CASH", "TRANSFER"]


def test_a_method_without_movement_may_be_counted_against_zero():
    lines = count_lines(
        ShiftTotals().lines(OPENING),
        _counts(CASH="50.00", DEBIT_CARD="0.80"),
        THRESHOLD,
    )

    assert [(str(line.payment_method), line.difference) for line in lines] == [
        ("CASH", Decimal("0.00")),
        ("DEBIT_CARD", Decimal("0.80")),
    ]


@pytest.mark.parametrize(
    "counts",
    [
        _counts(CASH="50", CREDIT="0"),
        _counts(CASH="50", BITCOIN="1"),
        [MethodCount("CASH", Decimal("50")), MethodCount("CASH", Decimal("50"))],
    ],
    ids=["credit", "unknown", "twice"],
)
def test_credit_unknown_or_repeated_methods_are_not_counted(counts):
    with pytest.raises(ClosingCountInvalidError):
        count_lines(ShiftTotals().lines(OPENING), counts, THRESHOLD)


@pytest.mark.parametrize("counted", ["48.99", "51.01"])
def test_a_difference_over_the_threshold_needs_a_justification(counted):
    with pytest.raises(ClosingJustificationRequiredError) as error:
        count_lines(ShiftTotals().lines(OPENING), _counts(CASH=counted), THRESHOLD)

    assert error.value.methods == ["CASH"]


@pytest.mark.parametrize("counted", ["49.00", "51.00"])
def test_a_difference_equal_to_the_threshold_needs_none(counted):
    [line] = count_lines(ShiftTotals().lines(OPENING), _counts(CASH=counted), THRESHOLD)

    assert line.justification is None


def test_a_blank_justification_is_no_justification():
    count = MethodCount("CASH", Decimal("40.00"), justification="   ")

    with pytest.raises(ClosingJustificationRequiredError):
        count_lines(ShiftTotals().lines(OPENING), [count], THRESHOLD)


def test_a_zero_threshold_needs_a_justification_for_any_difference():
    with pytest.raises(ClosingJustificationRequiredError):
        count_lines(ShiftTotals().lines(OPENING), _counts(CASH="50.01"), Decimal("0"))

    [line] = count_lines(
        ShiftTotals().lines(OPENING),
        [MethodCount("CASH", Decimal("50.01"), "Moneda de más")],
        Decimal("0"),
    )
    assert line.justification == "Moneda de más"


def test_the_z_number_names_establishment_terminal_and_correlative():
    assert closing_number("001", "CAJA-01", 12) == "Z-001-CAJA-01-000012"
    # A shift from before S2.6 has no terminal nor branch
    assert closing_number(None, None, 3) == "Z-000003"
