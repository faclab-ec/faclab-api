from dataclasses import dataclass

from src.integrations.domain.credentials import IntegrationEnvironment


@dataclass(frozen=True)
class IntegrationSettings:
    # The deployment's: its clients are created in it and only those get tokens
    environment: IntegrationEnvironment
