from dataclasses import dataclass

from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError
from src.shared.domain.quantity import MAX_QUANTITY_DECIMALS


@dataclass
class UnitOfMeasure(Entity):
    name: str
    symbol: str
    id: int | None = None
    description: str | None = None
    is_active: bool = True
    # Decimales que admiten las cantidades en esta unidad: 0 para unidades
    # enteras, 2 para metros, 3 para kilos (S5.1)
    decimals: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.decimals <= MAX_QUANTITY_DECIMALS:
            raise InvalidValueError(
                f"A unit of measure takes from 0 to {MAX_QUANTITY_DECIMALS} decimals"
            )
