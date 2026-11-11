import pytest


@pytest.fixture(autouse=True)
def _in_tenant(in_tenant):
    """The portfolio is read and written inside a request's tenant"""
    return in_tenant
