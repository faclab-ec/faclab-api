"""Excepciones de la importación masiva (S5.8)"""

from src.shared.domain.exceptions import ConflictError, DomainError, ValidationError


class ImportFileInvalidError(ValidationError):
    """El archivo no se puede importar tal como está: vacío, ilegible, con
    columnas que faltan o que la plantilla no tiene, o demasiado grande. Las
    filas no se validan hasta que el archivo se lee."""

    error_code = "IMPORT_FILE_INVALID"

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message=message, detail=detail)


class ImportNotConfirmableError(ConflictError):
    """Solo se confirma una importación validada sin errores, una vez"""

    error_code = "IMPORT_NOT_CONFIRMABLE"

    def __init__(self, job_id: int | None, status: str):
        super().__init__(
            message=f"Import {job_id} is {status}: only a VALIDATED import is confirmed",
            detail=f"status={status}",
        )


class ImportRowFailedError(DomainError):
    """Una fila falló al ejecutarse: los datos cambiaron desde la validación o
    un comando la rechazó. Su lote se revierte y la importación se detiene."""

    error_code = "IMPORT_ROW_FAILED"

    def __init__(self, row_number: int | None, message: str):
        self.row_number = row_number
        self.reason = message
        prefix = f"Row {row_number}: " if row_number is not None else ""
        super().__init__(message=f"{prefix}{message}", detail=f"row={row_number}")
