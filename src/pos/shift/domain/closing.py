"""El cierre Z de un turno (S5.9): lo que el turno movió, el arqueo por medio de
pago y el número con el que queda guardado. Una vez escrito no cambia: los
reportes leen el cierre, no lo recalculan."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from src.pos.shift.domain.exceptions import (
    ClosingCountInvalidError,
    ClosingCountMissingError,
    ClosingJustificationRequiredError,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.domain.entities import Entity

ZERO = Decimal("0")


@dataclass(frozen=True)
class MethodTotal:
    """Cuántos pagos de un medio y cuánto suman"""

    payment_method: str
    count: int
    total: Decimal


@dataclass(frozen=True)
class ItemSold:
    """Un producto vendido en el turno, en su unidad base"""

    product_name: str
    sku: str
    quantity: Decimal
    total: Decimal


def _total_of(rows: list[MethodTotal], method: PaymentMethod) -> Decimal:
    return sum((row.total for row in rows if row.payment_method == method), ZERO)


def _count_of(rows: list[MethodTotal], method: PaymentMethod) -> int:
    return sum(row.count for row in rows if row.payment_method == method)


@dataclass
class ShiftTotals:
    """Lo que un turno movió, leído de sus ventas completadas, abonos,
    devoluciones completadas y movimientos de caja. Lo usan el reporte X, el
    resumen de caja, el arqueo y el cierre Z."""

    sales_count: int = 0
    sales_subtotal: Decimal = ZERO
    sales_tax: Decimal = ZERO
    sales_discount: Decimal = ZERO
    sales_total: Decimal = ZERO
    # Pagos aplicados de las ventas completadas, por medio (CREDIT: a crédito)
    payments: list[MethodTotal] = field(default_factory=list)
    # Abonos a cuenta tomados en el turno (S5.5), por medio
    customer_payments: list[MethodTotal] = field(default_factory=list)
    refunds_count: int = 0
    refunds_total: Decimal = ZERO
    # Lo devuelto por las devoluciones completadas, por medio (CREDIT: a la cuenta)
    refund_payments: list[MethodTotal] = field(default_factory=list)
    cash_in: Decimal = ZERO
    cash_out: Decimal = ZERO
    items_sold: list[ItemSold] = field(default_factory=list)

    @property
    def cash_sales(self) -> Decimal:
        return _total_of(self.payments, PaymentMethod.CASH)

    @property
    def cash_refunds(self) -> Decimal:
        return _total_of(self.refund_payments, PaymentMethod.CASH)

    @property
    def cash_customer_payments(self) -> Decimal:
        return _total_of(self.customer_payments, PaymentMethod.CASH)

    def cash_summary(self) -> dict[str, Decimal]:
        """Los componentes del efectivo del turno"""
        return {
            "cash_sales": self.cash_sales,
            "cash_refunds": self.cash_refunds,
            "customer_payments": self.cash_customer_payments,
            "cash_in": self.cash_in,
            "cash_out": self.cash_out,
        }

    def expected_cash(self, opening_balance: Decimal) -> Decimal:
        """El efectivo que debería haber en la caja: el de apertura, más ventas
        y abonos en efectivo, menos devoluciones en efectivo, más y menos los
        movimientos"""
        return expected_cash(opening_balance, self.cash_summary())

    def lines(self, opening_balance: Decimal) -> list["ShiftClosingLine"]:
        """Una línea por medio de pago: el efectivo siempre, cada otro medio si
        el turno lo movió. CREDIT no entra en la caja: su línea solo informa (sin
        esperado). Ordenadas como `PaymentMethod`."""
        lines = []
        for method in PaymentMethod:
            moved = (
                _count_of(self.payments, method)
                or _count_of(self.customer_payments, method)
                or _count_of(self.refund_payments, method)
            )
            if method != PaymentMethod.CASH and not moved:
                continue
            payments_total = _total_of(self.payments, method)
            customer_total = _total_of(self.customer_payments, method)
            refunds_total = _total_of(self.refund_payments, method)
            if method == PaymentMethod.CASH:
                expected: Decimal | None = self.expected_cash(opening_balance)
            elif method == PaymentMethod.CREDIT:
                expected = None
            else:
                expected = payments_total + customer_total - refunds_total
            lines.append(
                ShiftClosingLine(
                    payment_method=method,
                    payments_count=_count_of(self.payments, method),
                    payments_total=payments_total,
                    customer_payments_count=_count_of(self.customer_payments, method),
                    customer_payments_total=customer_total,
                    refunds_total=refunds_total,
                    expected=expected,
                )
            )
        return lines


def expected_cash(opening_balance: Decimal, summary: dict) -> Decimal:
    """El efectivo que debería haber en la caja a partir de sus componentes"""
    return (
        opening_balance
        + summary["cash_sales"]
        - summary["cash_refunds"]
        + summary["customer_payments"]
        + summary["cash_in"]
        - summary["cash_out"]
    )


@dataclass
class ShiftClosingLine(Entity):
    """El arqueo de un medio de pago: lo que el turno movió en él, lo esperado,
    lo contado, la diferencia (contado − esperado) y su justificación. CREDIT
    no se cuenta: sus campos del arqueo quedan nulos."""

    payment_method: PaymentMethod
    payments_count: int = 0
    payments_total: Decimal = ZERO
    customer_payments_count: int = 0
    customer_payments_total: Decimal = ZERO
    refunds_total: Decimal = ZERO
    expected: Decimal | None = None
    counted: Decimal | None = None
    difference: Decimal | None = None
    justification: str | None = None
    closing_id: int | None = None
    id: int | None = None

    @property
    def countable(self) -> bool:
        return self.payment_method != PaymentMethod.CREDIT


@dataclass(frozen=True)
class MethodCount:
    """Lo que el cajero declara de un medio al cerrar"""

    payment_method: str
    counted: Decimal
    justification: str | None = None


def _method(value: str) -> PaymentMethod:
    try:
        method = PaymentMethod(value)
    except ValueError:
        raise ClosingCountInvalidError(
            message=f"Invalid payment method: {value}",
            detail=f"Valid methods: {[m.value for m in PaymentMethod]}",
        ) from None
    if method == PaymentMethod.CREDIT:
        raise ClosingCountInvalidError(
            message="CREDIT is not counted: it is owed by customers, not in the till",
            detail="Count every other payment method",
        )
    return method


def count_lines(
    lines: list[ShiftClosingLine],
    counts: list[MethodCount],
    threshold: Decimal,
) -> list[ShiftClosingLine]:
    """El arqueo: cada línea contable toma lo contado y su diferencia.

    - El efectivo y todo medio que el turno movió deben contarse
      (`CLOSING_COUNT_MISSING`); un medio sin movimiento puede contarse (se
      espera 0).
    - CREDIT, un medio desconocido o uno repetido no se cuentan
      (`CLOSING_COUNT_INVALID`).
    - Una diferencia que supera el umbral, en valor absoluto, exige
      justificación (`CLOSING_JUSTIFICATION_REQUIRED`); igual al umbral, no.
    """
    by_method: dict[PaymentMethod, MethodCount] = {}
    for count in counts:
        method = _method(count.payment_method)
        if method in by_method:
            raise ClosingCountInvalidError(
                message=f"{method} is counted twice",
                detail="Count each payment method once",
            )
        by_method[method] = count

    result = list(lines)
    present = {line.payment_method for line in result}
    for method in PaymentMethod:
        if method in by_method and method not in present:
            result.append(ShiftClosingLine(payment_method=method, expected=ZERO))
    result.sort(key=lambda line: list(PaymentMethod).index(line.payment_method))

    missing = [
        str(line.payment_method)
        for line in result
        if line.countable and line.payment_method not in by_method
    ]
    if missing:
        raise ClosingCountMissingError(missing)

    unjustified = []
    for line in result:
        if not line.countable:
            continue
        count = by_method[line.payment_method]
        line.counted = count.counted
        line.difference = count.counted - (line.expected or ZERO)
        line.justification = (count.justification or "").strip() or None
        if abs(line.difference) > threshold and line.justification is None:
            unjustified.append(str(line.payment_method))
    if unjustified:
        raise ClosingJustificationRequiredError(unjustified, str(threshold))
    return result


def closing_number(
    establishment_code: str | None, terminal_code: str | None, sequence: int
) -> str:
    """Número visible del cierre Z: prefijo, código del establecimiento, código
    de la terminal y correlativo de seis dígitos por terminal
    (`Z-001-CAJA-01-000012`). Conserva los códigos con los que se emitió. Un
    turno anterior a S2.6, sin terminal: `Z-000012`."""
    parts = ["Z", establishment_code, terminal_code, f"{sequence:06d}"]
    return "-".join(part for part in parts if part)


@dataclass
class ShiftClosing(Entity):
    """El cierre Z de un turno, escrito en la transacción que lo cierra. No
    tiene métodos que lo cambien y la base no deja a la aplicación modificarlo
    ni borrarlo."""

    shift_id: int
    sequence: int
    number: str
    cashier_name: str
    closed_at: datetime
    terminal_id: int | None = None
    branch_id: int | None = None
    opened_at: datetime | None = None
    closed_by: str | None = None
    closed_by_user_id: int | None = None
    opening_balance: Decimal = ZERO
    sales_count: int = 0
    sales_subtotal: Decimal = ZERO
    sales_tax: Decimal = ZERO
    sales_discount: Decimal = ZERO
    sales_total: Decimal = ZERO
    refunds_count: int = 0
    refunds_total: Decimal = ZERO
    cash_sales: Decimal = ZERO
    cash_refunds: Decimal = ZERO
    customer_payments: Decimal = ZERO
    cash_in: Decimal = ZERO
    cash_out: Decimal = ZERO
    # El umbral con el que se exigieron las justificaciones
    justification_threshold: Decimal = ZERO
    notes: str | None = None
    items_sold: list[ItemSold] = field(default_factory=list)
    lines: list[ShiftClosingLine] = field(default_factory=list)
    id: int | None = None

    @property
    def cash_line(self) -> ShiftClosingLine:
        return next(
            line for line in self.lines if line.payment_method == PaymentMethod.CASH
        )
