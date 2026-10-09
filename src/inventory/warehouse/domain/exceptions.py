from src.shared.domain.exceptions import AlreadyExistsError


class WarehouseCodeAlreadyExistsError(AlreadyExistsError):
    error_code = "WAREHOUSE_CODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A warehouse with this code already exists")
