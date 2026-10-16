# Auth Spec — Faclab Core

JWT-based authentication with role-based authorization. All admin and POS routes require a valid access token. Login, select-tenant, refresh and logout are public.

## Tenants and memberships

A **tenant** is a company: one taxpayer with one RUC (`tenants`). Users are global: the username and the email are unique across the platform, and the password and full name are the same in every tenant. A **membership** (`memberships`) gives a user a role in a tenant, so the same person can be the ADMIN of one company and a VIEWER of another (an outside accountant, for example).

Every session and every token belongs to one tenant: the `tid` claim. Role and permissions are those of the membership in that tenant. Tenants are created with the platform CLI (`python -m src.tenancy.provision`, see [Provisioning tenants](#provisioning-tenants)).

> Data isolation between tenants comes in later sessions (S2.2–S2.4): today the token says which tenant a request belongs to, and user management works inside it, but business data is still shared.

## Obtaining a token

```bash
curl -X POST http://localhost:3000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"ChangeMe123!"}'
```

A user with **one** active tenant gets the session right away (the refresh token comes in the `faclab_refresh` cookie, `HttpOnly; Secure; SameSite=Strict; Path=/api/auth`, without `Secure` locally):

```json
{
  "data": {
    "accessToken": "eyJhbGciOi...",
    "tokenType": "Bearer",
    "expiresIn": 900,
    "tenant": {"id": "6f1c…", "ruc": "1799999990001", "legalName": "Ferretería Ejemplo S.A.", "tradeName": null}
  }
}
```

A user with **several** gets no session yet: a selection token (5 minutes, `JWT_SELECTION_TTL_SECONDS`) and the tenants to choose from, with the role in each:

```json
{
  "data": {
    "selectionToken": "eyJhbGciOi...",
    "expiresIn": 300,
    "tenants": [
      {"id": "6f1c…", "ruc": "1799999990001", "legalName": "Ferretería Ejemplo S.A.", "tradeName": null, "role": 1},
      {"id": "a20e…", "ruc": "0999999999001", "legalName": "Comercial Dos S.A.", "tradeName": null, "role": 4}
    ]
  }
}
```

The client then opens the session in one of them; the answer is the one-tenant one, cookie included:

```bash
curl -X POST http://localhost:3000/api/auth/select-tenant \
  -H 'Authorization: Bearer <selectionToken>' \
  -H 'Content-Type: application/json' \
  -d '{"tenantId":"a20e…"}'
```

**Switching tenants** is the same call with the current access token instead of the selection token: it opens a session in the new tenant and closes the current one (its refresh cookie is replaced anyway). The current session must still be active, so a logged-out session can't be reopened with an access token that hasn't expired yet. A tenant the user can't enter answers 403 `TENANT_ACCESS_DENIED`; right credentials without any active membership in an active tenant answer 403 `NO_ACTIVE_TENANT`.

Send the token on every protected request:

```
Authorization: Bearer <accessToken>
```

Access tokens expire after `JWT_ACCESS_TTL_SECONDS` seconds (default 900). Refresh via `POST /api/auth/refresh` with no body: the browser sends the cookie (`withCredentials` / `credentials: "include"`). The server revalidates the user (`is_active`), the session and its membership (still active, in an active tenant; the role may have changed) before reissuing.

Each session (`auth_sessions`) belongs to a tenant (`tenant_id`); its id travels in the tokens as `sid` and the tenant as `tid`. `POST /api/auth/logout` revokes it and clears the cookie; a password change revokes the user's other sessions, an admin reset revokes all of them, and removing a user from a tenant revokes their sessions in that tenant. A revoked session can't be refreshed; access tokens are stateless and expire on their own. The last active admin of a tenant can't be deactivated or demoted (`LAST_ADMIN`, 409).

An access token without `tid` (issued before tenants existed) is rejected with 401 `TENANT_REQUIRED`: the client logs in again.

## Session security

- **Refresh rotation.** Every refresh issues a new refresh token (its `jti` is stored in `auth_sessions.refresh_jti`) and the previous one stops working. Presenting an already used refresh token revokes the whole session: 401 `TOKEN_REUSED`. The token replaced less than `JWT_REFRESH_REUSE_GRACE_SECONDS` ago (default 30) still gets the current token, so two tabs refreshing at once don't log the user out. The revocation is committed even though the request fails (`commit_transaction` on the error).
- **Login lockout.** Failed logins are stored in `login_failures`. By default 5 failures for a username within 15 minutes, or 20 from one client IP, lock it for 15 minutes after the last failure: 429 `LOGIN_LOCKED`, even with the right password. Attempts while locked are not counted. Unknown usernames are checked against a dummy bcrypt hash, so response time doesn't reveal which usernames exist.
- **Authors from the token.** Shifts, POS sales, cash movements, refunds, adjustments and transfers are signed with the authenticated user's `fullName`, or the username when it has none. Request bodies don't accept author fields.
- **No internals in responses or logs.** JWT errors answer the generic "invalid token" and unexpected `ValueError`s "Invalid value" (the detail stays in the server log). Request validation errors are logged without the rejected `input`, and a structlog processor masks passwords, tokens, secrets, cookies and `Authorization` values.
- **HTTP hardening.** Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`; bodies over `MAX_REQUEST_BODY_BYTES` (1 MiB) get 413 `REQUEST_TOO_LARGE`.

## Role × Permission matrix

The role is per membership: a user's permissions are those of their role in the tenant of the token.

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

Tokens carry the membership's `role`; the API re-derives the permissions on every request via `permissions_for(role)`, so you do not need to reissue tokens when the mapping changes. The access token also lists them in `perms` for other services (faclab-invoicing).

## Managing users of a tenant

`/api/admin/users` (permission `user:manage`) always works inside the caller's tenant (`tid`): it lists, creates and changes the members of that tenant, and a user of another tenant answers 404.

- `role` and `isActive` are those of the membership. Deactivating removes the user from this tenant only (their other tenants don't change) and closes their sessions here.
- Creating a user creates the global account and its membership. Usernames and emails are unique across the platform, so a name taken in another tenant answers `USERNAME_ALREADY_EXISTS`.
- The password and the full name are the same in every tenant: `reset-password` and `profile` answer 409 `USER_IN_OTHER_TENANTS` when the user also has an active membership elsewhere, so the admin of one company can't take over the user's access to another.
- The last active admin of a tenant can't be deactivated or demoted; another tenant's admins don't count.

## Provisioning tenants

Tenants are created from the platform CLI, idempotently: running it again reuses the tenant (by RUC), the user (by username) and the membership, which ends up as an active ADMIN.

```bash
PROVISION_ADMIN_PASSWORD=... python -m src.tenancy.provision \
  --ruc 1799999990001 --legal-name "Ferretería Ejemplo S.A." [--trade-name "La Ferre"] \
  --admin-username ana --admin-email ana@example.com [--admin-full-name "Ana Pérez"]
# or: make provision-tenant args="--ruc ... --legal-name ... --admin-username ... --admin-email ..."
```

The RUC must be a valid 13-digit one. The password goes in the environment, never in the arguments, and is only needed when the user doesn't exist yet: an existing user (an accountant of another company) joins with their own password. Branches, emission points and warehouses come in S2.5.

## Production checklist

- `JWT_SECRET` must be set (config `production.py` raises on missing / short secret).
- Seed the first tenant and its admin: `AUTH_SEED_USERNAME=... AUTH_SEED_EMAIL=... AUTH_SEED_PASSWORD=... AUTH_SEED_TENANT_RUC=... AUTH_SEED_TENANT_NAME=... python -m src.auth.seed` (locally the tenant defaults to a made-up RUC); further tenants with `python -m src.tenancy.provision`.
- Rotate `JWT_SECRET` invalidates all active tokens (users must log in again).
- Rate limiting on `/api/auth/login` is NOT implemented — put it at the reverse proxy if exposed publicly.
