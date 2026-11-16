from wireup import injectable

from src.imports.domain.entities import ImportJob, ImportRow
from src.imports.infra.models import ImportJobModel, ImportRowModel
from src.shared.infra.mappers import Mapper


@injectable(lifetime="singleton")
class ImportJobMapper(Mapper[ImportJob, ImportJobModel]):
    __entity__ = ImportJob
    __exclude_fields__ = frozenset({"created_at"})


@injectable(lifetime="singleton")
class ImportRowMapper(Mapper[ImportRow, ImportRowModel]):
    __entity__ = ImportRow
