from decimal import Decimal

import pytest

from src.shared.domain.tax import TaxCode


@pytest.mark.parametrize(
    "code,expected_rate",
    [
        (TaxCode.VAT_0, Decimal("0")),
        (TaxCode.VAT_5, Decimal("5")),
        (TaxCode.VAT_8_TOURISM, Decimal("8")),
        (TaxCode.VAT_12, Decimal("12")),
        (TaxCode.VAT_13, Decimal("13")),
        (TaxCode.VAT_14, Decimal("14")),
        (TaxCode.VAT_15, Decimal("15")),
        (TaxCode.EXEMPT, Decimal("0")),
        (TaxCode.NOT_TAXED, Decimal("0")),
    ],
)
def test_tax_code_rate(code, expected_rate):
    assert code.rate == expected_rate


def test_all_codes_have_rate():
    """Cada miembro del enum expone una tarifa."""
    for code in TaxCode:
        assert isinstance(code.rate, Decimal)


def test_zero_rate_codes_are_distinct():
    """0%, exento y no objeto comparten tarifa 0 pero son códigos distintos."""
    zero_codes = {TaxCode.VAT_0, TaxCode.EXEMPT, TaxCode.NOT_TAXED}
    assert all(c.rate == Decimal("0") for c in zero_codes)
    assert len(zero_codes) == 3


def test_str_value_is_code_name():
    """Como StrEnum, su valor serializado es el código semántico."""
    assert TaxCode.VAT_15 == "VAT_15"
    assert str(TaxCode.VAT_15) == "VAT_15"
