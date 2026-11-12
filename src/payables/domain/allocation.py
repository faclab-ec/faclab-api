"""Cómo se reparte un pago o una devolución entre las cuentas del proveedor
(S5.7). Es el mismo criterio que los abonos de clientes (S5.5)"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.payables.domain.entities import Payable
from src.payables.domain.exceptions import (
    PayableNotOpenError,
    SupplierPaymentApplicationMismatchError,
    SupplierPaymentExceedsBalanceError,
)
from src.shared.domain.money import round_money

ZERO = Decimal("0")


@dataclass(frozen=True)
class Allocation:
    """Lo que un pago o una devolución aplican a una cuenta"""

    payable: Payable
    amount: Decimal


def _fifo_key(payable: Payable) -> tuple:
    return payable.due_on, payable.require_id()


def _oldest_first(payables: Sequence[Payable]) -> list[Payable]:
    return sorted(
        (p for p in payables if p.is_open and p.balance > ZERO), key=_fifo_key
    )


def _fill(amount: Decimal, payables: Sequence[Payable]) -> list[Allocation]:
    allocations = []
    left = amount
    for payable in payables:
        if left <= ZERO:
            break
        applied = min(left, payable.balance)
        allocations.append(Allocation(payable, applied))
        left -= applied
    return allocations


def allocate_fifo(amount: Decimal, payables: Sequence[Payable]) -> list[Allocation]:
    """Reparte el pago por antigüedad: primero la cuenta que vence antes (y,
    entre las que vencen el mismo día, la más antigua). No deja saldo a favor:
    un pago mayor a lo que se debe se rechaza."""
    amount = round_money(amount)
    pending = _oldest_first(payables)
    owed = sum((p.balance for p in pending), ZERO)
    if amount > owed:
        raise SupplierPaymentExceedsBalanceError(amount, owed)
    return _fill(amount, pending)


def allocate_manual(
    amount: Decimal,
    payables: Sequence[Payable],
    requested: Mapping[int, Decimal],
) -> list[Allocation]:
    """Aplica el pago como lo pide el usuario: cada cuenta abierta del
    proveedor, sin pasar su saldo, y los montos suman el pago"""
    amount = round_money(amount)
    open_ones = {p.require_id(): p for p in _oldest_first(payables)}
    allocations = []
    for payable_id, requested_amount in requested.items():
        payable = open_ones.get(payable_id)
        if payable is None:
            raise PayableNotOpenError(payable_id)
        applied = round_money(requested_amount)
        if applied <= ZERO or applied > payable.balance:
            raise SupplierPaymentApplicationMismatchError(
                message=(
                    f"Payable {payable_id} has a balance of {payable.balance}; it "
                    f"can't take {applied}"
                ),
                detail=f"payable_id={payable_id}, balance={payable.balance}",
            )
        allocations.append(Allocation(payable, applied))
    applied_total = sum((a.amount for a in allocations), ZERO)
    if applied_total != amount:
        raise SupplierPaymentApplicationMismatchError(
            message=(
                f"The applications add up to {applied_total}, not to the payment's "
                f"{amount}"
            ),
            detail=f"amount={amount}, applied={applied_total}",
        )
    return sorted(allocations, key=lambda a: _fifo_key(a.payable))


def allocate_return(
    amount: Decimal, payables: Sequence[Payable], purchase_order_id: int
) -> list[Allocation]:
    """Reparte una devolución: primero las cuentas de su orden de compra y
    después las demás del proveedor, cada grupo por antigüedad. Lo que no cabe
    en lo que se debe no se aplica: el proveedor lo reembolsa"""
    pending = _oldest_first(payables)
    ordered = [p for p in pending if p.purchase_order_id == purchase_order_id] + [
        p for p in pending if p.purchase_order_id != purchase_order_id
    ]
    return _fill(round_money(amount), ordered)
