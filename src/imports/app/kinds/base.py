"""Lo común a los importadores de cada tipo (S5.8).

Un importador sabe dos cosas de su plantilla: planificar un grupo de filas
(leer sus celdas, validarlas contra los datos de la empresa y decidir si crean,
actualizan, no cambian o se saltan) y ejecutar las que crean o actualizan con
los comandos de su módulo. Se planifica al subir el archivo, sin escribir nada,
y otra vez en el worker antes de cada lote, porque los datos pudieron cambiar
desde entonces.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Generator, Hashable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar

import structlog

from src.imports.app.columns import Column, parse_row
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportMode,
    ImportRow,
    ImportRowAction,
    RowError,
)
from src.imports.domain.exceptions import ImportRowFailedError
from src.shared.domain.exceptions import BaseError
from src.shared.domain.quantity import decimals_of

logger = structlog.get_logger(__name__)

# Códigos de los errores por fila
REQUIRED = "REQUIRED"
INVALID_VALUE = "INVALID_VALUE"
DUPLICATE_IN_FILE = "DUPLICATE_IN_FILE"
NOT_FOUND = "NOT_FOUND"
ALREADY_IN_USE = "ALREADY_IN_USE"
NOT_ALLOWED = "NOT_ALLOWED"

# Lo que la importación escribe
WRITES = (ImportRowAction.CREATE, ImportRowAction.UPDATE)


@dataclass
class RowPlan:
    """Lo que se hará con una fila: su acción, sus errores y los campos del
    comando que la ejecuta (`payload`)"""

    row_number: int
    values: dict[str, Any]
    action: ImportRowAction = ImportRowAction.CREATE
    errors: list[RowError] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    # El registro que ya existe con su clave, y el que quedó al ejecutarla
    target_id: int | None = None
    record_id: int | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, column: Column | None, code: str, message: str) -> None:
        self.errors.append(RowError(column.name if column else None, code, message))

    def has(self, column: Column) -> bool:
        return column.field in self.values

    def get(self, column: Column, default: Any = None) -> Any:
        return self.values.get(column.field, default)


class KindImporter(ABC):
    kind: ClassVar[ImportKind]
    columns: ClassVar[tuple[Column, ...]]

    def plan(self, rows: Sequence[ImportRow], mode: ImportMode) -> list[RowPlan]:
        plans = [self._read(row) for row in rows]
        self._plan([plan for plan in plans if plan.ok], mode)
        for plan in plans:
            if plan.errors:
                plan.action = ImportRowAction.ERROR
        return plans

    def _read(self, row: ImportRow) -> RowPlan:
        values, problems = parse_row(self.columns, row.data)
        plan = RowPlan(row.row_number, values)
        for column, message in problems:
            plan.error(column, INVALID_VALUE, message)
        for column in self.columns:
            if column.key and not plan.has(column) and column.required:
                plan.error(column, REQUIRED, f"La columna {column.name} es obligatoria")
        return plan

    @abstractmethod
    def _plan(self, plans: list[RowPlan], mode: ImportMode) -> None:
        """Valida las filas que se pudieron leer y fija su acción"""

    @abstractmethod
    def execute(self, job: ImportJob, plans: list[RowPlan]) -> None:
        """Escribe las filas que crean o actualizan y fija su `record_id`"""

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def require(plan: RowPlan, *columns: Column) -> bool:
        """Las columnas obligatorias para crear: un error por cada una vacía"""
        missing = [column for column in columns if not plan.has(column)]
        for column in missing:
            plan.error(
                column,
                REQUIRED,
                f"La columna {column.name} es obligatoria para crear el registro",
            )
        return not missing

    @staticmethod
    def unique_in_file(
        plans: list[RowPlan],
        key: Callable[[RowPlan], Hashable | None],
        column: Column | None,
        what: str,
    ) -> None:
        """Marca las filas que repiten la clave de una anterior"""
        seen: dict[Hashable, int] = {}
        for plan in plans:
            value = key(plan)
            if value is None:
                continue
            if value in seen:
                plan.error(
                    column,
                    DUPLICATE_IN_FILE,
                    f"{what} ya está en la fila {seen[value]}",
                )
            else:
                seen[value] = plan.row_number

    @staticmethod
    def settle(plan: RowPlan, mode: ImportMode, changed: bool) -> None:
        """La acción de una fila cuyo registro ya existe"""
        if mode == ImportMode.SKIP:
            plan.action = ImportRowAction.SKIP
        elif changed:
            plan.action = ImportRowAction.UPDATE
        else:
            plan.action = ImportRowAction.UNCHANGED

    @staticmethod
    def fits_decimals(
        plan: RowPlan, column: Column, value: Any, decimals: int, unit: str
    ) -> bool:
        if value is None or decimals_of(Decimal(value)) <= decimals:
            return True
        allowed = "solo enteros" if decimals == 0 else f"hasta {decimals} decimales"
        plan.error(
            column,
            INVALID_VALUE,
            f"La unidad {unit} admite {allowed}",
        )
        return False

    @staticmethod
    def writes(plans: list[RowPlan]) -> list[RowPlan]:
        return [plan for plan in plans if plan.action in WRITES]

    @contextmanager
    def row(self, plan: RowPlan | None, label: str | None = None) -> Generator[None]:
        """Ejecuta una fila (o un grupo, sin fila): lo que falla detiene la
        importación con su número y el mensaje del error"""
        try:
            yield
        except ImportRowFailedError:
            raise
        except BaseError as exc:
            raise ImportRowFailedError(
                plan.row_number if plan else None, _label(label, exc.message)
            ) from exc
        except Exception as exc:
            logger.exception(
                "import_row_failed",
                import_kind=self.kind.value,
                row=plan.row_number if plan else None,
            )
            raise ImportRowFailedError(
                plan.row_number if plan else None,
                _label(label, f"Error inesperado ({type(exc).__name__})"),
            ) from exc


def _label(label: str | None, message: str) -> str:
    return f"{label}: {message}" if label else message
