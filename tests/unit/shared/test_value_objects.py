import pytest

from src.shared.domain.value_objects import Email, TaxId


class TestEmail:
    def test_valid(self):
        email = Email(value="user@example.com")
        assert email.value == "user@example.com"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid email"):
            Email(value="not-an-email")


class TestTaxId:
    _error_match = "Invalid tax ID"

    def test_valid_ruc(self):
        tax_id = TaxId(value="1710034065001")
        assert tax_id.value == "1710034065001"

    def test_valid_cedula(self):
        tax_id = TaxId(value="1710034065")
        assert tax_id.value == "1710034065"

    def test_invalid_length_raises(self):
        with pytest.raises(ValueError, match=self._error_match):
            TaxId(value="12345")

    def test_non_digit_raises(self):
        with pytest.raises(ValueError, match=self._error_match):
            TaxId(value="17ABC34065")

    def test_invalid_province_raises(self):
        with pytest.raises(ValueError, match="Invalid ID or RUC"):
            TaxId(value="9910034065")

    def test_invalid_check_digit_raises(self):
        with pytest.raises(ValueError, match="Invalid ID or RUC"):
            TaxId(value="1710034060")
