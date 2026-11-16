from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from wireup import injectable

from src.imports.app.columns import header_name
from src.imports.app.kinds import TEMPLATES, KindImporters
from src.imports.app.repositories import ImportJobRepository, ImportRowRepository
from src.imports.domain.entities import (
    ImportJob,
    ImportKind,
    ImportMode,
    ImportRow,
    ImportRowAction,
)
from src.imports.domain.exceptions import ImportFileInvalidError
from src.shared.app.commands import Command, CommandHandler
from src.shared.domain.tenant import TenantContext

FILE_NAME_LENGTH = 255


@dataclass
class CreateImportCommand(Command):
    kind: ImportKind
    mode: ImportMode
    file_name: str
    file_size: int
    # The file's first row and the next ones, each with its line number
    header: Sequence[object]
    rows: Iterable[tuple[int, Sequence[str | None]]]
    max_rows: int


@injectable(lifetime="scoped")
class CreateImportCommandHandler(CommandHandler[CreateImportCommand, dict]):
    """Lee las filas de un archivo, las valida contra los datos de la empresa y
    las guarda con lo que harían (S5.8). No escribe nada del negocio: la
    importación queda VALIDATED (lista para confirmar) o INVALID (con el
    detalle por fila)."""

    def __init__(
        self,
        jobs: ImportJobRepository,
        rows: ImportRowRepository,
        importers: KindImporters,
        tenant: TenantContext,
    ):
        self.jobs = jobs
        self.rows = rows
        self.importers = importers
        self.tenant = tenant

    def _handle(self, command: CreateImportCommand) -> dict:
        positions = self._positions(command)
        rows = self._rows(command, positions)
        plans = self.importers.of(command.kind).plan(rows, command.mode)
        for row, plan in zip(rows, plans, strict=True):
            row.action = plan.action
            row.errors = [error.dict() for error in plan.errors] or None

        job = self.jobs.create(
            ImportJob.validated(
                kind=command.kind,
                mode=command.mode,
                file_name=command.file_name[:FILE_NAME_LENGTH],
                file_size=command.file_size,
                actions=[row.action for row in rows],
                user_id=self.tenant.user_id,
                user_name=self.tenant.user_name,
                branch_id=self.tenant.branch_id,
            )
        )
        for row in rows:
            row.job_id = job.require_id()
        self.rows.add_many(rows)
        return job.dict()

    @staticmethod
    def _positions(command: CreateImportCommand) -> dict[str, int]:
        """Dónde está cada columna de la plantilla en el archivo"""
        columns = TEMPLATES[command.kind]
        known = {column.name for column in columns}
        names = [header_name(cell) for cell in command.header]
        unknown = [
            str(cell)
            for cell, name in zip(command.header, names, strict=True)
            if name and name not in known
        ]
        if unknown:
            raise ImportFileInvalidError(
                "El archivo tiene columnas que la plantilla no tiene: "
                + ", ".join(unknown),
                detail=",".join(unknown),
            )
        repeated = sorted({name for name in names if name and names.count(name) > 1})
        if repeated:
            raise ImportFileInvalidError(
                "Columnas repetidas: " + ", ".join(repeated), detail=",".join(repeated)
            )
        # Updating needs only the key; creating, every required column
        required = [
            column.name
            for column in columns
            if column.required and (column.key or command.mode == ImportMode.SKIP)
        ]
        missing = [name for name in required if name not in names]
        if missing:
            raise ImportFileInvalidError(
                "Faltan columnas obligatorias: " + ", ".join(missing),
                detail=",".join(missing),
            )
        return {name: index for index, name in enumerate(names) if name}

    @staticmethod
    def _rows(
        command: CreateImportCommand, positions: dict[str, int]
    ) -> list[ImportRow]:
        rows: list[ImportRow] = []
        for row_number, cells in command.rows:
            data: dict[str, str | None] = {}
            for name, index in positions.items():
                value = cells[index] if index < len(cells) else None
                data[name] = value.strip() or None if value is not None else None
            if all(value is None for value in data.values()):
                continue
            if len(rows) >= command.max_rows:
                raise ImportFileInvalidError(
                    f"El archivo tiene más de {command.max_rows} filas: divídalo",
                    detail=f"max_rows={command.max_rows}",
                )
            rows.append(
                ImportRow(
                    job_id=0,
                    row_number=row_number,
                    data=data,
                    action=ImportRowAction.CREATE,
                )
            )
        if not rows:
            raise ImportFileInvalidError("El archivo no tiene filas con datos")
        return rows
