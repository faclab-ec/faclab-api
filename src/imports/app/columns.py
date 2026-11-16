"""Columnas de las plantillas de importación (S5.8) y cómo se lee cada celda.

Una plantilla es una lista de `Column`: el encabezado que va en el archivo (en
español, sin tildes), el campo del comando que llena y cómo se convierte el
texto de la celda. Es la única fuente de las plantillas descargables, de los
metadatos que muestra la pantalla y de la guía.

Una celda vacía es "sin valor": al crear, el registro toma el valor por defecto
del comando; al actualizar, conserva el que tiene.
"""

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

# Lo que guardan MoneyColumn y QuantityColumn: numeric(18, 6)
_INTEGER_DIGITS = 12
_SCALE = 6


class CellError(ValueError):
    """El texto de una celda no es un valor de su columna"""


Parser = Callable[[str], Any]


@dataclass(frozen=True)
class Column:
    name: str  # encabezado en el archivo
    field: str  # campo del comando
    description: str
    example: str = ""
    # Parte de la clave que identifica el registro (SKU, identificación)
    key: bool = False
    # Obligatoria para crear el registro; si además es clave, en cada fila
    required: bool = False
    parse: Parser = lambda value: value

    def dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "example": self.example,
            "key": self.key,
            "required": self.required,
        }


def header_name(value: object) -> str:
    """Un encabezado como lo escribió el usuario, comparable con la plantilla:
    sin tildes ni mayúsculas, con `_` en vez de espacios ("Precio venta" →
    "precio_venta")"""
    text = unicodedata.normalize("NFKD", str(value or "")).strip().lower()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return "_".join(text.replace("-", " ").split())


def text(max_length: int) -> Parser:
    def parse(value: str) -> str:
        if len(value) > max_length:
            raise CellError(f"Tiene más de {max_length} caracteres")
        return value

    return parse


def _decimal(value: str, scale: int) -> Decimal:
    raw = value.replace(" ", "")
    # Una coma es el separador decimal si no hay punto ("12,50"); con los dos
    # no se sabe cuál es el de miles
    if "," in raw and "." in raw:
        raise CellError("Use un solo separador decimal y ninguno de miles")
    raw = raw.replace(",", ".")
    try:
        number = Decimal(raw)
    except InvalidOperation:
        raise CellError(f"No es un número: {value}") from None
    if not number.is_finite():
        raise CellError(f"No es un número: {value}")
    exponent = number.normalize().as_tuple().exponent
    if isinstance(exponent, int) and -exponent > scale:
        raise CellError(f"Admite hasta {scale} decimales")
    if abs(number) >= Decimal(10) ** _INTEGER_DIGITS:
        raise CellError("Es demasiado grande")
    return number


def money(value: str) -> Decimal:
    """Un precio, costo o cupo: cero o más"""
    number = _decimal(value, _SCALE)
    if number < 0:
        raise CellError("No puede ser negativo")
    return number


def quantity(value: str) -> Decimal:
    """Una cantidad: cero o más; los decimales los limita la unidad del producto"""
    number = _decimal(value, _SCALE)
    if number < 0:
        raise CellError("No puede ser negativa")
    return number


def positive_quantity(value: str) -> Decimal:
    number = quantity(value)
    if number <= 0:
        raise CellError("Debe ser mayor que cero")
    return number


def whole(value: str) -> int:
    """Un entero de cero o más (días)"""
    number = _decimal(value, 0)
    if number < 0:
        raise CellError("No puede ser negativo")
    if number > 100_000:
        raise CellError("Es demasiado grande")
    return int(number)


_TRUE = {"si", "s", "true", "verdadero", "1", "x"}
_FALSE = {"no", "n", "false", "falso", "0"}


def boolean(value: str) -> bool:
    normalized = header_name(value)
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise CellError("Escriba SI o NO")


def choice(options: Mapping[str, Enum], label: str) -> Parser:
    """Uno de los valores de `options` (sin tildes ni mayúsculas)"""
    normalized = {header_name(key): option for key, option in options.items()}

    def parse(value: str) -> Enum:
        option = normalized.get(header_name(value))
        if option is None:
            raise CellError(f"{label} no válido: {value}")
        return option

    return parse


def parse_row(
    columns: tuple[Column, ...], data: Mapping[str, str | None]
) -> tuple[dict[str, Any], list[tuple[Column, str]]]:
    """Los valores de una fila por campo (solo las celdas llenas) y los errores
    de las que no se pudieron leer"""
    values: dict[str, Any] = {}
    errors: list[tuple[Column, str]] = []
    for column in columns:
        raw = data.get(column.name)
        if raw is None or raw == "":
            continue
        try:
            values[column.field] = column.parse(raw)
        except CellError as exc:
            errors.append((column, str(exc)))
    return values, errors
