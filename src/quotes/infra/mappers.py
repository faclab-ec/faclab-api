from wireup import injectable

from src.quotes.domain.entities import Quote, QuoteItem
from src.quotes.infra.models import QuoteItemModel, QuoteModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class QuoteMapper(Mapper[Quote, QuoteModel]):
    __entity__ = Quote
    __exclude_fields__ = frozenset({"created_at", "updated_at"})


@injectable(lifetime="singleton")
class QuoteItemMapper(Mapper[QuoteItem, QuoteItemModel]):
    __entity__ = QuoteItem
