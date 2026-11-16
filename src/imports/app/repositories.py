from abc import abstractmethod
from collections.abc import Iterable

from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportRow,
    ImportRowAction,
    ImportStatus,
)
from src.shared.app.repositories import Repository


class ImportJobRepository(Repository[ImportJob]):
    @abstractmethod
    def lock_for_run(self, job_id: int) -> ImportJob | None:
        """El trabajo, bloqueado hasta el fin de la transacción; None si otro
        worker lo tiene (SKIP LOCKED) o no existe"""

    @abstractmethod
    def page(
        self,
        kind: ImportKind | None,
        status: ImportStatus | None,
        limit: int,
        offset: int,
    ) -> dict:
        """Los trabajos, el último primero, con su total"""


class ImportRowRepository(Repository[ImportRow]):
    @abstractmethod
    def add_many(self, rows: Iterable[ImportRow]) -> None:
        """Inserta las filas de un trabajo en bloques, sin leerlas de vuelta"""

    @abstractmethod
    def after(self, job_id: int, row_number: int, limit: int) -> list[ImportRow]:
        """Las siguientes `limit` filas después de `row_number`, en orden"""

    @abstractmethod
    def record_results(
        self, results: Iterable[tuple[int, ImportRowAction, int | None]]
    ) -> None:
        """Lo que se hizo con cada fila: (id de la fila, acción, registro)"""

    @abstractmethod
    def page(
        self, job_id: int, action: ImportRowAction | None, limit: int, offset: int
    ) -> dict:
        """Las filas de un trabajo en orden, con su total"""

    @abstractmethod
    def with_errors(self, job_id: int) -> list[ImportRow]:
        """Las filas con errores, en orden"""
