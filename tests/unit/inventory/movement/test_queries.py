"""Unit tests for Movement query handlers"""

from datetime import datetime
from unittest.mock import ANY, Mock

import pytest

from src.inventory.movement.app.queries import (
    GetAllMovementsQuery,
    GetAllMovementsQueryHandler,
    GetMovementByIdQuery,
    GetMovementByIdQueryHandler,
)
from src.inventory.movement.domain.constants import MovementType
from src.inventory.movement.domain.entities import Movement
from src.shared.domain.exceptions import NotFoundError


def _movement(
    product_id: int = 1,
    type: MovementType = MovementType.IN,
    date: datetime | None = None,
) -> Movement:
    quantity = 1 if type == MovementType.IN else -1
    return Movement(product_id=product_id, quantity=quantity, type=type, date=date)


def _matches(repo, movement: Movement) -> bool:
    """Whether the spec the handler paginated by accepts the movement"""
    spec = repo.paginate_by_spec.call_args.args[0]
    return spec.is_satisfied_by(movement)


@pytest.fixture
def mock_movement_repo():
    """Mock repository for Movement"""
    repo = Mock()
    return repo


def test_get_all_movements_query_handler(mock_movement_repo):
    """Test getting all movements"""
    movements = [
        Movement(
            id=1,
            product_id=1,
            quantity=10,
            type=MovementType.IN,
            reason="Purchase",
        ),
        Movement(
            id=2,
            product_id=2,
            quantity=-5,
            type=MovementType.OUT,
            reason="Sale",
        ),
    ]
    mock_movement_repo.paginate_by_spec.return_value = {
        "total": 2,
        "limit": None,
        "offset": None,
        "items": [m.dict() for m in movements],
    }

    query = GetAllMovementsQuery()
    handler = GetAllMovementsQueryHandler(mock_movement_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == 1
    assert result["items"][1]["id"] == 2
    assert result["total"] == 2
    mock_movement_repo.paginate_by_spec.assert_called_once_with(
        ANY, limit=None, offset=None
    )


def test_get_all_movements_with_product_filter(mock_movement_repo):
    """Test getting movements filtered by product_id"""
    movements = [
        Movement(
            id=1,
            product_id=1,
            quantity=10,
            type=MovementType.IN,
        ),
    ]
    mock_movement_repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [m.dict() for m in movements],
    }

    query = GetAllMovementsQuery(product_id=1)
    handler = GetAllMovementsQueryHandler(mock_movement_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 1
    assert result["items"][0]["product_id"] == 1
    assert result["total"] == 1
    mock_movement_repo.paginate_by_spec.assert_called_once_with(
        ANY, limit=None, offset=None
    )
    assert _matches(mock_movement_repo, _movement(product_id=1))
    assert not _matches(mock_movement_repo, _movement(product_id=2))


def test_get_all_movements_with_type_filter(mock_movement_repo):
    """Test getting movements filtered by type"""
    movements = [
        Movement(
            id=1,
            product_id=1,
            quantity=10,
            type=MovementType.IN,
        ),
    ]
    mock_movement_repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [m.dict() for m in movements],
    }

    query = GetAllMovementsQuery(type=MovementType.IN.value)
    handler = GetAllMovementsQueryHandler(mock_movement_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 1
    assert result["items"][0]["type"] == MovementType.IN
    assert result["total"] == 1
    assert _matches(mock_movement_repo, _movement(product_id=1, type=MovementType.IN))
    assert not _matches(
        mock_movement_repo, _movement(product_id=1, type=MovementType.OUT)
    )


def test_get_all_movements_with_multiple_filters(mock_movement_repo):
    """Test getting movements with multiple filters"""
    movements = [
        Movement(
            id=1,
            product_id=1,
            quantity=10,
            type=MovementType.IN,
        ),
    ]
    mock_movement_repo.paginate_by_spec.return_value = {
        "total": 1,
        "limit": None,
        "offset": None,
        "items": [m.dict() for m in movements],
    }

    query = GetAllMovementsQuery(product_id=1, type=MovementType.IN.value)
    handler = GetAllMovementsQueryHandler(mock_movement_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 1
    assert result["total"] == 1
    assert _matches(mock_movement_repo, _movement(product_id=1, type=MovementType.IN))
    assert not _matches(
        mock_movement_repo, _movement(product_id=2, type=MovementType.IN)
    )
    assert not _matches(
        mock_movement_repo, _movement(product_id=1, type=MovementType.OUT)
    )


def test_get_all_movements_in_date_range(mock_movement_repo):
    """fromDate and toDate are both inclusive"""
    mock_movement_repo.paginate_by_spec.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }
    query = GetAllMovementsQuery(
        from_date=datetime(2026, 10, 1, 8, 0), to_date=datetime(2026, 10, 8, 18, 0)
    )

    GetAllMovementsQueryHandler(mock_movement_repo).handle(query)

    for date, expected in (
        (datetime(2026, 10, 1, 8, 0), True),
        (datetime(2026, 10, 8, 18, 0), True),
        (datetime(2026, 10, 1, 7, 59), False),
        (datetime(2026, 10, 8, 18, 1), False),
        (None, False),
    ):
        movement = _movement(date=date)
        assert _matches(mock_movement_repo, movement) is expected


def test_get_all_movements_empty(mock_movement_repo):
    """Test getting all movements when none exist"""
    mock_movement_repo.paginate_by_spec.return_value = {
        "total": 0,
        "limit": None,
        "offset": None,
        "items": [],
    }

    query = GetAllMovementsQuery()
    handler = GetAllMovementsQueryHandler(mock_movement_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 0
    assert result["total"] == 0
    mock_movement_repo.paginate_by_spec.assert_called_once_with(
        ANY, limit=None, offset=None
    )


def test_get_all_movements_with_pagination(mock_movement_repo):
    """Test getting movements with pagination"""
    movements = [
        Movement(
            id=1,
            product_id=1,
            quantity=10,
            type=MovementType.IN,
        ),
        Movement(
            id=2,
            product_id=2,
            quantity=-5,
            type=MovementType.OUT,
        ),
    ]
    mock_movement_repo.paginate_by_spec.return_value = {
        "total": 2,
        "limit": 10,
        "offset": 5,
        "items": [m.dict() for m in movements],
    }

    query = GetAllMovementsQuery(limit=10, offset=5)
    handler = GetAllMovementsQueryHandler(mock_movement_repo)

    result = handler.handle(query)

    assert len(result["items"]) == 2
    assert result["total"] == 2
    mock_movement_repo.paginate_by_spec.assert_called_once_with(ANY, limit=10, offset=5)


def test_get_movement_by_id_handler(mock_movement_repo):
    """Test getting a movement by ID"""
    movement = Movement(
        id=1,
        product_id=1,
        quantity=10,
        type=MovementType.IN,
        reason="Test",
        date=datetime.now(),
    )
    mock_movement_repo.get_by_id.return_value = movement

    query = GetMovementByIdQuery(id=1)
    handler = GetMovementByIdQueryHandler(mock_movement_repo)

    result = handler.handle(query)

    assert result is not None
    assert result["id"] == 1
    assert result["product_id"] == 1
    assert result["quantity"] == 10
    mock_movement_repo.get_by_id.assert_called_once_with(1)


def test_get_movement_by_id_not_found_raises(mock_movement_repo):
    """Test getting non-existent movement raises NotFoundError"""
    mock_movement_repo.get_by_id.return_value = None

    query = GetMovementByIdQuery(id=999)
    handler = GetMovementByIdQueryHandler(mock_movement_repo)

    with pytest.raises(NotFoundError):
        handler.handle(query)
    mock_movement_repo.get_by_id.assert_called_once_with(999)
