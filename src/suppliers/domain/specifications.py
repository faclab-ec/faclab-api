from typing import Any

from src.shared.domain.specifications import Specification, contains_pattern


class SuppliersByStatus(Specification):
    def __init__(self, is_active: bool):
        self.is_active = is_active

    def is_satisfied_by(self, candidate: Any) -> bool:
        return candidate.is_active is self.is_active

    def to_query_criteria(self) -> list[Any]:
        from src.suppliers.infra.models import SupplierModel

        return [SupplierModel.is_active == self.is_active]


class SupplierBySearchTerm(Specification):
    """Proveedores cuyo nombre o identificación contiene el término"""

    def __init__(self, term: str):
        self.term = term

    def is_satisfied_by(self, candidate: Any) -> bool:
        term = self.term.lower()
        return term in candidate.name.lower() or term in candidate.tax_id.lower()

    def to_query_criteria(self) -> list[Any]:
        from sqlalchemy import or_

        from src.suppliers.infra.models import SupplierModel

        pattern = contains_pattern(self.term)
        return [
            or_(
                SupplierModel.name.ilike(pattern, escape="\\"),
                SupplierModel.tax_id.ilike(pattern, escape="\\"),
            )
        ]
