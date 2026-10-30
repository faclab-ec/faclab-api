from abc import abstractmethod

from src.invoicing.domain.entities import DiscrepancyKind, InvoiceDiscrepancy
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
