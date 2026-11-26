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


class GraceNotEndedError(ConflictError):
    """The grace period of the offboarding is still running (S8.7)"""

    error_code = "OFFBOARDING_GRACE_NOT_ENDED"

    def __init__(self, ends_at):
        super().__init__(
            message="The grace period of the offboarding has not ended",
            detail=f"graceEndsAt={ends_at.isoformat()}",
        )


class RetentionNotEndedError(ConflictError):
    """What tax law makes us keep can't be deleted yet"""

    error_code = "OFFBOARDING_RETENTION_NOT_ENDED"

    def __init__(self, ends_at):
        super().__init__(
            message="The tax retention period of this company has not ended",
            detail=f"retentionEndsAt={ends_at.isoformat()}",
        )


class OffboardingStepError(ConflictError):
    """A step out of order: anonymizing before starting, purging before
    anonymizing, a confirmation that is not the company's RUC"""

    error_code = "OFFBOARDING_STEP_INVALID"

    def __init__(self, message: str):
        super().__init__(message=message)


class PendingMessagesError(ConflictError):
    """Messages for other services (an invoice request) are still in the outbox:
    anonymizing would lose them"""

    error_code = "OFFBOARDING_PENDING_MESSAGES"

    def __init__(self, count: int):
        super().__init__(
            message="There are messages for other services still to be published",
            detail=f"pending={count}",
        )
