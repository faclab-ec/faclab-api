from sqlalchemy.orm import Session
from wireup import injectable

from src.platform_console.app.repositories import PlatformOperatorRepository
from src.platform_console.domain.entities import PlatformOperator
from src.platform_console.infra.mappers import PlatformOperatorMapper
from src.platform_console.infra.models import PlatformOperatorModel
from src.shared.infra.repositories import SqlAlchemyRepository


@injectable(lifetime="scoped", as_type=PlatformOperatorRepository)
class SqlAlchemyPlatformOperatorRepository(
    SqlAlchemyRepository[PlatformOperator], PlatformOperatorRepository
):
    __model__ = PlatformOperatorModel

    def __init__(self, session: Session, mapper: PlatformOperatorMapper):
        super().__init__(session, mapper)

    def get_by_user_id(self, user_id: int) -> PlatformOperator | None:
        return self.first(user_id=user_id)
