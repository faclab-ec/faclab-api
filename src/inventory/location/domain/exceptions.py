from src.shared.domain.exceptions import AlreadyExistsError


class LocationCodeAlreadyExistsError(AlreadyExistsError):
    error_code = "LOCATION_CODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A location with this code already exists in the warehouse")
