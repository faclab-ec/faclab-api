import pytest

from src.organization.domain.entities import Branch, EmissionPoint
from src.shared.domain.exceptions import InvalidValueError


@pytest.mark.parametrize("code", ["001", "010", "999", " 002 "])
def test_an_sri_code_has_three_digits_from_001_to_999(code):
    assert Branch(establishment_code=code, name="Matriz").establishment_code == (
        code.strip()
    )
    assert EmissionPoint(branch_id=1, code=code).code == code.strip()


@pytest.mark.parametrize("code", ["000", "1", "01", "1000", "abc", "0a1", ""])
def test_any_other_code_is_rejected(code):
    with pytest.raises(InvalidValueError):
        Branch(establishment_code=code, name="Matriz")
    with pytest.raises(InvalidValueError):
        EmissionPoint(branch_id=1, code=code)
