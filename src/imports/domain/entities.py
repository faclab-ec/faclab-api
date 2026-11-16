"""Importación masiva de datos iniciales (S5.8).

Un trabajo de importación (`ImportJob`) nace al subir un archivo: se leen sus
filas, se valida cada una contra los datos de la empresa y se guardan con la
acción que tendrían (`ImportRow`), sin escribir nada del negocio. Si ninguna
tiene errores queda `VALIDATED` y quien lo subió lo confirma (`QUEUED`); el
worker lo ejecuta por lotes (`RUNNING`) con los comandos de cada módulo hasta
`COMPLETED`, o se detiene en la primera fila que falla (`FAILED`). Los lotes ya
hechos quedan escritos: volver a importar el archivo no duplica nada, porque
cada fila se identifica por su clave natural (SKU, identificación, código).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from src.imports.domain.exceptions import ImportNotConfirmableError
from src.shared.domain.entities import Entity


class ImportKind(StrEnum):
    """Qué se importa; cada uno tiene su plantilla"""

    PRODUCTS = "PRODUCTS"
    PRESENTATIONS = "PRESENTATIONS"
    PRICES = "PRICES"
    CUSTOMERS = "CUSTOMERS"
    SUPPLIERS = "SUPPLIERS"
    STOCK = "STOCK"


class ImportMode(StrEnum):
    """Qué hacer con una fila cuyo registro ya existe"""

    SKIP = "SKIP"  # saltarla: solo se crean los nuevos
    UPDATE = "UPDATE"  # actualizarlo con las celdas llenas de la fila


class ImportStatus(StrEnum):
    VALIDATED = "VALIDATED"  # sin errores, espera la confirmación
    INVALID = "INVALID"  # alguna fila tiene errores: no se puede confirmar
    QUEUED = "QUEUED"  # confirmado, espera al worker
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ImportRowAction(StrEnum):
    """Lo que la importación hace (o haría) con una fila"""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    UNCHANGED = "UNCHANGED"  # existe con los mismos valores: no se escribe
    SKIP = "SKIP"  # existe y el modo es SKIP
    ERROR = "ERROR"


@dataclass(frozen=True)
class RowError:
    """Un problema de una fila: la columna (None, la fila entera), un código y
    un mensaje para quien corrige el archivo"""

    column: str | None
    code: str
    message: str

    def dict(self) -> dict[str, Any]:
        return {"column": self.column, "code": self.code, "message": self.message}


def empty_counts() -> dict[str, int]:
    return {action.value: 0 for action in ImportRowAction}


@dataclass
class ImportJob(Entity):
    kind: ImportKind
    mode: ImportMode
    file_name: str
    file_size: int
    status: ImportStatus = ImportStatus.VALIDATED
    id: int | None = None
    total_rows: int = 0
    # Filas por acción al validar el archivo, y las que el worker ya hizo
    planned: dict[str, int] = field(default_factory=empty_counts)
    done: dict[str, int] = field(default_factory=empty_counts)
    processed_rows: int = 0
    # La última fila ejecutada: el siguiente lote empieza después de ella
    cursor_row: int = 0
    # Quien lo subió y desde qué sucursal: el worker lo ejecuta a su nombre
    user_id: int | None = None
    user_name: str | None = None
    branch_id: int | None = None
    # La solicitud que lo confirmó: las entradas de la bitácora que escribe el
    # worker la llevan
    request_id: str | None = None
    failed_row: int | None = None
    failure: str | None = None
    created_at: datetime | None = None
    confirmed_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def validated(
        cls,
        *,
        kind: ImportKind,
        mode: ImportMode,
        file_name: str,
        file_size: int,
        actions: list[ImportRowAction],
        user_id: int | None,
        user_name: str | None,
        branch_id: int | None,
    ) -> "ImportJob":
        planned = empty_counts()
        for action in actions:
            planned[action.value] += 1
        return cls(
            kind=kind,
            mode=mode,
            file_name=file_name,
            file_size=file_size,
            status=(
                ImportStatus.INVALID
                if planned[ImportRowAction.ERROR.value]
                else ImportStatus.VALIDATED
            ),
            total_rows=len(actions),
            planned=planned,
            user_id=user_id,
            user_name=user_name,
            branch_id=branch_id,
        )

    @property
    def in_progress(self) -> bool:
        return self.status in (ImportStatus.QUEUED, ImportStatus.RUNNING)

    def confirm(self, request_id: str | None, now: datetime) -> None:
        if self.status != ImportStatus.VALIDATED:
            raise ImportNotConfirmableError(self.id, self.status)
        self.status = ImportStatus.QUEUED
        self.request_id = request_id
        self.confirmed_at = now

    def start(self, now: datetime) -> None:
        if self.status == ImportStatus.QUEUED:
            self.status = ImportStatus.RUNNING
            self.started_at = now

    def advance(self, actions: list[ImportRowAction], last_row: int) -> None:
        """Un lote hecho: cuenta sus filas y mueve el cursor"""
        done = dict(self.done)
        for action in actions:
            done[action.value] = done.get(action.value, 0) + 1
        self.done = done
        self.processed_rows += len(actions)
        self.cursor_row = last_row

    def complete(self, now: datetime) -> None:
        self.status = ImportStatus.COMPLETED
        self.finished_at = now

    def fail(self, row: int | None, message: str, now: datetime) -> None:
        self.status = ImportStatus.FAILED
        self.failed_row = row
        self.failure = message[:512]
        self.finished_at = now


@dataclass
class ImportRow(Entity):
    """Una fila del archivo, con sus valores tal como venían (texto, por el
    encabezado de la plantilla). `row_number` es su línea en la hoja: la 1 es el
    encabezado."""

    job_id: int
    row_number: int
    data: dict[str, str | None]
    action: ImportRowAction
    id: int | None = None
    errors: list[dict[str, Any]] | None = None
    # El registro que creó o actualizó (producto, cliente, ajuste...)
    record_id: int | None = None
