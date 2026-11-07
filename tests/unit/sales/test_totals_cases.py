"""The cases shared with faclab-web (S5.1): the cart of the POS and the core
compute the same totals, to the cent, with decimal quantities. The web keeps an
identical copy of the file (src/features/pos/model/__tests__/sale-totals.cases.json)."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from src.sales.domain.entities import Sale, SaleItem
from src.shared.domain.tax import TaxCode

CASES = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "sale_totals_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]
# What the database keeps of each line (numeric(18, 6))
SCALE = Decimal("0.000001")


def _totals(case: dict[str, Any], persisted: bool) -> dict[str, Decimal]:
    items = []
    for product_id, line in enumerate(case["items"], start=1):
        item = SaleItem(
            sale_id=1,
            product_id=product_id,
            quantity=Decimal(line["quantity"]),
            unit_price=Decimal(line["unitPrice"]),
            discount=Decimal(line["discount"]),
            tax_code=TaxCode(line["taxCode"]),
        )
        item.recalculate_tax()
        if persisted:
            item.tax_amount = item.tax_amount.quantize(SCALE)
        items.append(item)
    sale = Sale(id=1, customer_id=None)
    if case["discount"]:
        sale.apply_discount(
            case["discount"]["type"], Decimal(case["discount"]["value"])
        )
    sale.recalculate_totals(items)
    return {
        "subtotal": sale.subtotal,
        "discount": sale.discount,
        "tax": sale.tax,
        "total": sale.total,
    }


def test_there_are_cases_with_decimal_quantities():
    assert any(
        Decimal(line["quantity"]) % 1 for case in CASES for line in case["items"]
    )


@pytest.mark.parametrize("persisted", [False, True], ids=["in-memory", "persisted"])
@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_core_computes_the_shared_totals(case, persisted):
    expected = {key: Decimal(value) for key, value in case["expected"].items()}

    assert _totals(case, persisted) == expected
