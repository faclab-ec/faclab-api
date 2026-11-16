from src.imports.app.commands.create_import import CreateImportCommandHandler
from src.imports.app.commands.run_import import (
    ConfirmImportCommandHandler,
    FailImportCommandHandler,
    RunImportBatchCommandHandler,
)
from src.imports.app.kinds import KindImporters
from src.imports.app.kinds.partners import CustomerImporter, SupplierImporter
from src.imports.app.kinds.presentations import PresentationImporter
from src.imports.app.kinds.prices import PriceImporter
from src.imports.app.kinds.products import ProductImporter
from src.imports.app.kinds.stock import StockImporter
from src.imports.app.queries.imports import (
    GetImportErrorsQueryHandler,
    GetImportQueryHandler,
    GetImportRowsQueryHandler,
    GetImportsQueryHandler,
    GetImportTemplateQueryHandler,
    GetImportTemplatesQueryHandler,
)
from src.imports.infra.lookups import SqlAlchemyImportLookups
from src.imports.infra.mappers import ImportJobMapper, ImportRowMapper
from src.imports.infra.repositories import (
    SqlAlchemyImportJobRepository,
    SqlAlchemyImportRowRepository,
)

INJECTABLES = [
    ImportJobMapper,
    ImportRowMapper,
    SqlAlchemyImportJobRepository,
    SqlAlchemyImportRowRepository,
    SqlAlchemyImportLookups,
    ProductImporter,
    PresentationImporter,
    PriceImporter,
    CustomerImporter,
    SupplierImporter,
    StockImporter,
    KindImporters,
    CreateImportCommandHandler,
    ConfirmImportCommandHandler,
    RunImportBatchCommandHandler,
    FailImportCommandHandler,
    GetImportTemplatesQueryHandler,
    GetImportTemplateQueryHandler,
    GetImportsQueryHandler,
    GetImportQueryHandler,
    GetImportRowsQueryHandler,
    GetImportErrorsQueryHandler,
]
