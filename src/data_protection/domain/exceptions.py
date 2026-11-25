"""Excepciones de la exportación de datos (S8.7)"""

from src.shared.domain.exceptions import ConflictError


class ExportInProgressError(ConflictError):
    """Una exportación por empresa a la vez: la anterior sigue en cola o en curso"""

    error_code = "EXPORT_IN_PROGRESS"

    def __init__(self, job_id: int | None):
        super().__init__(
            message="A data export is already in progress for this company",
            detail=f"exportId={job_id}",
        )


class ExportNotReadyError(ConflictError):
    """Solo se descarga una exportación `READY`: la otra aún se arma, falló o
    ya venció (pida una nueva)"""

    error_code = "EXPORT_NOT_READY"

    def __init__(self, job_id: int | None, status: str):
        super().__init__(
            message=f"Export {job_id} is {status}: only a READY export is downloaded",
            detail=f"status={status}",
        )
