from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session
from wireup import injectable

from src.organization.app.repositories import (
    BranchRepository,
    DocumentSequenceRepository,
    EmissionPointRepository,
    PosTerminalRepository,
)
from src.organization.domain.entities import Branch, EmissionPoint, PosTerminal
from src.organization.domain.exceptions import (
    BranchEstablishmentCodeAlreadyExistsError,
    EmissionPointCodeAlreadyExistsError,
    MainBranchAlreadyExistsError,
    PosTerminalCodeAlreadyExistsError,
)
from src.organization.domain.numbering import DocumentType
from src.organization.infra.mappers import (
    BranchMapper,
    EmissionPointMapper,
    PosTerminalMapper,
)
from src.organization.infra.models import (
    BranchModel,
    DocumentSequenceModel,
    EmissionPointModel,
    PosTerminalModel,
)
from src.shared.domain.tenant import require_tenant
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=BranchRepository)
class SqlAlchemyBranchRepository(SqlAlchemyRepository[Branch], BranchRepository):
    __model__ = BranchModel
    __unique_errors__ = {
        "uq_branches_tenant_establishment_code": (
            BranchEstablishmentCodeAlreadyExistsError
        ),
        "uq_branches_tenant_main": MainBranchAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: BranchMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=EmissionPointRepository)
class SqlAlchemyEmissionPointRepository(
    SqlAlchemyRepository[EmissionPoint], EmissionPointRepository
):
    __model__ = EmissionPointModel
    __unique_errors__ = {
        "uq_emission_points_tenant_branch_code": EmissionPointCodeAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: EmissionPointMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=PosTerminalRepository)
class SqlAlchemyPosTerminalRepository(
    SqlAlchemyRepository[PosTerminal], PosTerminalRepository
):
    __model__ = PosTerminalModel
    __unique_errors__ = {
        "uq_pos_terminals_tenant_branch_code": PosTerminalCodeAlreadyExistsError,
    }

    def __init__(self, session: Session, mapper: PosTerminalMapper):
        super().__init__(session, mapper)


@injectable(lifetime="scoped", as_type=DocumentSequenceRepository)
class SqlAlchemyDocumentSequenceRepository(DocumentSequenceRepository):
    """One upsert per number: the first document of a type creates the counter
    at 1 and the next ones add 1 to it. The row stays locked until the
    transaction ends, so concurrent documents of the branch wait their turn.
    A Core statement: the tenant is set here, `assign_tenant` doesn't see it."""

    _KEY = ("tenant_id", "branch_id", "doc_type")
    # A tenant's counter has no branch: its key is the partial unique index
    # uq_document_sequences_tenant_doc_type
    _TENANT_KEY = ("tenant_id", "doc_type")

    def __init__(self, session: Session):
        self.session = session

    def next_value(self, branch_id: int | None, doc_type: DocumentType) -> int:
        values = {
            "tenant_id": require_tenant("numbering a document").tenant_id,
            "branch_id": branch_id,
            "doc_type": doc_type.value,
            "last_value": 1,
        }
        conflict: dict = (
            {"index_elements": self._KEY}
            if branch_id is not None
            else {
                "index_elements": self._TENANT_KEY,
                "index_where": DocumentSequenceModel.branch_id.is_(None),
            }
        )
        bump = {"last_value": DocumentSequenceModel.last_value + 1}
        if self.session.get_bind().dialect.name == "postgresql":
            statement = (
                postgresql.insert(DocumentSequenceModel)
                .values(**values)
                .on_conflict_do_update(set_=bump, **conflict)
            )
        else:
            statement = (
                sqlite.insert(DocumentSequenceModel)
                .values(**values)
                .on_conflict_do_update(set_=bump, **conflict)
            )
        returning = statement.returning(DocumentSequenceModel.last_value)
        return self.session.execute(returning).scalar_one()
