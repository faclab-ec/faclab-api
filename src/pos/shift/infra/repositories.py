from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from wireup import injectable

from src.pos.shift.app.repositories import ShiftClosingRepository, ShiftRepository
from src.pos.shift.domain.closing import ItemSold, ShiftClosing, ShiftClosingLine
from src.pos.shift.domain.entities import Shift
from src.pos.shift.domain.exceptions import (
    ShiftAlreadyOpenError,
    ShiftClosingAlreadyExistsError,
)
from src.pos.shift.infra.mappers import ShiftMapper
from src.pos.shift.infra.models import (
    ShiftClosingLineModel,
    ShiftClosingModel,
    ShiftModel,
)
from src.sales.domain.entities import PaymentMethod
from src.shared.infra.repositories import SqlAlchemyRepository
from src.shared.infra.tenant import tenant_criteria


@injectable(lifetime="scoped", as_type=ShiftRepository)
class SqlAlchemyShiftRepository(SqlAlchemyRepository[Shift], ShiftRepository):
    __model__ = ShiftModel
    __unique_errors__ = {
        "uq_pos_shifts_tenant_terminal_open": ShiftAlreadyOpenError,
    }

    def __init__(self, session: Session, mapper: ShiftMapper):
        super().__init__(session, mapper)


# The columns a closing and its lines share with their entities
_CLOSING_COLUMNS = (
    "shift_id",
    "terminal_id",
    "branch_id",
    "sequence",
    "number",
    "cashier_name",
    "opened_at",
    "closed_at",
    "closed_by",
    "closed_by_user_id",
    "opening_balance",
    "sales_count",
    "sales_subtotal",
    "sales_tax",
    "sales_discount",
    "sales_total",
    "refunds_count",
    "refunds_total",
    "cash_sales",
    "cash_refunds",
    "customer_payments",
    "cash_in",
    "cash_out",
    "justification_threshold",
    "notes",
)
_LINE_COLUMNS = (
    "payments_count",
    "payments_total",
    "customer_payments_count",
    "customer_payments_total",
    "refunds_total",
    "expected",
    "counted",
    "difference",
    "justification",
)


def _items_to_json(items: list[ItemSold]) -> list[dict]:
    """Decimals as text, so the JSON keeps them exact"""
    return [
        {
            "product_name": item.product_name,
            "sku": item.sku,
            "quantity": str(item.quantity),
            "total": str(item.total),
        }
        for item in items
    ]


def _items_from_json(rows: list[dict]) -> list[ItemSold]:
    return [
        ItemSold(
            product_name=row["product_name"],
            sku=row["sku"],
            quantity=Decimal(row["quantity"]),
            total=Decimal(row["total"]),
        )
        for row in rows or []
    ]


@injectable(lifetime="scoped", as_type=ShiftClosingRepository)
class SqlAlchemyShiftClosingRepository(ShiftClosingRepository):
    """Writes a closing and its lines once and reads them back. There is no
    update nor delete: the closing is the record of the count. ORM inserts:
    `assign_tenant` gives them the context's tenant."""

    _UNIQUE = {
        "uq_pos_shift_closings_tenant_shift_id",
        "uq_pos_shift_closings_tenant_terminal_sequence",
    }

    def __init__(self, session: Session):
        self.session = session

    def add(self, closing: ShiftClosing) -> ShiftClosing:
        model = ShiftClosingModel(
            **{column: getattr(closing, column) for column in _CLOSING_COLUMNS},
            items_sold=_items_to_json(closing.items_sold),
        )
        self.session.add(model)
        self._flush()
        lines = [
            ShiftClosingLineModel(
                closing_id=model.id,
                payment_method=str(line.payment_method),
                **{column: getattr(line, column) for column in _LINE_COLUMNS},
            )
            for line in closing.lines
        ]
        self.session.add_all(lines)
        self._flush()
        return self._to_entity(model, lines)

    def _flush(self) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            diag = getattr(exc.orig, "diag", None)
            if getattr(diag, "constraint_name", "") in self._UNIQUE:
                raise ShiftClosingAlreadyExistsError() from exc
            raise

    def of_shift(self, shift_id: int) -> ShiftClosing | None:
        model = (
            self.session.query(ShiftClosingModel)
            .filter(
                ShiftClosingModel.shift_id == shift_id,
                *tenant_criteria(ShiftClosingModel),
            )
            .first()
        )
        if model is None:
            return None
        lines = (
            self.session.query(ShiftClosingLineModel)
            .filter(
                ShiftClosingLineModel.closing_id == model.id,
                *tenant_criteria(ShiftClosingLineModel),
            )
            .all()
        )
        return self._to_entity(model, lines)

    def numbers_of(self, shift_ids: Iterable[int]) -> dict[int, str]:
        ids = set(shift_ids)
        if not ids:
            return {}
        rows = (
            self.session.query(ShiftClosingModel.shift_id, ShiftClosingModel.number)
            .filter(
                ShiftClosingModel.shift_id.in_(ids),
                *tenant_criteria(ShiftClosingModel),
            )
            .all()
        )
        return {row.shift_id: row.number for row in rows}

    def next_sequence(self, terminal_id: int | None) -> int:
        terminal = (
            ShiftClosingModel.terminal_id.is_(None)
            if terminal_id is None
            else ShiftClosingModel.terminal_id == terminal_id
        )
        last = (
            self.session.query(func.max(ShiftClosingModel.sequence))
            .filter(terminal, *tenant_criteria(ShiftClosingModel))
            .scalar()
        )
        return (last or 0) + 1

    @staticmethod
    def _to_entity(
        model: ShiftClosingModel, lines: list[ShiftClosingLineModel]
    ) -> ShiftClosing:
        order = list(PaymentMethod)
        return ShiftClosing(
            id=model.id,
            **{column: getattr(model, column) for column in _CLOSING_COLUMNS},
            items_sold=_items_from_json(model.items_sold),
            lines=sorted(
                (
                    ShiftClosingLine(
                        id=line.id,
                        closing_id=line.closing_id,
                        payment_method=PaymentMethod(line.payment_method),
                        **{column: getattr(line, column) for column in _LINE_COLUMNS},
                    )
                    for line in lines
                ),
                key=lambda line: order.index(line.payment_method),
            ),
        )
