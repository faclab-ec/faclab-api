# Auth Spec — Faclab Core

JWT-based authentication (Ed25519-signed tokens, public keys at `/.well-known/jwks.json`) with role-based authorization. All admin and POS routes require a valid access token. Login, select-tenant, refresh and logout are public.

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

## Token signing and JWKS (S6.1)

Tokens are signed with an **Ed25519** key (`alg: EdDSA`). The header names the key in `kid`, the RFC 7638 thumbprint of its public JWK, so nothing about it is configured and two keys never share one. The public keys are published, without authentication, at:

```
GET /.well-known/jwks.json      Cache-Control: public, max-age=300
{"keys": [{"kty": "OKP", "crv": "Ed25519", "x": "…", "kid": "…", "alg": "EdDSA", "use": "sig"}]}
```

faclab-invoicing verifies access tokens with that set (cached in memory, fetched again after 10 minutes and for an unknown `kid`). It holds nothing that could issue a token, so compromising it doesn't compromise the core (G-48). The core accepts a token only when its `kid` is one of the published keys, its signature verifies with that key, and its `iss` is `JWT_ISSUER` and its `aud` lists `JWT_AUDIENCE` (`faclab-core`). Another `alg` (`HS256` keyed with the public key, `none`), an unknown or missing `kid`, or a missing `aud` answer 401 `INVALID_TOKEN`.

**Audiences.** Refresh and selection tokens are for the core only: `aud: "faclab-core"`. Access tokens also name the services that accept them (`JWT_SERVICE_AUDIENCES`, default `faclab-invoicing`): `aud: ["faclab-core", "faclab-invoicing"]`. faclab-invoicing requires its own name, so a refresh token is no good there.

**Keys.** The signing key is a PEM (PKCS#8) Ed25519 private key in `JWT_PRIVATE_KEY` or in the file named by `JWT_PRIVATE_KEY_FILE` (a mounted secret), never both. A variable that can't hold newlines may carry them as `\n`. `JWT_PUBLIC_KEYS` / `JWT_PUBLIC_KEYS_FILE` hold more public keys, PEM blocks one after the other, that are also accepted and published. Locally, without a key, a fixed development key derived from a seed in the code signs, so tokens survive a hot reload. Staging and production refuse to start without a key, with a key that isn't Ed25519 or can't be read, or with the development key, whether signing or published. The messages name the variable, never its value.

```bash
openssl genpkey -algorithm ed25519 -out jwt-2026-11.pem      # private: the secret manager only
openssl pkey -in jwt-2026-11.pem -pubout -out jwt-2026-11.pub.pem
```

### Rotating the key

Two keys are active during a rotation, so it closes no session:

1. **Generate** the new key K2. Optionally, publish it first by deploying with `JWT_PUBLIC_KEYS` = the public key of K2. Nothing signs with it yet.
2. **Switch.** Deploy with K2 as the signing key and `JWT_PUBLIC_KEYS` = the public key of K1. New tokens carry the `kid` of K2. The access and refresh tokens of K1 keep working in the core and in faclab-invoicing, which fetches the JWKS again as soon as it sees the new `kid`.
3. **Retire.** After `JWT_REFRESH_TTL_SECONDS` (7 days by default) from step 2, no valid token was signed with K1: remove it from `JWT_PUBLIC_KEYS`, deploy, and destroy K1. faclab-invoicing drops it at its next fetch (10 minutes at most).

If K1 leaked, skip the wait: switch and retire in one deploy, which logs everyone out.

Changing from HS256 to EdDSA (this release) invalidates every session once. To roll it back, deploy the previous images, faclab-invoicing first, with the old `JWT_SECRET`, which stays in the secret manager for one release.

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
| `integration:manage` | ✓ |   |   |   |   |

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

## Integration clients (S6.2)

An **integration client** is a system of the tenant (an ecommerce, an ERP) that calls the API with OAuth 2.0 *client credentials*, without a person's account. It is a service principal of its tenant: what it may do is its **scopes**, not a role. Decisions in [ADR-0008](architecture/ADR/0008-api-publica-versionada-y-credenciales-de-integracion.md) and [PUBLIC_API.md §3](architecture/PUBLIC_API.md).

**Managing them.** `/api/admin/integrations` (permission `integration:manage`, ADMIN only) creates, lists, changes and revokes the tenant's clients:

| Route | What it does | Audited as |
|---|---|---|
| `POST /api/admin/integrations` | `name`, `scopes`, optional `branchIds` and `allowedIps` (CIDR). Answers the `clientId` and its first `clientSecret`, **shown only in this response** | `integration.created` |
| `GET /api/admin/integrations`, `GET …/{id}` | The clients with their secrets' metadata (prefix, created, expires, revoked, last used), never their value | — |
| `PUT …/{id}` | Name, scopes, branches, addresses | `integration.updated` |
| `POST …/{id}/secrets` | Rotation: a new secret (shown once) next to the current one, at most two active (`INTEGRATION_SECRET_LIMIT_REACHED`, 409); `previousExpiresInDays` makes the current ones expire (0: now) | `integration.secret_created` |
| `POST …/{id}/secrets/{secretId}/revoke` | Revokes a secret | `integration.secret_revoked` |
| `POST …/{id}/revoke` | Revokes the client for good, and its secrets | `integration.revoked` |
| `GET …/{id}/usage` | Per day: tokens obtained and refused, requests, errors, last source address (`fromDate`/`toDate`, the last 30 days by default) | — |

No branches (or no addresses) means all of them. A branch that isn't the tenant's answers `REFERENCE_NOT_FOUND` (422), a scope outside the tenant's plan `SCOPE_NOT_IN_PLAN` (409; every plan has every scope until S8.4), a revoked client `INTEGRATION_CLIENT_REVOKED` (409).

**Secrets.** The `clientId` is public and says the environment: `fl_live_…` in production, `fl_test_…` in a sandbox. The environment is the deployment's (`INTEGRATION_ENVIRONMENT`: `production` in production, `sandbox` elsewhere): clients are created in it and only those get tokens, so the credentials of a production database restored in staging don't work there. The secret is 256 random bits (`secrets.token_urlsafe(32)`); only its SHA-256 and its first six characters are kept. A slow hash (bcrypt) protects passwords people choose; a random 256-bit secret can't be guessed either way, and a fast hash keeps the token endpoint from spending CPU on every attempt. Comparisons are constant time, and an unknown `clientId` costs the same. Neither the secret nor its hash reaches the audit log, a response after its creation or a log (`secret_hash` is one of the redacted keys).

**Token.** `POST /api/oauth/token` (public), `application/x-www-form-urlencoded`, credentials with HTTP Basic (`client_secret_basic`) or in the form (`client_id`, `client_secret`), never both:

```bash
curl -s http://localhost:3000/api/oauth/token \
  -u "$FACLAB_CLIENT_ID:$FACLAB_CLIENT_SECRET" \
  -d grant_type=client_credentials -d scope="stock:read sales:write"
# {"access_token": "eyJ…", "token_type": "Bearer", "expires_in": 900, "scope": "sales:write stock:read"}
```

The answers follow RFC 6749, not the API's envelope, so OAuth libraries understand them: `{"error", "error_description"}` with 400 `invalid_request` / `unsupported_grant_type` / `invalid_scope`, 401 `invalid_client` (with `WWW-Authenticate: Basic`; a wrong secret, an unknown, revoked or other environment's client, an address it isn't allowed from or a suspended tenant all look the same, the log says which), and 503 `temporarily_unavailable` with `INTEGRATIONS_ENABLED=false`. Without `scope` the token gets every scope of the client. It lasts `JWT_ACCESS_TTL_SECONDS` and has no refresh: the client asks again.

```json
{"sub": "client:fl_live_3f2a9c1b0d4e", "azp": "fl_live_3f2a9c1b0d4e", "tid": "8d1c…",
 "scope": "sales:write stock:read", "bids": [12], "cred": 41, "typ": "access",
 "iss": "faclab-core", "aud": "faclab-core", "iat": 1763380000, "exp": 1763380900}
```

`bids` only when the client is limited to some branches; `cred` is the secret it was obtained with. `aud` is only `faclab-core` until faclab-invoicing's public API checks scopes (S6.3): no `perms`, so its internal routes refuse it. The user methods of the token service (access, refresh, selection) never take an integration's token, and `decode_bearer` tells them apart by `sub`.

**Using it.** `AuthMiddleware` reads an integration's token into `request.state.integration` (an `IntegrationPrincipal`) and runs the request in its tenant with `TenantContext.integration_id` and the client's name as `user_name`, so an audited write records `actor_integration_id` and the name with no user (`GET /api/admin/audit-log?actorIntegrationId=`). Before that it checks the client's current state through `IntegrationAccess` (`src/integrations/infra/access.py`), read with a session of its own and cached per process at most `INTEGRATION_STATUS_CACHE_SECONDS` (30, between 0 and 60):

- a revoked client, a revoked or expired secret (`cred`), another environment or an address outside `allowedIps` make the token invalid (401 `INVALID_TOKEN`): **revoking takes effect within a minute**;
- its scopes and branches are those of the token narrowed to the client's current ones, so taking one away applies before the token expires.

Each request of an integration counts in its usage of the day (one upsert in a transaction of its own) and updates its `lastUsedAt`; a failure there is logged and never breaks the response.

The routes of the frontend (`/api/admin`, `/api/pos`, `/api/auth`) are the internal contract: `get_current_user`, and so every `require_permission`, answers 403 `INTEGRATION_NOT_ALLOWED` to an integration. Its routes (the public API `/api/v1`, S6.3) declare what they need with `require_scope(Scope.X)` (`src/auth/infra/dependencies.py`): a missing scope answers 403 `INSUFFICIENT_SCOPE`, a user's token 403 `PERMISSION_DENIED`. `require_branch` works for both, so a client limited to a branch gets `BRANCH_ACCESS_DENIED` in another.

**Scopes.** Each scope stands for the permissions that guard the same resources for a user (`PERMISSIONS_BY_SCOPE`, `src/auth/domain/scopes.py`); `IntegrationPrincipal.permissions` is their union. `tests/unit/auth/test_scopes.py` spells out the whole table and checks that no scope reaches an admin permission.

| Scope | Permissions |
|---|---|
| `products:read` | `product:read` |
| `products:write` | `product:write`, `category:write`, `uom:write` |
| `prices:read` | `product:read` (price lists) |
| `prices:write` | `product:write` (price lists) |
| `stock:read` | `stock:read` |
| `inventory:write` | `adjustment:write`, `transfer:write` |
| `customers:read` / `customers:write` | `customer:read` / `customer:write` |
| `sales:read` | `sale:read` |
| `sales:write` | `sale:write`, `sale:cancel` |
| `invoices:read` | `sale:read` |
| `webhooks:manage` | none yet (S6.4) |

**Rollback.** `INTEGRATIONS_ENABLED=false` makes the token endpoint answer 503 and every integration token invalid; the clients and their secrets stay.

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

- `JWT_PRIVATE_KEY_FILE` (or `JWT_PRIVATE_KEY`) must hold the Ed25519 signing key; staging and production refuse to start without it, with an unreadable one or with the development key. faclab-invoicing needs `JWT_JWKS_URL` pointing at `/.well-known/jwks.json` (internal network), and no secret of the core.
- Seed the first tenant and its admin: `AUTH_SEED_USERNAME=... AUTH_SEED_EMAIL=... AUTH_SEED_PASSWORD=... AUTH_SEED_TENANT_RUC=... AUTH_SEED_TENANT_NAME=... python -m src.auth.seed` (locally the tenant defaults to a made-up RUC); further tenants with `python -m src.tenancy.provision`.
- Rotate the signing key with the two-key procedure in [Rotating the key](#rotating-the-key); removing the previous key early logs everyone out.
- `INTEGRATION_ENVIRONMENT` is `production` in production (its default there) and `sandbox` in every other deployment, so integration credentials only work where they were created. `INTEGRATION_STATUS_CACHE_SECONDS` (at most 60) bounds how long a revoked integration client keeps working.
- Rate limiting on `/api/auth/login` is NOT implemented — put it at the reverse proxy if exposed publicly.
