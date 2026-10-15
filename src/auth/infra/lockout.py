from datetime import timedelta

from wireup import injectable

from config import config
from src.auth.domain.entities import LoginLockoutPolicy


@injectable(lifetime="singleton")
def login_lockout_policy() -> LoginLockoutPolicy:
    return LoginLockoutPolicy(
        max_failures_per_user=config.LOGIN_MAX_FAILURES_PER_USER,
        max_failures_per_ip=config.LOGIN_MAX_FAILURES_PER_IP,
        window=timedelta(seconds=config.LOGIN_FAILURE_WINDOW_SECONDS),
        lockout=timedelta(seconds=config.LOGIN_LOCKOUT_SECONDS),
    )
