from dataclasses import dataclass

import pytest

from src.shared.domain.entities import Entity


@dataclass
class _Thing(Entity):
    name: str
    id: int | None = None


def test_require_id_returns_id_of_persisted_entity():
    """Test require_id returns the id when the entity has been persisted."""
    assert _Thing(name="a", id=7).require_id() == 7


def test_require_id_raises_for_unpersisted_entity():
    """Test require_id raises when the entity has no id yet."""
    with pytest.raises(RuntimeError, match="_Thing has no id"):
        _Thing(name="a").require_id()


def test_entity_id_annotation_does_not_change_dataclass_fields():
    """Test the base id annotation leaves subclass fields and dict() intact."""
    thing = _Thing(name="a", id=7)
    assert thing.dict() == {"name": "a", "id": 7}
