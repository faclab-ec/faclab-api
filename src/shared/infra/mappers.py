import dataclasses
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar, get_args, get_type_hints, overload

E = TypeVar("E")  # Entity
M = TypeVar("M")  # Model


def _extract_enum_type(hint) -> type[Enum] | None:
    """Extract Enum subclass from a type hint, handling Optional types."""
    if isinstance(hint, type) and issubclass(hint, Enum):
        return hint
    for arg in get_args(hint):
        if isinstance(arg, type) and issubclass(arg, Enum):
            return arg
    return None


class Mapper(Generic[E, M]):
    """Convention-based mapper: auto-maps fields by name between Entity and Model.

    Subclasses only need to declare:
      - __entity__: the dataclass type to construct
      - __exclude_fields__: fields to omit from to_dict (e.g. auto-generated timestamps)
    """

    __entity__: ClassVar[type[Any]]
    __exclude_fields__: ClassVar[frozenset[str]] = frozenset()
    _enum_fields: ClassVar[dict[str, type[Enum]]]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "__entity__"):
            hints = get_type_hints(cls.__entity__)
            cls._enum_fields = {
                name: enum_type
                for name, hint in hints.items()
                if (enum_type := _extract_enum_type(hint)) is not None
            }

    @overload
    def to_entity(self, model: M) -> E: ...

    @overload
    def to_entity(self, model: None) -> None: ...

    def to_entity(self, model: M | None) -> E | None:
        if model is None:
            return None
        kwargs = {}
        for field in dataclasses.fields(self.__entity__):
            value = getattr(model, field.name)
            if value is not None and field.name in self._enum_fields:
                value = self._enum_fields[field.name](value)
            kwargs[field.name] = value
        return self.__entity__(**kwargs)

    def to_dict(self, entity: E) -> dict[str, Any]:
        result = {}
        for field in dataclasses.fields(self.__entity__):
            if field.name in self.__exclude_fields__:
                continue
            value = getattr(entity, field.name)
            if field.name == "id" and value is None:
                continue
            if isinstance(value, Enum):
                value = value.value
            result[field.name] = value
        return result
