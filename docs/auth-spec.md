# Auth Spec — Faclab Core

JWT-based authentication with role-based authorization. All admin and POS routes require a valid access token. Login, refresh and logout are public.

## Obtaining a token

```bash
curl -X POST http://localhost:3000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"ChangeMe123!"}'
```

Response (the refresh token comes in the `faclab_refresh` cookie, `HttpOnly; Secure; SameSite=Strict; Path=/api/auth`, without `Secure` locally):

```json
{
  "data": {
    "accessToken": "eyJhbGciOi...",
    "tokenType": "Bearer",
    "expiresIn": 900
  }
}
```

Send the token on every protected request:

```
Authorization: Bearer <accessToken>
```

Access tokens expire after `JWT_ACCESS_TTL_SECONDS` seconds (default 900). Refresh via `POST /api/auth/refresh` with no body: the browser sends the cookie (`withCredentials` / `credentials: "include"`). The server revalidates the user (role, `is_active`) and the session before reissuing.

Each login opens a session (`auth_sessions`) whose id travels in the tokens as `sid`. `POST /api/auth/logout` revokes it and clears the cookie; a password change revokes the user's other sessions, and an admin reset or deactivation revokes all of them. A revoked session can't be refreshed; access tokens are stateless and expire on their own. The last active admin can't be deactivated or demoted (`LAST_ADMIN`, 409).

## Session security

- **Refresh rotation.** Every refresh issues a new refresh token (its `jti` is stored in `auth_sessions.refresh_jti`) and the previous one stops working. Presenting an already used refresh token revokes the whole session: 401 `TOKEN_REUSED`. The token replaced less than `JWT_REFRESH_REUSE_GRACE_SECONDS` ago (default 30) still gets the current token, so two tabs refreshing at once don't log the user out. The revocation is committed even though the request fails (`commit_transaction` on the error).
- **Login lockout.** Failed logins are stored in `login_failures`. By default 5 failures for a username within 15 minutes, or 20 from one client IP, lock it for 15 minutes after the last failure: 429 `LOGIN_LOCKED`, even with the right password. Attempts while locked are not counted. Unknown usernames are checked against a dummy bcrypt hash, so response time doesn't reveal which usernames exist.
- **Authors from the token.** Shifts, POS sales, cash movements, refunds, adjustments and transfers are signed with the authenticated user's `fullName`, or the username when it has none. Request bodies don't accept author fields.
- **No internals in responses or logs.** JWT errors answer the generic "invalid token" and unexpected `ValueError`s "Invalid value" (the detail stays in the server log). Request validation errors are logged without the rejected `input`, and a structlog processor masks passwords, tokens, secrets, cookies and `Authorization` values.
- **HTTP hardening.** Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`; bodies over `MAX_REQUEST_BODY_BYTES` (1 MiB) get 413 `REQUEST_TOO_LARGE`.

## Role × Permission matrix

| Permission | ADMIN | MANAGER | OPERATOR | VIEWER | CASHIER |
|---|:-:|:-:|:-:|:-:|:-:|
| `product:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `product:write` | ✓ | ✓ | ✓ |   |   |
| `category:write` | ✓ | ✓ | ✓ |   |   |
| `uom:write` | ✓ | ✓ | ✓ |   |   |
| `stock:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `movement:write` | ✓ | ✓ | ✓ |   |   |
| `warehouse:write` | ✓ | ✓ |   |   |   |
| `location:write` | ✓ | ✓ |   |   |   |
| `lot:write` | ✓ | ✓ | ✓ |   |   |
| `serial:write` | ✓ | ✓ | ✓ |   |   |
| `adjustment:write` | ✓ | ✓ | ✓ |   |   |
| `transfer:write` | ✓ | ✓ | ✓ |   |   |
| `alert:read` | ✓ | ✓ | ✓ | ✓ |   |
| `sale:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `sale:write` | ✓ | ✓ | ✓ |   | ✓ |
| `sale:cancel` | ✓ | ✓ |   |   |   |
| `purchase:read` | ✓ | ✓ | ✓ | ✓ |   |
| `purchase:write` | ✓ | ✓ | ✓ |   |   |
| `purchase:confirm` | ✓ | ✓ |   |   |   |
| `purchase:receive` | ✓ | ✓ |   |   |   |
| `customer:read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `customer:write` | ✓ | ✓ | ✓ |   | ✓ |
| `supplier:read` | ✓ | ✓ | ✓ | ✓ |   |
| `supplier:write` | ✓ | ✓ | ✓ |   |   |
| `pos:operate` | ✓ |   |   |   | ✓ |
| `refund:approve` | ✓ | ✓ |   |   |   |
| `report:inventory:read` | ✓ | ✓ | ✓ | ✓ |   |
| `report:pos:read` | ✓ | ✓ |   | ✓ | ✓ |
| `user:manage` | ✓ |   |   |   |   |

Role numeric codes (persisted in DB):

| Code | Role |
|---|---|
| 1 | ADMIN |
| 2 | MANAGER |
| 3 | OPERATOR |
| 4 | VIEWER |
| 5 | CASHIER |

## Protecting a new route

```python
from fastapi import Depends
from src.auth.domain.permissions import Permission
from src.auth.infra.dependencies import require_permission

def _setup_routes(self):
    _read = [Depends(require_permission(Permission.PRODUCT_READ))]
    _write = [Depends(require_permission(Permission.PRODUCT_WRITE))]

    self.router.get("", ..., dependencies=_read)(self.list)
    self.router.post("", ..., dependencies=_write)(self.create)
```

Route-level `dependencies=[...]` runs before the handler. If the user is unauthenticated, the dependency raises `PermissionDeniedError("authentication required")` → 403. If the user lacks the permission, it raises `PermissionDeniedError("missing permissions: [...]")` → 403.

## Adding a new permission

1. Add the verb to `Permission` (StrEnum) in `src/auth/domain/permissions.py` under the right module comment.
2. Add it to the role mappings in `PERMISSIONS_BY_ROLE` (or to `_ALL_READS` / `_OPERATOR_PERMS` / `_CASHIER_PERMS` if it fits an existing bundle). `ADMIN` and `MANAGER` receive it automatically (MANAGER via `frozenset(Permission) - {excluded}`).
3. Add unit tests in `tests/unit/auth/test_permissions.py` covering which roles do and do not get the new permission.
4. Apply it to the relevant routers via `Depends(require_permission(...))`.

Tokens carry only `role`; permissions are re-derived on every request via `permissions_for(role)`. You do not need to reissue tokens when mapping changes.

## Production checklist

- `JWT_SECRET` must be set (config `production.py` raises on missing / short secret).
- Seed the first admin: `AUTH_SEED_USERNAME=... AUTH_SEED_EMAIL=... AUTH_SEED_PASSWORD=... python -m src.auth.seed`
- Rotate `JWT_SECRET` invalidates all active tokens (users must log in again).
- Rate limiting on `/api/auth/login` is NOT implemented — put it at the reverse proxy if exposed publicly.
