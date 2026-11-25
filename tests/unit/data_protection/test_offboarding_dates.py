from datetime import datetime

import pytest

from src.data_protection.app.commands.offboarding import add_years
from src.tenancy.domain.entities import Tenant, TenantStatus
from src.tenancy.domain.exceptions import (
    OffboardingAlreadyStartedError,
    OffboardingNotStartedError,
    TenantOffboardedError,
)

RUC = "1799999990001"
NOW = datetime(2026, 11, 25, 10)


def test_add_years_keeps_the_day_and_handles_leap_days():
    assert add_years(datetime(2026, 11, 25, 9), 7) == datetime(2033, 11, 25, 9)
    assert add_years(datetime(2028, 2, 29), 1) == datetime(2029, 2, 28)


def test_a_tenant_goes_through_its_offboarding():
    tenant = Tenant(ruc=RUC, legal_name="Ferretería Andes")
    tenant.start_offboarding(NOW, NOW, NOW)

    assert tenant.in_offboarding
    with pytest.raises(OffboardingAlreadyStartedError):
        tenant.start_offboarding(NOW, NOW, NOW)
    tenant.cancel_offboarding()
    assert not tenant.in_offboarding and tenant.grace_ends_at is None
    with pytest.raises(OffboardingNotStartedError):
        tenant.cancel_offboarding()


def test_an_offboarded_tenant_cannot_come_back():
    tenant = Tenant(ruc=RUC, legal_name="Ferretería Andes")
    tenant.start_offboarding(NOW, NOW, NOW)
    tenant.mark_anonymized(NOW)

    assert tenant.status == TenantStatus.OFFBOARDED and not tenant.is_active
    for step in (tenant.activate, tenant.cancel_offboarding):
        with pytest.raises(TenantOffboardedError):
            step()
