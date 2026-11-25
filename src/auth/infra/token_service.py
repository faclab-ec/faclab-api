from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
import structlog
from wireup import injectable

from config import config
from src.auth.app.services.token_service import (
    ClientToken,
    ClientTokenClaims,
    PlatformToken,
    PlatformTokenClaims,
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
from src.auth.domain.scopes import Scope, format_scopes
from src.auth.infra.signing_keys import ALGORITHM, JwtKeys
from src.tenancy.domain.entities import Membership

logger = structlog.get_logger(__name__)

# `sub` of an integration client's token; a user's is its numeric id
CLIENT_SUBJECT_PREFIX = "client:"


@injectable(lifetime="singleton", as_type=TokenService)
class JwtTokenService(TokenService):
    """Signs with the Ed25519 key of `JwtKeys` (EdDSA, its `kid` in the header)
    and accepts tokens of any key it publishes, so a rotation keeps the
    sessions signed with the previous key (S6.1)"""

    def __init__(self, keys: JwtKeys):
        self._keys = keys
        self._access_ttl = config.JWT_ACCESS_TTL_SECONDS
        self._refresh_ttl = config.JWT_REFRESH_TTL_SECONDS
        self._selection_ttl = config.JWT_SELECTION_TTL_SECONDS
        self._issuer = config.JWT_ISSUER
        self._audience = config.JWT_AUDIENCE
        # Access tokens also go to these services (faclab-invoicing)
        self._access_audience = [
            self._audience,
            *(aud for aud in config.JWT_SERVICE_AUDIENCES if aud != self._audience),
        ]
        self._reuse_grace = config.JWT_REFRESH_REUSE_GRACE_SECONDS
        self._platform_ttl = config.PLATFORM_TOKEN_TTL_SECONDS

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
            token=self._encode(payload),
            expires_in=self._selection_ttl,
        )

    def decode_access(self, token: str) -> TokenClaims:
        return self._user_access(self._decode(token, accepted=("access",)))

    def decode_bearer(
        self, token: str
    ) -> TokenClaims | ClientTokenClaims | PlatformTokenClaims:
        payload = self._verified(token, accepted=("access", "platform"))
        if payload["typ"] == "platform":
            return _platform_claims(payload)
        if _is_client(payload):
            return _client_claims(payload)
        return self._user_access(_user_claims(payload))

    def issue_platform_access(self, user: User) -> PlatformToken:
        payload = self._payload(user, "platform", self._platform_ttl)
        # No `tid`, no `role`; only this service names itself in `aud`, so
        # faclab-invoicing refuses it
        payload.pop("mcp", None)
        if user.full_name:
            payload["name"] = user.full_name
        return PlatformToken(
            access_token=self._encode(payload), expires_in=self._platform_ttl
        )

    def issue_client_access(
        self,
        *,
        public_id: str,
        tenant_id: UUID,
        secret_id: int,
        scopes: Collection[Scope],
        branch_ids: Collection[int] | None = None,
    ) -> ClientToken:
        now = datetime.now(UTC)
        granted = frozenset(scopes)
        payload: dict[str, Any] = {
            "sub": f"{CLIENT_SUBJECT_PREFIX}{public_id}",
            "azp": public_id,
            "tid": str(tenant_id),
            "cred": secret_id,
            "scope": format_scopes(granted),
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self._access_ttl)).timestamp()),
            "iss": self._issuer,
            # Also the services with a public API (S6.3): faclab-invoicing's
            # `/api/v1/invoices` checks its scopes, and its internal routes
            # refuse it (they authorize with `perms`, which it doesn't carry)
            "aud": self._access_audience,
        }
        if branch_ids is not None:
            payload["bids"] = sorted(set(branch_ids))
        return ClientToken(
            access_token=self._encode(payload),
            expires_in=self._access_ttl,
            scopes=granted,
        )

    def _user_access(self, claims: TokenClaims) -> TokenClaims:
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
            "aud": self._audience,
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
            payload["aud"] = self._access_audience
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
        return self._encode(payload)

    def _encode(self, payload: dict[str, Any]) -> str:
        return jwt.encode(
            payload,
            self._keys.signing_key,
            algorithm=ALGORITHM,
            headers={"kid": self._keys.signing_kid},
        )

    def _decode(self, token: str, accepted: tuple[TokenType, ...]) -> TokenClaims:
        """A user's token: an integration's never passes as one"""
        payload = self._verified(token, accepted)
        if _is_client(payload):
            logger.info("token_rejected", reason="integration token as a user's")
            raise InvalidTokenError("invalid token")
        return _user_claims(payload)

    def _verified(self, token: str, accepted: tuple[TokenType, ...]) -> dict[str, Any]:
        """The claims of a token signed by a published key, for this service,
        not expired and of one of the `accepted` types"""
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self._keys.verification_key(kid) if isinstance(kid, str) else None
            if key is None:
                # Signed with a key that isn't published (or none): no one
                # should trust it
                raise jwt.InvalidKeyError("unknown signing key")
            payload = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "iss", "sub", "typ", "aud"]},
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
        return payload


def _is_client(payload: dict[str, Any]) -> bool:
    return str(payload.get("sub", "")).startswith(CLIENT_SUBJECT_PREFIX)


def _user_claims(payload: dict[str, Any]) -> TokenClaims:
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


def _platform_claims(payload: dict[str, Any]) -> PlatformTokenClaims:
    try:
        if payload.get("tid") is not None or _is_client(payload):
            raise ValueError("a platform token has no tenant")
        return PlatformTokenClaims(
            sub=int(payload["sub"]),
            username=payload["username"],
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
            iss=payload["iss"],
            name=payload.get("name") or None,
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.info("token_rejected", reason="malformed platform claims")
        raise InvalidTokenError("invalid token") from exc


def _client_claims(payload: dict[str, Any]) -> ClientTokenClaims:
    try:
        public_id = payload["azp"]
        if not isinstance(public_id, str) or payload["sub"] != (
            f"{CLIENT_SUBJECT_PREFIX}{public_id}"
        ):
            raise ValueError("sub and azp name different clients")
        return ClientTokenClaims(
            public_id=public_id,
            tid=UUID(str(payload["tid"])),
            secret_id=int(payload["cred"]),
            scopes=_scopes(payload["scope"]),
            iat=int(payload["iat"]),
            exp=int(payload["exp"]),
            iss=payload["iss"],
            bids=_optional(payload, "bids", _branch_ids),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.info("token_rejected", reason="malformed integration claims")
        raise InvalidTokenError("invalid token") from exc


def _scopes(value: Any) -> frozenset[Scope]:
    """The scopes it names that still exist: one retired after the token was
    issued gives nothing"""
    if not isinstance(value, str):
        raise TypeError("scope must be a string")
    known = {scope.value for scope in Scope}
    return frozenset(Scope(name) for name in value.split() if name in known)


def _branch_ids(value: Any) -> frozenset[int]:
    if not isinstance(value, list):
        raise TypeError("bids must be a list")
    return frozenset(int(branch_id) for branch_id in value)


def _optional(payload: dict[str, Any], key: str, convert):
    value = payload.get(key)
    return convert(value) if value is not None else None
