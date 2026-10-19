import re
from dataclasses import dataclass
from datetime import datetime

from src.shared.domain.entities import Entity
from src.shared.domain.exceptions import InvalidValueError

_SRI_CODE = re.compile(r"\d{3}")


def sri_code(value: str, label: str) -> str:
    """Código de establecimiento o de punto de emisión del SRI: tres dígitos,
    de 001 a 999"""
    value = (value or "").strip()
    if not _SRI_CODE.fullmatch(value) or value == "000":
        raise InvalidValueError(f"{label} must be three digits from 001 to 999")
    return value


@dataclass
class Branch(Entity):
    """Una sucursal: un establecimiento SRI de la empresa"""

    establishment_code: str
    name: str
    id: int | None = None
    address: str | None = None
    is_main: bool = False
    is_active: bool = True
    created_at: datetime | None = None

    def __post_init__(self):
        self.establishment_code = sri_code(
            self.establishment_code, "establishment code"
        )


@dataclass
class EmissionPoint(Entity):
    """Un punto de emisión SRI de una sucursal"""

    branch_id: int
    code: str
    id: int | None = None
    name: str | None = None
    is_active: bool = True
    created_at: datetime | None = None

    def __post_init__(self):
        self.code = sri_code(self.code, "emission point code")


@dataclass
class PosTerminal(Entity):
    """Una caja del POS: emite por un punto de emisión de su sucursal y
    descuenta stock de una ubicación de una bodega de esa sucursal"""

    branch_id: int
    emission_point_id: int
    default_location_id: int
    code: str
    name: str
    id: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
