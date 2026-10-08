from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import asc, desc, func
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from src.shared.app.repositories import Repository
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import NotFoundError
from src.shared.domain.specifications import Specification
from src.shared.infra.mappers import Mapper

E = TypeVar("E", bound="Entity")

Criteria = list[BinaryExpression | BooleanClauseList | Any]
OrderCriteria = str | Any


class SqlAlchemyRepository(Repository[E], Generic[E]):
    __model__: ClassVar[type[Any]]

    def __init__(self, session: Session, mapper: Mapper[E, Any]):
        self.session = session
        self.mapper = mapper

    def _save(self) -> None:
        self.session.flush()

    def create(self, entity: E) -> E:
        """
        Creates a new entity.
        Args:
            entity: Entity to create
        Returns:
            Created entity
        """
        model = self.__model__(**self.mapper.to_dict(entity))
        self.session.add(model)
        self._save()
        return self.mapper.to_entity(model)

    def update(self, entity: E) -> E:
        """
        Updates an entity.
        Args:
            entity: Entity to update
        Returns:
            Updated entity
        Raises:
            ValueError: If entity with given ID does not exist
        """
        model = self.session.query(self.__model__).get(entity.id)
        if not model:
            raise NotFoundError(f"Entity with id {entity.id} not found")

        for key, value in self.mapper.to_dict(entity).items():
            setattr(model, key, value)
        self._save()
        return self.mapper.to_entity(model)

    def delete(self, id: int) -> None:
        """
        Deletes an entity.
        Args:
            id: ID of the entity to delete
        Raises:
            ValueError: If entity with given ID does not exist
        """
        model = self.session.query(self.__model__).get(id)
        if not model:
            raise NotFoundError(f"Entity with id {id} not found")

        self.session.delete(model)
        self._save()

    def get_by_id(self, id: int) -> E | None:
        """
        Retrieves an entity by its ID.
        Args:
            id: ID of the entity to retrieve
        Returns:
            Entity if found, None otherwise
        """
        model = self.session.query(self.__model__).get(id)
        return self.mapper.to_entity(model)

    def get_all(self) -> list[E]:
        """
        Retrieves all entities.
        Returns:
            List of all entities
        """
        models = self.session.query(self.__model__).all()
        return [self.mapper.to_entity(model) for model in models]

    def first(self, **kwargs) -> E | None:
        """
        Retrieves the first entity that matches the given criteria.
        Args:
            criteria: List of conditions to filter by
        Returns:
            First entity that matches the criteria, or None if no entity is found
        """
        criteria = [
            getattr(self.__model__, key) == value for key, value in kwargs.items()
        ]
        model = self.session.query(self.__model__).filter(*criteria).first()
        return self.mapper.to_entity(model)

    def filter(
        self,
        criteria: Criteria,
        order_by: OrderCriteria | None = None,
        desc_order: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[E]:
        """
        Filters entities according to given criteria

        Args:
            criteria: List of conditions to filter by
            order_by: Field or expression to order by
            desc_order: If True, orders in descending order
            limit: Maximum number of results to return

        Returns:
            List of entities that match the criteria
        """
        query = self.session.query(self.__model__)
        query = query.filter(*criteria)

        if order_by:
            if isinstance(order_by, str):
                order_by = getattr(self.__model__, order_by)

            if desc_order:
                query = query.order_by(desc(order_by))
            else:
                query = query.order_by(asc(order_by))

        if limit is not None:
            query = query.limit(limit)

        if offset is not None:
            query = query.offset(offset)

        models = query.all()
        return [self.mapper.to_entity(model) for model in models]

    def count_by(self, **kwargs) -> int:
        """
        Counts entities by given keyword arguments.
        Args:
            **kwargs: Keyword arguments to filter by
        Returns:
            Count of entities that match the criteria
        """
        query = self.session.query(func.count(self.__model__.id))
        for key, value in kwargs.items():
            query = query.filter(getattr(self.__model__, key) == value)
        return query.scalar()

    def filter_by(self, limit=None, offset=None, **kwargs) -> list[E]:
        """
        Filters entities by given keyword arguments.
        Args:
            limit: Maximum number of results to return
            offset: Number of results to skip
            **kwargs: Keyword arguments to filter by
        Returns:
            List of entities that match the criteria
        """
        filter_criteria = []
        for key, value in kwargs.items():
            filter_criteria.append(getattr(self.__model__, key) == value)
        return self.filter(criteria=filter_criteria, limit=limit, offset=offset)

    def filter_by_spec(
        self,
        spec: Specification,
        order_by: OrderCriteria | None = None,
        desc_order: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[E]:
        criteria = spec.to_query_criteria()
        return self.filter(
            criteria=criteria,
            order_by=order_by,
            desc_order=desc_order,
            limit=limit,
            offset=offset,
        )

    def count_by_spec(self, spec: Specification) -> int:
        criteria = spec.to_query_criteria()
        return (
            self.session.query(func.count(self.__model__.id)).filter(*criteria).scalar()
        )

    def paginate(self, limit=None, offset=None, **kwargs) -> dict:
        items = self.filter_by(limit=limit, offset=offset, **kwargs)
        total = self.count_by(**kwargs)
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [item.dict() for item in items],
        }

    def paginate_by_spec(self, spec, limit=None, offset=None) -> dict:
        items = self.filter_by_spec(spec, limit=limit, offset=offset)
        total = self.count_by_spec(spec)
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [item.dict() for item in items],
        }
