from src.shared.domain.exceptions import (
    AlreadyExistsError,
    ConflictError,
    ValidationError,
)


class BranchEstablishmentCodeAlreadyExistsError(AlreadyExistsError):
    error_code = "BRANCH_ESTABLISHMENT_CODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A branch with this establishment code already exists")


class MainBranchAlreadyExistsError(AlreadyExistsError):
    error_code = "MAIN_BRANCH_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("The tenant already has a main branch")


class EmissionPointCodeAlreadyExistsError(AlreadyExistsError):
    error_code = "EMISSION_POINT_CODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("The branch already has an emission point with this code")


class PosTerminalCodeAlreadyExistsError(AlreadyExistsError):
    error_code = "POS_TERMINAL_CODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("The branch already has a POS terminal with this code")


class MainBranchDeletionError(ConflictError):
    error_code = "MAIN_BRANCH_DELETION"

    def __init__(self):
        super().__init__("The main branch can't be deleted")


class BranchInactiveError(ConflictError):
    error_code = "BRANCH_INACTIVE"

    def __init__(self, branch_id: int):
        super().__init__(f"Branch {branch_id} is inactive")


class EmissionPointOutsideBranchError(ValidationError):
    error_code = "EMISSION_POINT_OUTSIDE_BRANCH"

    def __init__(self):
        super().__init__("The emission point belongs to another branch")


class LocationOutsideBranchError(ValidationError):
    error_code = "LOCATION_OUTSIDE_BRANCH"

    def __init__(self):
        super().__init__("The location is in a warehouse of another branch")
