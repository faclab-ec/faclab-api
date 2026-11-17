from abc import ABC, abstractmethod

from src.auth.app.services.token_service import ClientTokenClaims
from src.auth.domain.principals import IntegrationPrincipal


class IntegrationAccess(ABC):
    """What an integration's access token is worth now (S6.2).

    A signed token isn't enough: the client may have been revoked, the secret
    it was obtained with may have been revoked, or its scopes and branches may
    have shrunk since. The implementation reads the client's state (cached for
    at most a minute) and records the usage of every request."""

    @abstractmethod
    def principal(
        self, claims: ClientTokenClaims, ip: str | None
    ) -> IntegrationPrincipal | None:
        """The integration of the token as it is now, or None when the token
        no longer gives access (revoked client or secret, another environment,
        an address it isn't allowed from)"""

    @abstractmethod
    def record_request(
        self, principal: IntegrationPrincipal, status_code: int, ip: str | None
    ) -> None:
        """Counts a request of the integration in its usage of the day. Never
        raises: the usage can't break the response"""
