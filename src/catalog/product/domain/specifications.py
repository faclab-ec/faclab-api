from src.shared.domain.specifications import Specification, contains_pattern


class ProductInCategory(Specification):
    def __init__(self, category_id: int):
        self.category_id = category_id

    def is_satisfied_by(self, candidate) -> bool:
        return candidate.category_id == self.category_id

    def to_query_criteria(self):
        from src.catalog.product.infra.models import ProductModel

        return [ProductModel.category_id == self.category_id]


class ProductByName(Specification):
    def __init__(self, name_pattern: str):
        self.name_pattern = name_pattern

    def is_satisfied_by(self, candidate) -> bool:
        return self.name_pattern.lower() in candidate.name.lower()

    def to_query_criteria(self):
        from src.catalog.product.infra.models import ProductModel

        return [ProductModel.name.ilike(f"%{self.name_pattern}%")]


class ProductBySku(Specification):
    def __init__(self, sku: str):
        self.sku = sku

    def is_satisfied_by(self, candidate) -> bool:
        return candidate.sku == self.sku

    def to_query_criteria(self):
        from src.catalog.product.infra.models import ProductModel

        return [ProductModel.sku == self.sku]


class ProductBySearchTerm(Specification):
    """Productos cuyo nombre o SKU contiene el término, o con una presentación
    activa de ese código de barras (S5.2: los códigos viven en las presentaciones;
    en memoria solo se comparan nombre y SKU)"""

    def __init__(self, term: str):
        self.term = term

    def is_satisfied_by(self, candidate) -> bool:
        term = self.term.lower()
        return term in candidate.sku.lower() or term in candidate.name.lower()

    def to_query_criteria(self):
        from sqlalchemy import and_, exists, or_

        from src.catalog.product.infra.models import (
            ProductModel,
            ProductPresentationModel,
        )
        from src.shared.infra.tenant import tenant_criteria

        pattern = contains_pattern(self.term)
        by_barcode = exists().where(
            and_(
                ProductPresentationModel.product_id == ProductModel.id,
                ProductPresentationModel.barcode == self.term,
                ProductPresentationModel.is_active.is_(True),
                *tenant_criteria(ProductPresentationModel),
            )
        )
        return [
            or_(
                ProductModel.sku.ilike(pattern, escape="\\"),
                ProductModel.name.ilike(pattern, escape="\\"),
                by_barcode,
            )
        ]
