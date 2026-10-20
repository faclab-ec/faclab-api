from wireup import injectable

from src.organization.app.repositories import (
    BranchRepository,
    DocumentSequenceRepository,
)
from src.organization.domain.numbering import DocumentType, document_number
from src.shared.domain.exceptions import NotFoundError


@injectable(lifetime="scoped")
class DocumentNumbering:
    """Numbers the internal documents of a branch (ADR-0012) inside the
    document's transaction"""

    def __init__(
        self, sequences: DocumentSequenceRepository, branches: BranchRepository
    ):
        self.sequences = sequences
        self.branches = branches

    def next(self, branch_id: int, doc_type: DocumentType) -> str:
        branch = self.branches.get_by_id(branch_id)
        if branch is None:
            raise NotFoundError(f"Branch {branch_id} not found")
        value = self.sequences.next_value(branch_id, doc_type)
        return document_number(doc_type, branch.establishment_code, value)
