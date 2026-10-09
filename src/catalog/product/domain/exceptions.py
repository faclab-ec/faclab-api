from src.shared.domain.exceptions import AlreadyExistsError


class ProductSkuAlreadyExistsError(AlreadyExistsError):
    error_code = "PRODUCT_SKU_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A product with this SKU already exists")


class ProductBarcodeAlreadyExistsError(AlreadyExistsError):
    error_code = "PRODUCT_BARCODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A product with this barcode already exists")
