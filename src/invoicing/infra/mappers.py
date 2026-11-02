from wireup import injectable

from src.invoicing.domain.entities import CreditNote, InvoiceDiscrepancy
from src.invoicing.infra.models import CreditNoteModel, InvoiceDiscrepancyModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class InvoiceDiscrepancyMapper(Mapper[InvoiceDiscrepancy, InvoiceDiscrepancyModel]):
    __entity__ = InvoiceDiscrepancy
    __exclude_fields__ = frozenset({"detected_at"})


@injectable(lifetime="singleton")
class CreditNoteMapper(Mapper[CreditNote, CreditNoteModel]):
    __entity__ = CreditNote
    __exclude_fields__ = frozenset({"created_at"})
