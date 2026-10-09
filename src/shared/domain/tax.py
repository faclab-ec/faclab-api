from decimal import Decimal
from enum import IntEnum, StrEnum


class TaxCode(StrEnum):
    """Código semántico de IVA.

    El porcentaje por sí solo es ambiguo: 0%, exento y no objeto de impuesto
    comparten tarifa 0. El código resuelve esa ambigüedad para que el servicio
    de facturación lo traduzca a la nomenclatura del SRI.
    """

    VAT_0 = "VAT_0"
    VAT_5 = "VAT_5"
    VAT_8_TOURISM = "VAT_8_TOURISM"
    VAT_12 = "VAT_12"
    VAT_13 = "VAT_13"
    VAT_14 = "VAT_14"
    VAT_15 = "VAT_15"
    EXEMPT = "EXEMPT"
    NOT_TAXED = "NOT_TAXED"

    @property
    def rate(self) -> Decimal:
        """Tarifa de IVA asociada al código, como porcentaje (0-100)."""
        return _RATES[self]


_RATES = {
    TaxCode.VAT_0: Decimal("0"),
    TaxCode.VAT_5: Decimal("5"),
    TaxCode.VAT_8_TOURISM: Decimal("8"),
    TaxCode.VAT_12: Decimal("12"),
    TaxCode.VAT_13: Decimal("13"),
    TaxCode.VAT_14: Decimal("14"),
    TaxCode.VAT_15: Decimal("15"),
    TaxCode.EXEMPT: Decimal("0"),
    TaxCode.NOT_TAXED: Decimal("0"),
}


class TaxType(IntEnum):
    """Tipo de identificación tributaria de un cliente o proveedor"""

    RUC = 1
    NATIONAL_ID = 2  # Cédula
    PASSPORT = 3  # Pasaporte
    FOREIGN_ID = 4  # Identificación de extranjero
