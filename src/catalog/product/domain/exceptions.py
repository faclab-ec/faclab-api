from src.shared.domain.exceptions import (
    AlreadyExistsError,
    DomainError,
    InvalidValueError,
    ValidationError,
)
from src.shared.domain.tax import CONSTRUCTION_MATERIAL_TAX_CODE


class ProductSkuAlreadyExistsError(AlreadyExistsError):
    error_code = "PRODUCT_SKU_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A product with this SKU already exists")


class ProductBarcodeAlreadyExistsError(AlreadyExistsError):
    error_code = "PRODUCT_BARCODE_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("A product with this barcode already exists")


class ProductPresentationNameAlreadyExistsError(AlreadyExistsError):
    error_code = "PRODUCT_PRESENTATION_ALREADY_EXISTS"

    def __init__(self):
        super().__init__("The product already has a presentation with this name")


class InvalidPresentationFactorError(InvalidValueError):
    """El factor de conversión de una presentación tiene que ser mayor que cero"""

    def __init__(self):
        super().__init__(
            "The conversion factor of a presentation must be greater than zero"
        )


class BasePresentationFixedError(DomainError):
    """La presentación base es la unidad del producto: solo cambia su código de
    barras, y no se desactiva ni se borra"""

    error_code = "BASE_PRESENTATION_FIXED"

    def __init__(self, detail: str = "Only the barcode of a base presentation changes"):
        super().__init__(detail)


class PresentationInactiveError(DomainError):
    error_code = "PRESENTATION_INACTIVE"

    def __init__(self, presentation_id: int | None):
        super().__init__(f"Presentation {presentation_id} is inactive")


class UnitOfMeasureRequiredError(ValidationError):
    """Todo producto tiene su unidad base, en la que se lleva el stock (S5.2)"""

    def __init__(self):
        super().__init__("A product needs its unit of measure")


class ConstructionMaterialTaxMismatchError(DomainError):
    error_code = "CONSTRUCTION_MATERIAL_TAX_MISMATCH"

    def __init__(self):
        super().__init__(
            "A construction material must use the tax code "
            f"{CONSTRUCTION_MATERIAL_TAX_CODE.value}"
        )
