from abc import abstractmethod
from collections.abc import Iterable

from src.invoicing.domain.entities import (
    CreditNote,
    DiscrepancyKind,
    InvoiceDiscrepancy,
)
from src.shared.app.repositories import Repository


class InvoiceDiscrepancyRepository(Repository[InvoiceDiscrepancy]):
    @abstractmethod
    def open(
        self, sale_id: int, kind: DiscrepancyKind, invoice_id: str | None = None
    ) -> bool:
        """Abre una discrepancia de la venta, salvo que ya tenga una sin
        resolver de ese tipo (quizá la abrió otro worker); dice si la abrió"""
        raise NotImplementedError

    @abstractmethod
    def unresolved(
        self, kind: DiscrepancyKind, sale_id: int | None = None
    ) -> list[InvoiceDiscrepancy]:
        """Las abiertas o revisadas de ese tipo, de una venta o de todas"""
        raise NotImplementedError


class CreditNoteRepository(Repository[CreditNote]):
    @abstractmethod
    def of_refunds(self, refund_ids: Iterable[int]) -> list[CreditNote]:
        """Las notas de esas devoluciones"""
        raise NotImplementedError

    @abstractmethod
    def of_cancelled_sale(self, sale_id: int) -> CreditNote | None:
        """La nota de la factura de una venta anulada, sin devolución"""
        raise NotImplementedError
