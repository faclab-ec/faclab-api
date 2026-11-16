"""Un importador por tipo de plantilla (S5.8)"""

from wireup import injectable

from src.imports.app.columns import Column
from src.imports.app.kinds.base import KindImporter
from src.imports.app.kinds.partners import CustomerImporter, SupplierImporter
from src.imports.app.kinds.presentations import PresentationImporter
from src.imports.app.kinds.prices import PriceImporter
from src.imports.app.kinds.products import ProductImporter
from src.imports.app.kinds.stock import StockImporter
from src.imports.domain.entities import ImportKind

IMPORTERS: tuple[type[KindImporter], ...] = (
    ProductImporter,
    PresentationImporter,
    PriceImporter,
    CustomerImporter,
    SupplierImporter,
    StockImporter,
)

# Las columnas de cada plantilla, en el orden en que se cargan
TEMPLATES: dict[ImportKind, tuple[Column, ...]] = {
    importer.kind: importer.columns for importer in IMPORTERS
}


@injectable(lifetime="scoped")
class KindImporters:
    def __init__(
        self,
        products: ProductImporter,
        presentations: PresentationImporter,
        prices: PriceImporter,
        customers: CustomerImporter,
        suppliers: SupplierImporter,
        stock: StockImporter,
    ):
        self._by_kind: dict[ImportKind, KindImporter] = {
            importer.kind: importer
            for importer in (
                products,
                presentations,
                prices,
                customers,
                suppliers,
                stock,
            )
        }

    def of(self, kind: ImportKind) -> KindImporter:
        return self._by_kind[kind]
