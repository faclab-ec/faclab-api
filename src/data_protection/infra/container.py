from src.data_protection.app.commands.offboarding import (
    AnonymizeTenantCommandHandler,
    CancelOffboardingCommandHandler,
    PurgeTenantCommandHandler,
    StartOffboardingCommandHandler,
)
from src.data_protection.app.commands.request_export import (
    RequestDataExportCommandHandler,
)
from src.data_protection.app.queries.exports import (
    GetDataExportFileQueryHandler,
    GetDataExportQueryHandler,
    GetDataExportsQueryHandler,
)
from src.data_protection.infra.cleaner import SqlAlchemyTenantDataCleaner
from src.data_protection.infra.mappers import ExportJobMapper
from src.data_protection.infra.repositories import SqlAlchemyExportJobRepository

INJECTABLES = [
    ExportJobMapper,
    SqlAlchemyExportJobRepository,
    RequestDataExportCommandHandler,
    GetDataExportsQueryHandler,
    GetDataExportQueryHandler,
    GetDataExportFileQueryHandler,
    SqlAlchemyTenantDataCleaner,
    StartOffboardingCommandHandler,
    CancelOffboardingCommandHandler,
    AnonymizeTenantCommandHandler,
    PurgeTenantCommandHandler,
]
