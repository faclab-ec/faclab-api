from wireup import injectable

from src.invoicing.domain.entities import InvoiceDiscrepancy
from src.invoicing.infra.models import InvoiceDiscrepancyModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class InvoiceDiscrepancyMapper(Mapper[InvoiceDiscrepancy, InvoiceDiscrepancyModel]):
    __entity__ = InvoiceDiscrepancy
    __exclude_fields__ = frozenset({"detected_at"})
