from src.shared.domain.exceptions import AlreadyExistsError


class CustomerTaxIdAlreadyExistsError(AlreadyExistsError):
    error_code = "CUSTOMER_TAX_ID_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A customer with this tax ID already exists")
