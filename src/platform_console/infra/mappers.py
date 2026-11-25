from wireup import injectable

from src.platform_console.domain.entities import PlatformOperator
from src.platform_console.infra.models import PlatformOperatorModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class PlatformOperatorMapper(Mapper[PlatformOperator, PlatformOperatorModel]):
    __entity__ = PlatformOperator
    __exclude_fields__ = frozenset({"created_at"})
