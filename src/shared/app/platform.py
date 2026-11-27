"""Who is a platform operator (S8.5, S9.3).

Users are global identities: the password and the name of a user are the same
in every tenant and in the platform console. A tenant's admin may change them
only for a user that belongs to that tenant alone; a platform operator never
belongs to one tenant alone, since its console reaches all of them. Modules ask
through this port, like they record audit entries through `AuditTrail`: they
never import `src/platform_console`.
"""

from abc import ABC, abstractmethod

from src.shared.domain.exceptions import ConflictError


class UserIsPlatformOperatorError(ConflictError):
    error_code = "USER_IS_PLATFORM_OPERATOR"

    def __init__(self, user_id: int):
        super().__init__(
            "the user is a platform operator; their password and name can't be "
            "changed from a tenant",
            detail=f"user_id={user_id}",
        )


class PlatformOperators(ABC):
    @abstractmethod
    def is_operator(self, user_id: int) -> bool:
        """True when the user has a row in `platform_operators`, active or not:
        an inactive operator may be activated again with the same password"""

    def ensure_not_operator(self, user_id: int) -> None:
        if self.is_operator(user_id):
            raise UserIsPlatformOperatorError(user_id)
