"""Cómo se reparte un abono entre las cuentas del cliente, y la antigüedad de
sus saldos (S5.5)"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from src.receivables.domain.entities import Receivable
from src.receivables.domain.exceptions import (
    CustomerPaymentExceedsBalanceError,
    PaymentApplicationMismatchError,
    ReceivableNotOpenError,
)
from src.shared.domain.money import round_money


@dataclass(frozen=True)
class Allocation:
    """Lo que un abono aplica a una cuenta"""

    receivable: Receivable
    amount: Decimal


def _oldest_first(receivables: Sequence[Receivable]) -> list[Receivable]:
    return sorted(
        (r for r in receivables if r.is_open and r.balance > Decimal("0")),
        key=lambda r: (r.due_on, r.require_id()),
    )


def allocate_fifo(
    amount: Decimal, receivables: Sequence[Receivable]
) -> list[Allocation]:
    """Reparte el abono por antigüedad: primero la cuenta que vence antes (y,
    entre las que vencen el mismo día, la más antigua). No deja saldo a favor:
    un abono mayor a lo que se debe se rechaza."""
    amount = round_money(amount)
    pending = _oldest_first(receivables)
    owed = sum((r.balance for r in pending), Decimal("0"))
    if amount > owed:
        raise CustomerPaymentExceedsBalanceError(amount, owed)
    allocations = []
    left = amount
    for receivable in pending:
        if left <= Decimal("0"):
            break
        applied = min(left, receivable.balance)
        allocations.append(Allocation(receivable, applied))
        left -= applied
    return allocations


def allocate_manual(
    amount: Decimal,
    receivables: Sequence[Receivable],
    requested: Mapping[int, Decimal],
) -> list[Allocation]:
    """Aplica el abono como lo pide el usuario: cada cuenta abierta del cliente,
    sin pasar su saldo, y los montos suman el abono"""
    amount = round_money(amount)
    open_ones = {r.require_id(): r for r in _oldest_first(receivables)}
    allocations = []
    for receivable_id, requested_amount in requested.items():
        receivable = open_ones.get(receivable_id)
        if receivable is None:
            raise ReceivableNotOpenError(receivable_id)
        applied = round_money(requested_amount)
        if applied <= Decimal("0") or applied > receivable.balance:
            raise PaymentApplicationMismatchError(
                message=(
                    f"Receivable {receivable_id} has a balance of "
                    f"{receivable.balance}; it can't take {applied}"
                ),
                detail=f"receivable_id={receivable_id}, balance={receivable.balance}",
            )
        allocations.append(Allocation(receivable, applied))
    applied_total = sum((a.amount for a in allocations), Decimal("0"))
    if applied_total != amount:
        raise PaymentApplicationMismatchError(
            message=(
                f"The applications add up to {applied_total}, not to the payment's "
                f"{amount}"
            ),
            detail=f"amount={amount}, applied={applied_total}",
        )
    # In the same order as FIFO: the receivables are locked and updated so
    return sorted(
        allocations, key=lambda a: (a.receivable.due_on, a.receivable.require_id())
    )


class AgingBucket(StrEnum):
    """Tramos de antigüedad por días de vencido"""

    NOT_DUE = "NOT_DUE"
    DAYS_1_30 = "DAYS_1_30"
    DAYS_31_60 = "DAYS_31_60"
    DAYS_61_90 = "DAYS_61_90"
    OVER_90 = "OVER_90"


def aging_bucket(days_overdue: int) -> AgingBucket:
    """El tramo de una cuenta según los días desde su vencimiento: la que vence
    hoy o después está por vencer"""
    if days_overdue <= 0:
        return AgingBucket.NOT_DUE
    if days_overdue <= 30:
        return AgingBucket.DAYS_1_30
    if days_overdue <= 60:
        return AgingBucket.DAYS_31_60
    if days_overdue <= 90:
        return AgingBucket.DAYS_61_90
    return AgingBucket.OVER_90
