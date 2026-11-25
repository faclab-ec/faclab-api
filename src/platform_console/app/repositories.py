from abc import abstractmethod

from src.platform_console.domain.entities import PlatformOperator
from src.shared.app.repositories import Repository


class PlatformOperatorRepository(Repository[PlatformOperator]):
    @abstractmethod
    def get_by_user_id(self, user_id: int) -> PlatformOperator | None: ...
