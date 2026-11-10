from typing import Any

from wireup import injectable

from src.pos.refund.domain.entities import Refund, RefundItem, RefundPayment
from src.pos.refund.infra.models import RefundItemModel, RefundModel, RefundPaymentModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class RefundMapper(Mapper[Refund, RefundModel]):
    __entity__ = Refund


@injectable(lifetime="singleton")
class RefundItemMapper(Mapper[RefundItem, RefundItemModel]):
    __entity__ = RefundItem

    def to_dict(self, entity: RefundItem) -> dict[str, Any]:
        # The quantity in base units is stored for the reports (S5.2)
        return {**super().to_dict(entity), "base_quantity": entity.base_quantity}


@injectable(lifetime="singleton")
class RefundPaymentMapper(Mapper[RefundPayment, RefundPaymentModel]):
    __entity__ = RefundPayment
