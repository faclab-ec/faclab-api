from collections.abc import Iterator

import pytest

from tests.webhook_receiver import Certificate, Receiver, localhost_certificate


@pytest.fixture(scope="session")
def certificate() -> Certificate:
    return localhost_certificate()


@pytest.fixture
def receiver(certificate) -> Iterator[Receiver]:
    server = Receiver(certificate)
    yield server
    server.close()
