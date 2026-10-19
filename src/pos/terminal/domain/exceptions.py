from src.shared.domain.exceptions import (
    ApplicationError,
    ConflictError,
    ValidationError,
)


class TerminalRequiredError(ApplicationError):
    """A terminal operation without `X-Terminal-Id`, or, with the local
    fallback, in a branch without an active terminal"""

    error_code = "TERMINAL_REQUIRED"

    def __init__(self, message: str = "this operation needs the X-Terminal-Id header"):
        super().__init__(message)


class InvalidTerminalHeaderError(ApplicationError):
    error_code = "INVALID_TERMINAL_HEADER"

    def __init__(self, message: str = "X-Terminal-Id must be a POS terminal id"):
        super().__init__(message)


class PosTerminalOutsideBranchError(ValidationError):
    error_code = "POS_TERMINAL_OUTSIDE_BRANCH"

    def __init__(self):
        super().__init__("The POS terminal belongs to another branch")


class PosTerminalInactiveError(ConflictError):
    error_code = "POS_TERMINAL_INACTIVE"

    def __init__(self, terminal_id: int):
        super().__init__(f"POS terminal {terminal_id} is inactive")
