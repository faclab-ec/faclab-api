from abc import ABC, abstractmethod

from src.organization.domain.entities import Branch, EmissionPoint, PosTerminal
from src.organization.domain.numbering import DocumentType
from src.shared.app.repositories import Repository


class BranchRepository(Repository[Branch]):
    pass


class EmissionPointRepository(Repository[EmissionPoint]):
    pass


class PosTerminalRepository(Repository[PosTerminal]):
    pass


class DocumentSequenceRepository(ABC):
    @abstractmethod
    def next_value(self, branch_id: int | None, doc_type: DocumentType) -> int:
        """The next number of a document type in a branch (or in the whole
        tenant, without one), starting at 1. It locks the counter until the
        transaction ends, so two documents of the same type and branch never
        get the same number."""
        raise NotImplementedError
