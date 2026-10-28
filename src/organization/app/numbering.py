from wireup import injectable

from src.organization.app.repositories import (
    BranchRepository,
    DocumentSequenceRepository,
)
from src.organization.domain.numbering import (
    DocumentType,
    document_number,
    tenant_document_number,
)
from src.shared.domain.exceptions import NotFoundError


@injectable(lifetime="scoped")
class DocumentNumbering:
    """Numbers the internal documents of a branch or of the whole tenant
    (ADR-0012) inside the document's transaction"""

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

    def next_in_tenant(self, doc_type: DocumentType, year: int) -> str:
        """A document of the whole tenant, such as a purchase order"""
        value = self.sequences.next_value(None, doc_type)
        return tenant_document_number(doc_type, year, value)
