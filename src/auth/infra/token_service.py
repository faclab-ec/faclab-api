from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import structlog
from wireup import injectable

from config import config
from src.auth.app.services.token_service import (
    SelectionToken,
    TokenClaims,
    TokenPair,
    TokenService,
    TokenType,
)
from src.auth.domain.entities import User
from src.auth.domain.exceptions import (
    InvalidTokenError,
    TenantRequiredError,
    TokenExpiredError,
)
from src.auth.domain.permissions import permissions_for
from src.tenancy.domain.entities import Membership

_ALGORITHM = "HS256"

logger = structlog.get_logger(__name__)


@injectable(lifetime="singleton", as_type=TokenService)
class JwtTokenService(TokenService):
    def __init__(self):
        self._secret = config.JWT_SECRET
        self._access_ttl = config.JWT_ACCESS_TTL_SECONDS
        self._refresh_ttl = config.JWT_REFRESH_TTL_SECONDS
        self._selection_ttl = config.JWT_SELECTION_TTL_SECONDS
        self._issuer = config.JWT_ISSUER
        self._reuse_grace = config.JWT_REFRESH_REUSE_GRACE_SECONDS

    @property
    def refresh_ttl_seconds(self) -> int:
        return self._refresh_ttl

    @property
    def refresh_reuse_grace_seconds(self) -> int:
        return self._reuse_grace

    def issue_pair(
        self,
        user: User,
        membership: Membership,
        session_id: int,
        refresh_jti: str,
        *,
        branch_ids: Collection[int] | None = None,
    ) -> TokenPair:
        access = self._session_token(
            user,
            membership,
            session_id,
            "access",
            self._access_ttl,
            branch_ids=branch_ids,
        )
        refresh = self._session_token(
            user,
            membership,
            session_id,
            "refresh",
            self._refresh_ttl,
            jti=refresh_jti,
        )
        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=self._access_ttl,
        )

    def issue_selection(self, user: User) -> SelectionToken:
        payload = self._payload(user, "selection", self._selection_ttl)
        return SelectionToken(
            token=jwt.encode(payload, self._secret, algorithm=_ALGORITHM),
            expires_in=self._selection_ttl,
        )

    def decode_access(self, token: str) -> TokenClaims:
        claims = self._decode(token, accepted=("access",))
        if claims.tid is None:
            raise TenantRequiredError()
        if claims.role is None:
            logger.info("token_rejected", reason="access token without role")
            raise InvalidTokenError("invalid token")
        return claims

    def decode_refresh(self, token: str) -> TokenClaims:
        return self._decode(token, accepted=("refresh",))

    def decode_selection(self, token: str) -> TokenClaims:
        return self._decode(token, accepted=("selection", "access"))

    def _payload(self, user: User, typ: TokenType, ttl_seconds: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "sub": str(user.id),
            "username": user.username,
            "typ": typ,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
            "iss": self._issuer,
            "mcp": bool(user.must_change_password),
        }

    def _session_token(
        self,
        user: User,
        membership: Membership,
        session_id: int,
        typ: TokenType,
        ttl_seconds: int,
        jti: str | None = None,
        branch_ids: Collection[int] | None = None,
    ) -> str:
        payload = self._payload(user, typ, ttl_seconds)
        payload["sid"] = session_id
        payload["tid"] = str(membership.tenant_id)
        payload["role"] = int(membership.role)
        if typ == "access":
            # Other services (faclab-invoicing) authorize with these, so they
            # don't need their own copy of the role -> permissions table
            payload["perms"] = sorted(p.value for p in permissions_for(membership.role))
            if user.full_name:
                payload["name"] = user.full_name
            # Only when the membership is limited to some branches: without
            # the claim the user may enter all of them
            if branch_ids is not None:
                payload["bids"] = sorted(set(branch_ids))
        if jti is not None:
            payload["jti"] = jti
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM)

    def _decode(self, token: str, accepted: tuple[TokenType, ...]) -> TokenClaims:
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

        if payload.get("typ") not in accepted:
            logger.info(
                "token_rejected",
                reason=f"expected {'/'.join(accepted)} token, got {payload.get('typ')}",
            )
            raise InvalidTokenError("invalid token")

        try:
            return TokenClaims(
                sub=int(payload["sub"]),
                username=payload["username"],
                typ=payload["typ"],
                iat=int(payload["iat"]),
                exp=int(payload["exp"]),
                iss=payload["iss"],
                role=_optional(payload, "role", int),
                tid=_optional(payload, "tid", lambda value: UUID(str(value))),
                must_change_password=bool(payload.get("mcp", False)),
                sid=_optional(payload, "sid", int),
                jti=_optional(payload, "jti", str),
                name=payload.get("name") or None,
                bids=_optional(payload, "bids", _branch_ids),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.info("token_rejected", reason="malformed claims")
            raise InvalidTokenError("invalid token") from exc


def _branch_ids(value: Any) -> frozenset[int]:
    if not isinstance(value, list):
        raise TypeError("bids must be a list")
    return frozenset(int(branch_id) for branch_id in value)


def _optional(payload: dict[str, Any], key: str, convert):
    value = payload.get(key)
    return convert(value) if value is not None else None
