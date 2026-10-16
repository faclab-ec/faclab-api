from collections.abc import Callable, Iterable
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import asc, desc, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

from src.shared.app.repositories import Repository
from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import AlreadyExistsError, NotFoundError
from src.shared.domain.specifications import Specification
from src.shared.domain.tenant import TenantMismatchError, require_tenant
from src.shared.infra.mappers import Mapper
from src.shared.infra.tenant import tenant_criteria

E = TypeVar("E", bound="Entity")

Criteria = list[BinaryExpression | BooleanClauseList | Any]
OrderCriteria = str | Any


class SqlAlchemyRepository(Repository[E], Generic[E]):
    """Base repository.

    A model whose class declares `__tenant_scoped__ = True` (and has a
    `tenant_id` column) belongs to a tenant: `create` takes the tenant from the
    context and every read, update and delete only sees that tenant's rows, so
    another tenant's id is simply not found. Without a context they raise
    `TenantContextRequiredError`. Queries that subclasses write themselves are
    not covered: they add `tenant_criteria(...)` explicitly.
    """

    __model__: ClassVar[type[Any]]
    # Unique constraint (or unique index) name -> error raised when it is violated
    __unique_errors__: ClassVar[dict[str, Callable[[], AlreadyExistsError]]] = {}

    def __init__(self, session: Session, mapper: Mapper[E, Any]):
        self.session = session
        self.mapper = mapper

    @property
    def _tenant_scoped(self) -> bool:
        return getattr(self.__model__, "__tenant_scoped__", False)

    def _tenant_criteria(self) -> Criteria:
        """The tenant filter every read of a tenant-scoped model adds"""
        if not self._tenant_scoped:
            return []
        return tenant_criteria(self.__model__)

    def _query(self, *columns: Any) -> Query:
        """Query of the model (or of `columns`), limited to the context tenant"""
        query = self.session.query(*(columns or (self.__model__,)))
        criteria = self._tenant_criteria()
        return query.filter(*criteria) if criteria else query

    def _get_model(self, id: int | None) -> Any:
        if not self._tenant_scoped:
            return self.session.get(self.__model__, id)
        return self._query().filter(self.__model__.id == id).first()

    def _values(self, entity: E, creating: bool) -> dict[str, Any]:
        """The entity's columns; for a tenant-scoped model the tenant always
        comes from the context, and an entity carrying another one is rejected."""
        values = self.mapper.to_dict(entity)
        if not self._tenant_scoped:
            return values
        tenant_id = require_tenant(f"writing {self.__model__.__name__}").tenant_id
        given = values.pop("tenant_id", None)
        if given is not None and given != tenant_id:
            raise TenantMismatchError(given, tenant_id)
        if creating:
            values["tenant_id"] = tenant_id
        return values

    def _save(self) -> None:
        try:
            self.session.flush()
        except IntegrityError as exc:
            diag = getattr(exc.orig, "diag", None)
            error = self.__unique_errors__.get(getattr(diag, "constraint_name", ""))
            if error is None:
                raise
            raise error() from exc

    def create(self, entity: E) -> E:
        """
        Creates a new entity.
        Args:
            entity: Entity to create
        Returns:
            Created entity
        """
        model = self.__model__(**self._values(entity, creating=True))
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
        values = self._values(entity, creating=False)
        model = self._get_model(entity.id)
        if not model:
            raise NotFoundError(f"Entity with id {entity.id} not found")

        for key, value in values.items():
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
        model = self._get_model(id)
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
        return self.mapper.to_entity(self._get_model(id))

    def get_by_ids(self, ids: Iterable[int]) -> list[E]:
        """
        Retrieves the entities with the given IDs in a single query.
        Args:
            ids: IDs to look up; missing IDs are skipped
        Returns:
            Entities found, in no particular order
        """
        unique_ids = set(ids)
        if not unique_ids:
            return []
        return self.filter(criteria=[self.__model__.id.in_(unique_ids)])

    def get_all(self) -> list[E]:
        """
        Retrieves all entities.
        Returns:
            List of all entities
        """
        models = self._query().all()
        return [self.mapper.to_entity(model) for model in models]

    def first(self, **kwargs) -> E | None:
        """
        Retrieves the first entity that matches the given criteria.
        Args:
            criteria: List of conditions to filter by
        Returns:
            First entity that matches the criteria, or None if no entity is found
        """
        return self._first(kwargs, for_update=False)

    def first_for_update(self, **kwargs) -> E | None:
        """
        Like first(), but locks the row (SELECT ... FOR UPDATE) until the
        transaction ends, so a concurrent request that wants to change it
        waits instead of overwriting this one's update.
        """
        return self._first(kwargs, for_update=True)

    def _first(self, filters: dict[str, Any], for_update: bool) -> E | None:
        criteria = [
            getattr(self.__model__, key) == value for key, value in filters.items()
        ]
        query = self._query().filter(*criteria)
        if for_update:
            query = query.with_for_update()
        return self.mapper.to_entity(query.first())

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
        query = self._query().filter(*criteria)

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
        query = self._query(func.count(self.__model__.id))
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
        return self._query(func.count(self.__model__.id)).filter(*criteria).scalar()

    def paginate(self, limit=None, offset=None, **kwargs) -> dict:
        items = self.filter_by(limit=limit, offset=offset, **kwargs)
        total = self.count_by(**kwargs)
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [item.dict() for item in items],
        }

    def paginate_by_spec(
        self,
        spec: Specification,
        limit: int | None = None,
        offset: int | None = None,
        order_by: OrderCriteria | None = None,
        desc_order: bool = False,
    ) -> dict:
        items = self.filter_by_spec(
            spec,
            order_by=order_by,
            desc_order=desc_order,
            limit=limit,
            offset=offset,
        )
        total = self.count_by_spec(spec)
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [item.dict() for item in items],
        }
