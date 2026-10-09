from typing import Any

from src.shared.domain.specifications import Specification, contains_pattern


class ActiveCustomers(Specification):
    def is_satisfied_by(self, candidate: Any) -> bool:
        return getattr(candidate, "is_active", False) is True

    def to_query_criteria(self) -> list[Any]:
        from src.customers.infra.models import CustomerModel

        return [CustomerModel.is_active == True]  # noqa: E712


class CustomersByType(Specification):
    def __init__(self, tax_type: int):
        self.tax_type = tax_type

    def is_satisfied_by(self, candidate: Any) -> bool:
        return getattr(candidate, "tax_type", None) == self.tax_type

    def to_query_criteria(self) -> list[Any]:
        from src.customers.infra.models import CustomerModel

        return [CustomerModel.tax_type == self.tax_type]


class CustomerBySearchTerm(Specification):
    """Clientes cuyo nombre o identificación contiene el término"""

    def __init__(self, term: str):
        self.term = term

    def is_satisfied_by(self, candidate: Any) -> bool:
        term = self.term.lower()
        return term in candidate.name.lower() or term in candidate.tax_id.lower()

    def to_query_criteria(self) -> list[Any]:
        from sqlalchemy import or_

        from src.customers.infra.models import CustomerModel

        pattern = contains_pattern(self.term)
        return [
            or_(
                CustomerModel.name.ilike(pattern, escape="\\"),
                CustomerModel.tax_id.ilike(pattern, escape="\\"),
            )
        ]
