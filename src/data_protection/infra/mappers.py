from wireup import injectable

from src.data_protection.domain.entities import ExportJob
from src.data_protection.infra.models import ExportJobModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class ExportJobMapper(Mapper[ExportJob, ExportJobModel]):
    __entity__ = ExportJob
    __exclude_fields__ = frozenset({"created_at"})
