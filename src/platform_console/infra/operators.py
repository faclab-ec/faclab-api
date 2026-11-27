from wireup import injectable

from src.platform_console.app.repositories import PlatformOperatorRepository
from src.shared.app.platform import PlatformOperators


@injectable(lifetime="scoped", as_type=PlatformOperators)
class RepositoryPlatformOperators(PlatformOperators):
    """`PlatformOperators` over `platform_operators` (faclab_app may read it)"""

    def __init__(self, operators: PlatformOperatorRepository):
        self.operators = operators

    def is_operator(self, user_id: int) -> bool:
        return self.operators.get_by_user_id(user_id) is not None
