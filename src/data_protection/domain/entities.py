"""Exportación de los datos de una empresa (S8.7, LOPDP: derecho de acceso y
portabilidad).

Un administrador pide la exportación (`QUEUED`); el worker arma un ZIP con un
CSV por tabla de la empresa y un `manifest.json` (`RUNNING`) y lo deja
descargable hasta `expires_at` (`READY`); después el archivo se borra
(`EXPIRED`). Una que falla queda `FAILED` con el tipo del error: se pide otra.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from src.shared.domain.entities import Entity


class ExportStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


@dataclass
class ExportJob(Entity):
    # Quien la pidió: el nombre sale del token, nunca del cuerpo
    requested_by_id: int | None = None
    requested_by_name: str | None = None
    status: ExportStatus = ExportStatus.QUEUED
    id: int | None = None
    # La solicitud que la pidió, para seguirla en los logs del worker
    request_id: str | None = None
    # El ZIP, dentro de la carpeta de exportaciones de la empresa
    file_name: str | None = None
    file_size: int | None = None
    # Filas por tabla del ZIP
    tables: dict[str, int] = field(default_factory=dict)
    failure: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None

    @property
    def in_progress(self) -> bool:
        return self.status in (ExportStatus.QUEUED, ExportStatus.RUNNING)
