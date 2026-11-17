"""`GET /.well-known/jwks.json`: the public keys that verify faclab-core's tokens.

Public and outside the API docs, like the health checks. Other services
(faclab-invoicing) read it to check access tokens without a shared secret, and
cache it; during a rotation it lists both keys (S6.1).
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.auth.infra.signing_keys import JwtKeys

JWKS_PATH = "/.well-known/jwks.json"
# Verifiers fetch it again for an unknown `kid`, so a new key doesn't wait for this
_MAX_AGE_SECONDS = 300


class JwksRouter:
    def __init__(self, keys: JwtKeys):
        self._keys = keys
        self.router = APIRouter()
        self.router.add_api_route(
            JWKS_PATH, self.jwks, methods=["GET"], include_in_schema=False
        )

    def jwks(self) -> JSONResponse:
        return JSONResponse(
            self._keys.jwks(),
            headers={"Cache-Control": f"public, max-age={_MAX_AGE_SECONDS}"},
        )
