import pytest


@pytest.fixture(autouse=True)
def _in_tenant(in_tenant):
    """An import is uploaded and run inside a tenant"""
    return in_tenant
