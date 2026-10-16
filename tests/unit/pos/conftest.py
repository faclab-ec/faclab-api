import pytest


@pytest.fixture(autouse=True)
def _in_tenant(in_tenant):
    """POS code runs inside a request's tenant"""
    return in_tenant
