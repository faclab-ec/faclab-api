"""The cost a manual movement takes (S5.6)"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.inventory.movement.domain.exceptions import InvalidMovementTypeError
from src.inventory.movement.infra.validators import MovementRequest, MovementResponse


def test_an_in_takes_its_unit_cost_as_a_decimal():
    request = MovementRequest.model_validate(
        {"productId": 1, "quantity": 5, "type": "IN", "unitCost": "6.125"}
    )

    # Handed to the command as it came, not as a float
    assert request.model_dump()["unit_cost"] == Decimal("6.125")


def test_an_out_takes_no_unit_cost():
    with pytest.raises(InvalidMovementTypeError):
        MovementRequest.model_validate(
            {"productId": 1, "quantity": -5, "type": "OUT", "unitCost": 1}
        )


@pytest.mark.parametrize("cost", ["-1", "0.0000001"])
def test_a_unit_cost_is_not_negative_and_has_six_decimals_at_most(cost):
    with pytest.raises(ValidationError):
        MovementRequest.model_validate(
            {"productId": 1, "quantity": 5, "type": "IN", "unitCost": cost}
        )


def test_the_response_answers_the_cost_it_moved_at():
    response = MovementResponse.model_validate(
        {
            "id": 1,
            "product_id": 1,
            "quantity": Decimal(-2),
            "type": "OUT",
            "unit_cost": Decimal("6.5"),
        }
    )

    assert response.model_dump(mode="json", by_alias=True)["unitCost"] == 6.5
