from wireup import injectable

from src.pricing.domain.entities import PriceList, PriceListItem
from src.pricing.infra.models import PriceListItemModel, PriceListModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class PriceListMapper(Mapper[PriceList, PriceListModel]):
    __entity__ = PriceList
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class PriceListItemMapper(Mapper[PriceListItem, PriceListItemModel]):
    __entity__ = PriceListItem
    __exclude_fields__ = frozenset({"created_at"})
