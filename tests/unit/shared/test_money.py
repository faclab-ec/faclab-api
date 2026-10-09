from decimal import Decimal

from src.shared.domain.money import allocate


def test_allocate_gives_leftover_cents_to_the_largest_remainders():
    shares = allocate(Decimal("1.00"), [Decimal("1"), Decimal("1"), Decimal("1")])

    assert shares == [Decimal("0.34"), Decimal("0.33"), Decimal("0.33")]


def test_allocate_is_proportional_and_sums_to_the_total():
    weights = [Decimal("100"), Decimal("20"), Decimal("30.005")]

    shares = allocate(Decimal("15.00"), weights)

    assert sum(shares) == Decimal("15.00")
    assert shares == [Decimal("10.00"), Decimal("2.00"), Decimal("3.00")]


def test_allocate_with_zero_weights_splits_evenly():
    assert allocate(Decimal("0.05"), [Decimal("0"), Decimal("0")]) == [
        Decimal("0.03"),
        Decimal("0.02"),
    ]


def test_allocate_without_weights_returns_nothing():
    assert allocate(Decimal("1"), []) == []
