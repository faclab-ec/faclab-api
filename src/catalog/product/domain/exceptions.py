from src.shared.domain.exceptions import AlreadyExistsError, DomainError
from src.shared.domain.tax import CONSTRUCTION_MATERIAL_TAX_CODE


class ProductSkuAlreadyExistsError(AlreadyExistsError):
    error_code = "PRODUCT_SKU_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A product with this SKU already exists")


class ProductBarcodeAlreadyExistsError(AlreadyExistsError):
    error_code = "PRODUCT_BARCODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A product with this barcode already exists")


class ConstructionMaterialTaxMismatchError(DomainError):
    error_code = "CONSTRUCTION_MATERIAL_TAX_MISMATCH"

    def __init__(self):
        super().__init__(
            "A construction material must use the tax code "
            f"{CONSTRUCTION_MATERIAL_TAX_CODE.value}"
        )
