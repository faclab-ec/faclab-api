from .base import env
from .deployed import DeployedConfig


class Config(DeployedConfig):
    # Production issues fl_live_ credentials (S6.2); every other deployment is
    # a sandbox
    INTEGRATION_ENVIRONMENT = env.str(
        "INTEGRATION_ENVIRONMENT",
        "production",
        validate=lambda value: value in ("sandbox", "production"),
    )
