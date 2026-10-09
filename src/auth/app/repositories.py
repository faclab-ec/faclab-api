from datetime import datetime

from src.auth.domain.entities import AuthSession, User
from src.shared.app.repositories import Repository


class UserRepository(Repository[User]):
    def get_by_username(self, username: str) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...


class AuthSessionRepository(Repository[AuthSession]):
    def revoke_all_for_user(
        self, user_id: int, now: datetime, keep_session_id: int | None = None
    ) -> int:
        """Revoke the user's active sessions except `keep_session_id`; return
        how many were revoked."""
        raise NotImplementedError
