from abc import ABC, abstractmethod


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, plain: str) -> str: ...

    @abstractmethod
    def verify(self, plain: str, hashed: str) -> bool: ...

    @abstractmethod
    def verify_dummy(self, plain: str) -> None:
        """Spend the same time as verify() when there is no user to check
        against, so the response time doesn't tell whether a username exists."""
