from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Generic, TypeVar

from src.shared.domain.specifications import Specification

T = TypeVar("T")


class Repository(Generic[T], ABC):
    @abstractmethod
    def create(self, entity: T) -> T:
        raise NotImplementedError

    @abstractmethod
    def update(self, entity: T) -> T:
        raise NotImplementedError

    @abstractmethod
    def delete(self, id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_all(self) -> list[T]:
        raise NotImplementedError

    @abstractmethod
    def get_by_id(self, id: int) -> T | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_ids(self, ids: Iterable[int]) -> list[T]:
        raise NotImplementedError

    @abstractmethod
    def first(self, **kwargs) -> T | None:
        raise NotImplementedError

    @abstractmethod
    def filter_by(
        self, limit: int | None = None, offset: int | None = None, **kwargs
    ) -> list[T]:
        raise NotImplementedError

    @abstractmethod
    def count_by(self, **kwargs) -> int:
        raise NotImplementedError

    @abstractmethod
    def filter_by_spec(
        self,
        spec: Specification,
        order_by: str | None = None,
        desc_order: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[T]:
        raise NotImplementedError

    @abstractmethod
    def paginate(
        self, limit: int | None = None, offset: int | None = None, **kwargs
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    def paginate_by_spec(
        self, spec: Specification, limit: int | None = None, offset: int | None = None
    ) -> dict:
        raise NotImplementedError
