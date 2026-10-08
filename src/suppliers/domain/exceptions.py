from src.shared.domain.exceptions import AlreadyExistsError


class SupplierTaxIdAlreadyExistsError(AlreadyExistsError):
    error_code = "SUPPLIER_TAX_ID_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A supplier with this tax ID already exists")


class SupplierProductAlreadyExistsError(AlreadyExistsError):
    error_code = "SUPPLIER_PRODUCT_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("This product is already linked to the supplier")
