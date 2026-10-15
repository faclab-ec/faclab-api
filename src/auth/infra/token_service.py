from datetime import UTC, datetime, timedelta

import jwt
import structlog
from wireup import injectable

from config import config
from src.auth.app.services.token_service import (
    TokenClaims,
    TokenPair,
    TokenService,
    TokenType,
)
from src.auth.domain.entities import User
from src.auth.domain.exceptions import InvalidTokenError, TokenExpiredError
from src.auth.domain.permissions import permissions_for

_ALGORITHM = "HS256"

logger = structlog.get_logger(__name__)


@injectable(lifetime="singleton", as_type=TokenService)
class JwtTokenService(TokenService):
    def __init__(self):
        self._secret = config.JWT_SECRET
        self._access_ttl = config.JWT_ACCESS_TTL_SECONDS
        self._refresh_ttl = config.JWT_REFRESH_TTL_SECONDS
        self._issuer = config.JWT_ISSUER
        self._reuse_grace = config.JWT_REFRESH_REUSE_GRACE_SECONDS

    @property
    def refresh_ttl_seconds(self) -> int:
        return self._refresh_ttl

    @property
    def refresh_reuse_grace_seconds(self) -> int:
        return self._reuse_grace

    def issue_pair(self, user: User, session_id: int, refresh_jti: str) -> TokenPair:
        access = self._encode(user, session_id, "access", self._access_ttl)
        refresh = self._encode(
            user, session_id, "refresh", self._refresh_ttl, jti=refresh_jti
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=self._access_ttl,
        )

    def decode_access(self, token: str) -> TokenClaims:
        return self._decode(token, expected_typ="access")

    def decode_refresh(self, token: str) -> TokenClaims:
        return self._decode(token, expected_typ="refresh")

    def _encode(
        self,
        user: User,
        session_id: int,
        typ: TokenType,
        ttl_seconds: int,
        jti: str | None = None,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(user.id),
            "sid": session_id,
            "username": user.username,
            "role": int(user.role),
            "typ": typ,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
            "iss": self._issuer,
            "mcp": bool(user.must_change_password),
        }
        if typ == "access":
            # Other services (faclab-invoicing) authorize with these, so they
            # don't need their own copy of the role -> permissions table
            payload["perms"] = sorted(p.value for p in permissions_for(user.role))
            if user.full_name:
                payload["name"] = user.full_name
        if jti is not None:
            payload["jti"] = jti
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def _decode(self, token: str, expected_typ: TokenType) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "sub", "typ"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("token expired") from exc
        except jwt.PyJWTError as exc:
            # PyJWT's text stays in the server log; the client gets a stable one
            logger.info("token_rejected", reason=str(exc))
            raise InvalidTokenError("invalid token") from exc

        if payload.get("typ") != expected_typ:
            logger.info(
                "token_rejected",
                reason=f"expected {expected_typ} token, got {payload.get('typ')}",
            )
            raise InvalidTokenError("invalid token")

        try:
            return TokenClaims(
                sub=int(payload["sub"]),
                username=payload["username"],
                role=int(payload["role"]),
                typ=payload["typ"],
                iat=int(payload["iat"]),
                exp=int(payload["exp"]),
                iss=payload["iss"],
                must_change_password=bool(payload.get("mcp", False)),
                sid=int(payload["sid"]) if payload.get("sid") is not None else None,
                jti=str(payload["jti"]) if payload.get("jti") is not None else None,
                name=payload.get("name") or None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.info("token_rejected", reason="malformed claims")
            raise InvalidTokenError("invalid token") from exc
