"""What every route of the public API declares (S6.3)."""

from typing import Any

from fastapi import Depends

from config import config
from src.auth.domain.exceptions import BranchAccessDeniedError, PermissionDeniedError
from src.auth.domain.principals import IntegrationPrincipal, Principal
from src.auth.domain.scopes import Scope
from src.auth.infra.dependencies import get_principal, require_scope
from src.public_api.domain.exceptions import (
    BranchIdRequiredError,
    PublicApiDisabledError,
)

# The security scheme of the public OpenAPI: OAuth 2.0 client credentials
OAUTH_SCHEME = "clientCredentials"


def public_api_enabled() -> None:
    """PUBLIC_API_ENABLED=false turns every route off (503), the rollback"""
    if not config.PUBLIC_API_ENABLED:
        raise PublicApiDisabledError()


class RequireScope:
    """`require_scope` as an object, so the tests and the OpenAPI can read the
    scopes a route requires. Without scopes it still requires an integration
    client's token (`GET /branches`)."""

    def __init__(self, *scopes: Scope):
        self.scopes = scopes
        self._check = require_scope(*scopes)

    def __call__(
        self, principal: Principal = Depends(get_principal)
    ) -> IntegrationPrincipal:
        return self._check(principal)


def guarded(*scopes: Scope) -> dict[str, Any]:
    """The route arguments of a public route: the switch, the scopes, and the
    scopes in its OpenAPI operation"""
    return {
        "dependencies": [Depends(public_api_enabled), Depends(RequireScope(*scopes))],
        "openapi_extra": {"security": [{OAUTH_SCHEME: [s.value for s in scopes]}]},
    }


def current_client(
    principal: Principal = Depends(get_principal),
) -> IntegrationPrincipal:
    """The integration client of the request (its route already required it)"""
    if not isinstance(principal, IntegrationPrincipal):
        raise PermissionDeniedError("this route takes integration credentials")
    return principal


def ensure_branch(client: IntegrationPrincipal, branch_id: int) -> int:
    """A branch the client names in a filter: one it may operate in"""
    if not client.can_enter_branch(branch_id):
        raise BranchAccessDeniedError("this client may not operate in this branch")
    return branch_id


def single_branch(client: IntegrationPrincipal, branch_id: int | None) -> int:
    """The branch of a listing by branch: the one it names, or the only one the
    client may operate in (`BRANCH_REQUIRED` otherwise)"""
    if branch_id is not None:
        return ensure_branch(client, branch_id)
    if client.branch_ids is not None and len(client.branch_ids) == 1:
        [only] = client.branch_ids
        return only
    raise BranchIdRequiredError()
