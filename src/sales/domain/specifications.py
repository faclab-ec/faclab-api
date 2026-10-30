"""Especificaciones del dominio de Sales"""

from datetime import datetime
from typing import Any

from src.shared.domain.specifications import Specification


class ParkedSalesSpecification(Specification):
    """Especificacion para ventas aparcadas (DRAFT con parked_at no nulo)"""

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.status == "DRAFT" and candidate.parked_at is not None

    def to_query_criteria(self) -> list[Any]:
        from src.sales.infra.models import SaleModel

        return [
            SaleModel.status == "DRAFT",
            SaleModel.parked_at.isnot(None),
        ]


class SalesByTerminal(Specification):
    """Ventas de una terminal del POS"""

    def __init__(self, terminal_id: int):
        self.terminal_id = terminal_id

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.terminal_id == self.terminal_id

    def to_query_criteria(self) -> list[Any]:
        from src.sales.infra.models import SaleModel

        return [SaleModel.terminal_id == self.terminal_id]


class SalesAwaitingInvoice(Specification):
    """Ventas confirmadas que siguen sin resultado de facturación desde antes de
    `older_than`: pendientes desde que se enviaron, o nunca enviadas. Sin punto
    de emisión (antes de S2.6) no se pueden facturar y no cuentan."""

    def __init__(self, older_than: datetime):
        self.older_than = older_than

    def is_satisfied_by(self, candidate: Any) -> bool:
        if candidate.status != "CONFIRMED" or candidate.emission_point_id is None:
            return False
        if candidate.invoice_status == "PENDING":
            since = candidate.invoice_requested_at
        elif candidate.invoice_status is None:
            since = candidate.sale_date
        else:
            return False
        return since is not None and since < self.older_than

    def to_query_criteria(self) -> list[Any]:
        from sqlalchemy import and_, or_

        from src.sales.infra.models import SaleModel

        return [
            SaleModel.status == "CONFIRMED",
            SaleModel.emission_point_id.isnot(None),
            or_(
                and_(
                    SaleModel.invoice_status == "PENDING",
                    SaleModel.invoice_requested_at < self.older_than,
                ),
                and_(
                    SaleModel.invoice_status.is_(None),
                    SaleModel.sale_date < self.older_than,
                ),
            ),
        ]
