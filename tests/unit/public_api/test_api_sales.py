"""A sale of the public API (S6.3): checked where it is made and how it is
paid, then made by the POS's checkout; cancelled only by its own client."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.catalog.product.domain.entities import Product
from src.customers.domain.entities import Customer
from src.inventory.location.domain.entities import Location
from src.inventory.warehouse.domain.entities import Warehouse
from src.organization.domain.entities import Branch, EmissionPoint
from src.organization.domain.exceptions import (
    BranchInactiveError,
    EmissionPointOutsideBranchError,
    LocationOutsideBranchError,
)
from src.pos.sales.app.checkout import SalePlacement
from src.public_api.app.commands.sales import (
    CancelApiSaleCommand,
    CancelApiSaleCommandHandler,
    CreateApiSaleCommand,
    CreateApiSaleCommandHandler,
)
from src.public_api.domain.exceptions import (
    CustomerInactiveError,
    EmissionPointInactiveError,
    PaymentMethodNotAllowedError,
    ReferenceNotFoundError,
    SaleNotFromClientError,
)
from src.sales.domain.entities import Sale, SaleChannel, SaleStatus
from src.shared.domain.exceptions import NotFoundError


def _repo(*entities):
    repo = MagicMock()
    by_id = {e.id: e for e in entities}
    repo.get_by_id.side_effect = by_id.get
    repo.get_by_ids.side_effect = lambda ids: [by_id[i] for i in ids if i in by_id]
    repo.first.side_effect = lambda **kw: next(
        (e for e in entities if all(getattr(e, k) == v for k, v in kw.items())),
        None,
    )
    return repo


BRANCH = Branch(id=1, establishment_code="001", name="Matriz")
OTHER_BRANCH = Branch(id=2, establishment_code="002", name="Norte")
POINT = EmissionPoint(id=10, branch_id=1, code="002")
OTHER_POINT = EmissionPoint(id=11, branch_id=2, code="001")
WAREHOUSE = Warehouse(id=20, branch_id=1, name="Bodega", code="BOD-001")
OTHER_WAREHOUSE = Warehouse(id=21, branch_id=2, name="Bodega 2", code="BOD-002")
LOCATION = Location(id=30, warehouse_id=20, name="General", code="GENERAL")
OTHER_LOCATION = Location(id=31, warehouse_id=21, name="General", code="GENERAL")
CUSTOMER = Customer(id=40, name="Constructora", tax_id="1790011223001")
PRODUCT = Product(id=50, sku="CEM-50", name="Cemento", unit_of_measure_id=1)


@pytest.fixture
def checkout():
    checkout = MagicMock()
    checkout.complete.return_value = {"id": 99}
    return checkout


def _handler(checkout, **overrides) -> CreateApiSaleCommandHandler:
    repos = {
        "branches": _repo(BRANCH, OTHER_BRANCH),
        "emission_points": _repo(POINT, OTHER_POINT),
        "locations": _repo(LOCATION, OTHER_LOCATION),
        "warehouses": _repo(WAREHOUSE, OTHER_WAREHOUSE),
        "customers": _repo(CUSTOMER),
        "products": _repo(PRODUCT),
        **overrides,
    }
    return CreateApiSaleCommandHandler(**repos, checkout=checkout)


def _command(**overrides) -> CreateApiSaleCommand:
    fields: dict[str, Any] = {
        "integration_client_id": 7,
        "branch_id": 1,
        "emission_point_id": 10,
        "location_id": 30,
        "items": [{"product_id": 50, "quantity": Decimal(2)}],
        "payments": [{"payment_method": "TRANSFER", "amount": Decimal("23.00")}],
        "external_reference": "WEB-100234",
        "created_by": "Tienda web",
        **overrides,
    }
    return CreateApiSaleCommand(**fields)


def test_the_sale_is_made_by_the_checkout_at_its_place(checkout):
    _handler(checkout).handle(_command(identification="1790011223001"))

    placement, order = checkout.complete.call_args.args
    assert placement == SalePlacement(
        branch_id=1,
        emission_point_id=10,
        location_id=30,
        channel=SaleChannel.API,
        integration_client_id=7,
        external_reference="WEB-100234",
    )
    assert placement.source == "api"
    assert placement.terminal_id is None and placement.shift_id is None
    assert order.customer_id == 40
    assert order.created_by == "Tienda web"


def test_without_a_customer_it_goes_to_the_final_consumer(checkout):
    _handler(checkout).handle(_command())

    _, order = checkout.complete.call_args.args
    assert order.customer_id is None


@pytest.mark.parametrize("method", ["CASH", "CREDIT"])
def test_cash_and_credit_are_not_paid_online(checkout, method):
    payments = [{"payment_method": method, "amount": Decimal(23)}]

    with pytest.raises(PaymentMethodNotAllowedError):
        _handler(checkout).handle(_command(payments=payments))
    checkout.complete.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"emission_point_id": 11}, EmissionPointOutsideBranchError),
        ({"location_id": 31}, LocationOutsideBranchError),
        ({"emission_point_id": 12}, ReferenceNotFoundError),
        ({"location_id": 32}, ReferenceNotFoundError),
        ({"customer_id": 41}, ReferenceNotFoundError),
        ({"identification": "0999999999"}, ReferenceNotFoundError),
        (
            {"items": [{"product_id": 51, "quantity": Decimal(1)}]},
            ReferenceNotFoundError,
        ),
        ({"branch_id": 3}, NotFoundError),
    ],
    ids=[
        "point-of-another-branch",
        "location-of-another-branch",
        "point-missing",
        "location-missing",
        "customer-missing",
        "identification-missing",
        "product-missing",
        "branch-missing",
    ],
)
def test_what_the_sale_names_must_be_of_its_branch(checkout, overrides, error):
    with pytest.raises(error):
        _handler(checkout).handle(_command(**overrides))
    checkout.complete.assert_not_called()


def test_a_reference_names_its_field(checkout):
    items = [{"product_id": 50, "quantity": 1}, {"product_id": 51, "quantity": 1}]

    with pytest.raises(ReferenceNotFoundError) as raised:
        _handler(checkout).handle(_command(items=items))

    assert raised.value.extra == {"field": "items.1.productId"}


def test_inactive_places_and_customers_are_refused(checkout):
    inactive_branch = Branch(id=1, establishment_code="001", name="M", is_active=False)
    inactive_point = EmissionPoint(id=10, branch_id=1, code="002", is_active=False)
    inactive_customer = Customer(
        id=40, name="C", tax_id="1790011223001", is_active=False
    )

    with pytest.raises(BranchInactiveError):
        _handler(checkout, branches=_repo(inactive_branch)).handle(_command())
    with pytest.raises(EmissionPointInactiveError):
        _handler(checkout, emission_points=_repo(inactive_point)).handle(_command())
    with pytest.raises(CustomerInactiveError):
        _handler(checkout, customers=_repo(inactive_customer)).handle(
            _command(customer_id=40)
        )


def _sale(**fields) -> Sale:
    return Sale(
        id=5,
        branch_id=1,
        status=SaleStatus.CONFIRMED,
        channel=SaleChannel.API,
        integration_client_id=7,
        **fields,
    )


def test_a_client_cancels_its_own_sales_through_the_pos_command():
    cancel = MagicMock()
    handler = CancelApiSaleCommandHandler(_repo(_sale()), cancel)

    handler.handle(CancelApiSaleCommand(integration_client_id=7, sale_id=5))

    [command] = cancel.handle.call_args.args
    assert (command.sale_id, command.source) == (5, "api")


def test_another_clients_sale_is_not_cancelled():
    cancel = MagicMock()
    handler = CancelApiSaleCommandHandler(_repo(_sale()), cancel)

    with pytest.raises(SaleNotFromClientError):
        handler.handle(CancelApiSaleCommand(integration_client_id=8, sale_id=5))
    cancel.handle.assert_not_called()


def test_a_sale_of_another_branch_looks_missing():
    handler = CancelApiSaleCommandHandler(_repo(_sale()), MagicMock())

    with pytest.raises(NotFoundError):
        handler.handle(
            CancelApiSaleCommand(
                integration_client_id=7, sale_id=5, allowed_branch_ids=frozenset({2})
            )
        )
