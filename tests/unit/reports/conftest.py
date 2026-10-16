import pytest


@pytest.fixture(autouse=True)
def _in_tenant(in_tenant):
    """Report queries read only the context's tenant, as in a request"""
    return in_tenant
