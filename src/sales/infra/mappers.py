from typing import Any

from wireup import injectable

from src.sales.domain.entities import Payment, Sale, SaleItem
from src.sales.infra.models import PaymentModel, SaleItemModel, SaleModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class SaleMapper(Mapper[Sale, SaleModel]):
    __entity__ = Sale
    __exclude_fields__ = frozenset({"created_at", "updated_at"})


@injectable(lifetime="singleton")
class SaleItemMapper(Mapper[SaleItem, SaleItemModel]):
    __entity__ = SaleItem

    def to_dict(self, entity: SaleItem) -> dict[str, Any]:
        # The quantity in base units is stored for the reports (S5.2)
        return {**super().to_dict(entity), "base_quantity": entity.base_quantity}


@injectable(lifetime="singleton")
class PaymentMapper(Mapper[Payment, PaymentModel]):
    __entity__ = Payment
    __exclude_fields__ = frozenset({"created_at"})
