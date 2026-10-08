from src.shared.domain.specifications import Specification


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
    def __init__(self, term: str):
        self.term = term

    def is_satisfied_by(self, candidate) -> bool:
        return (
            candidate.sku == self.term
            or (candidate.barcode and candidate.barcode == self.term)
            or self.term.lower() in candidate.name.lower()
        )

    def to_query_criteria(self):
        from sqlalchemy import or_

        from src.catalog.product.infra.models import ProductModel

        return [
            or_(
                ProductModel.sku == self.term,
                ProductModel.barcode == self.term,
                ProductModel.name.ilike(f"%{self.term}%"),
            )
        ]
