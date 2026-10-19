# Auth API Specification — Frontend Implementation Guide

This document is a self-contained contract for implementing authentication and authorization in the Admin and POS frontends. All requests/responses use `camelCase` JSON.

---

## 1. Base URLs & Conventions

| Environment | Base URL |
|---|---|
| Local | `http://localhost:3000` |
| Staging / Prod | configured per deployment |

- **Content-Type**: `application/json` on all writes.
- **Auth header** (protected routes): `Authorization: Bearer <accessToken>`.
- **Public routes** (no auth header required): `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout`. `POST /api/auth/select-tenant` authenticates itself with the login's selection token or the current access token.
- **Tenants**: every session and token belongs to one tenant (company, one RUC); see §2.0. The frontend never sends a tenant id except to `select-tenant`.
- **Refresh cookie**: the refresh token never appears in a body. Login, select-tenant and refresh set it in the `faclab_refresh` cookie (`HttpOnly; Secure; SameSite=Strict; Path=/api/auth`; without `Secure` locally), refresh reads it and logout clears it. Browsers must send these calls with credentials (`withCredentials: true` / `credentials: "include"`); the API allows credentials for the origins in `CORS_ORIGINS`.
- **Response envelope** (success):
  ```json
  { "data": { ... }, "meta": { "requestId": "uuid", "timestamp": "ISO-8601" } }
  ```
  Paginated: adds `meta.pagination = { total, limit, offset }`.
- **Response envelope** (error):
  ```json
  {
    "errors": [{ "code": "INVALID_CREDENTIALS", "message": "...", "field": null }],
    "meta": { "requestId": "uuid", "timestamp": "ISO-8601" }
  }
  ```
- 204 No Content on successful password change (no envelope).

---

## 2. Data Model

### 2.0 Tenants and memberships

- A **tenant** is a company (one RUC): `{ id (UUID), ruc, legalName, tradeName }`.
- A **user** is global: username and email are unique across the platform, and the password and full name are the same in every tenant.
- A **membership** gives the user a role in a tenant. Role and permissions in a session are those of the membership in the session's tenant; the same person may be ADMIN in one company and VIEWER in another.
- The tenant of a session comes from the token (`tid`); switching tenants means new tokens (§3.1bis).

### 2.1 Role (integer codes)

| Code | Role | Typical UI |
|---|---|---|
| 1 | `ADMIN` | Admin |
| 2 | `MANAGER` | Admin |
| 3 | `OPERATOR` | Admin |
| 4 | `VIEWER` | Admin (read-only) |
| 5 | `CASHIER` | POS |

Frontend should maintain a `ROLE` enum mirroring these codes.

### 2.2 Permission strings (canonical list)

Catalog: `product:read`, `product:write`, `category:write`, `uom:write`
Inventory: `stock:read`, `movement:write`, `warehouse:write`, `location:write`, `lot:write`, `serial:write`, `adjustment:write`, `transfer:write`, `alert:read`
Sales: `sale:read`, `sale:write`, `sale:cancel`
Purchasing: `purchase:read`, `purchase:write`, `purchase:confirm`, `purchase:receive`
Partners: `customer:read`, `customer:write`, `supplier:read`, `supplier:write`
POS: `pos:operate`, `refund:approve`
Reports: `report:inventory:read`, `report:pos:read`
Organization: `organization:read`, `organization:write`
Admin: `user:manage`

### 2.3 Role → Permission matrix (source of truth for UI guards)

| Permission | ADMIN | MANAGER | OPERATOR | VIEWER | CASHIER |
|---|:-:|:-:|:-:|:-:|:-:|
| product:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| product:write | ✓ | ✓ | ✓ |   |   |
| category:write | ✓ | ✓ | ✓ |   |   |
| uom:write | ✓ | ✓ | ✓ |   |   |
| stock:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| movement:write | ✓ | ✓ | ✓ |   |   |
| warehouse:write | ✓ | ✓ |   |   |   |
| location:write | ✓ | ✓ |   |   |   |
| lot:write | ✓ | ✓ | ✓ |   |   |
| serial:write | ✓ | ✓ | ✓ |   |   |
| adjustment:write | ✓ | ✓ | ✓ |   |   |
| transfer:write | ✓ | ✓ | ✓ |   |   |
| alert:read | ✓ | ✓ | ✓ | ✓ |   |
| sale:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| sale:write | ✓ | ✓ | ✓ |   | ✓ |
| sale:cancel | ✓ | ✓ |   |   |   |
| purchase:read | ✓ | ✓ | ✓ | ✓ |   |
| purchase:write | ✓ | ✓ | ✓ |   |   |
| purchase:confirm | ✓ | ✓ |   |   |   |
| purchase:receive | ✓ | ✓ | ✓ |   |   |
| customer:read | ✓ | ✓ | ✓ | ✓ | ✓ |
| customer:write | ✓ | ✓ | ✓ |   | ✓ |
| supplier:read | ✓ | ✓ | ✓ | ✓ |   |
| supplier:write | ✓ | ✓ | ✓ |   |   |
| pos:operate | ✓ |   |   |   | ✓ |
| refund:approve | ✓ | ✓ |   |   |   |
| report:inventory:read | ✓ | ✓ | ✓ | ✓ |   |
| report:pos:read | ✓ | ✓ |   |   | ✓ |
| organization:read | ✓ | ✓ | ✓ | ✓ |   |
| organization:write | ✓ |   |   |   |   |
| user:manage | ✓ |   |   |   |   |

> Treat `GET /api/auth/me` as the authoritative list at runtime. The matrix above is for designing static UI route guards.

---

## 3. Public Endpoints

### 3.1 `POST /api/auth/login`

**Request**
```json
{ "username": "admin", "password": "ChangeMe123!" }
```

Validation: `username` 1..64 chars, `password` 1..128 chars.

**200 Response, one active tenant**: the session opens in it (plus `Set-Cookie: faclab_refresh=...; HttpOnly; Path=/api/auth; SameSite=strict`)
```json
{
  "data": {
    "accessToken": "eyJhbGciOi...",
    "tokenType": "Bearer",
    "expiresIn": 900,
    "tenant": { "id": "6f1c…", "ruc": "1799999990001", "legalName": "Ferretería Ejemplo S.A.", "tradeName": null }
  },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

**200 Response, several active tenants**: no session and no cookie yet; choose one with §3.1bis
```json
{
  "data": {
    "selectionToken": "eyJhbGciOi...",
    "expiresIn": 300,
    "tenants": [
      { "id": "6f1c…", "ruc": "1799999990001", "legalName": "Ferretería Ejemplo S.A.", "tradeName": null, "role": 1 },
      { "id": "a20e…", "ruc": "0999999999001", "legalName": "Comercial Dos S.A.", "tradeName": "Comercial Dos", "role": 4 }
    ],
    "branches": [
      { "id": 1, "establishmentCode": "001", "name": "Matriz", "isMain": true },
      { "id": 2, "establishmentCode": "002", "name": "Sucursal Norte", "isMain": false }
    ]
  },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```
Tell them apart by `accessToken` vs `selectionToken`. Only active memberships in active tenants are listed, sorted by `legalName`.

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 401 | `INVALID_CREDENTIALS` | Wrong user/pass **or** user account blocked |
| 403 | `NO_ACTIVE_TENANT` | Right credentials, but no active membership in an active tenant |
| 429 | `LOGIN_LOCKED` | Too many failed attempts for this username or client IP; wait and retry |
| 422 | `VALIDATION_ERROR` | Missing/invalid body |

**Lockout**: by default 5 failures for a username within 15 minutes lock it for 15 minutes, counted from the last failure; 20 failures from one client IP lock that IP the same way. While locked the password is not checked (the right one also gets `LOGIN_LOCKED`) and attempts are not counted, so the lock ends on time. Unknown usernames lock too, and their response takes as long as a real check, so neither reveals whether a username exists. A successful login clears the username's failures. Settings: `LOGIN_MAX_FAILURES_PER_USER`, `LOGIN_MAX_FAILURES_PER_IP`, `LOGIN_FAILURE_WINDOW_SECONDS`, `LOGIN_LOCKOUT_SECONDS`.

**Frontend behavior**
- On 200 with `accessToken`: keep it **in memory only** and compute `accessExpiresAt = now + expiresIn*1000`. The browser keeps the refresh cookie.
- On 200 with `selectionToken`: show the tenant picker (keep the selection token in memory; it expires in `expiresIn` seconds), then call §3.1bis.
- Then call `GET /api/auth/me` to hydrate the session (tenant, role, permissions).
- On `LOGIN_LOCKED`: show "Demasiados intentos fallidos. Espera unos minutos e intenta de nuevo."
- On `NO_ACTIVE_TENANT`: show "Tu usuario no tiene acceso a ninguna empresa activa."

### 3.1bis `POST /api/auth/select-tenant`

Opens a session in one of the user's tenants. Used after a login that returned `selectionToken`, and to **switch tenants** from an open session.

**Request**: `Authorization: Bearer <selectionToken>` (after login) or `Authorization: Bearer <accessToken>` (switching), with credentials, and
```json
{ "tenantId": "a20e…" }
```

**200 Response**: same shape as a one-tenant login (`accessToken`, `tokenType`, `expiresIn`, `tenant`) and a new refresh cookie. When switching, the current session is closed: its refresh token stops working.

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 401 | `INVALID_TOKEN` | No token, a refresh token, or the current session already ended (logout) → force re-login |
| 401 | `TOKEN_EXPIRED` | Selection token expired → log in again |
| 403 | `TENANT_ACCESS_DENIED` | The user has no active membership in that tenant, or the tenant is suspended |
| 422 | `VALIDATION_ERROR` | `tenantId` missing or not a UUID |

### 3.2 `POST /api/auth/refresh`

**Request**: no body; the `faclab_refresh` cookie identifies the session.

**200 Response**: same shape as a one-tenant `/login` (with the session's `tenant`), with a new access token and a new refresh cookie of the same session. The session's expiry moves forward 7 days. The tenant doesn't change; the role is re-read from the membership, so a role change shows up here.

**Rotation**: each refresh replaces the refresh token; only the newest one is valid. Presenting an already used refresh token means it may have been stolen, so the session is revoked and the call fails with `TOKEN_REUSED`. One exception keeps concurrent tabs (or a lost response) working: the token replaced less than `JWT_REFRESH_REUSE_GRACE_SECONDS` ago (default 30) gets the current session's token back without rotating again.

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 401 | `TOKEN_EXPIRED` | Refresh token expired → force re-login |
| 401 | `INVALID_TOKEN` | No cookie, not a refresh token / malformed, or its session ended (logout, password change or reset, removed from the tenant, tenant suspended, switched tenants) → force re-login |
| 401 | `TOKEN_REUSED` | An already used refresh token; the session is now revoked → force re-login |

### 3.3 `POST /api/auth/logout`

**Request**: no body; reads the `faclab_refresh` cookie.

**204**, always, and the cookie is cleared: the session is revoked, so its refresh token can't be used again. A missing, expired, invalid or already-closed token leaves nothing to close and also returns 204. Clear the in-memory session afterwards; the access token keeps working until it expires (15 min).

---

## 4. Authenticated Endpoints (common)

### 4.1 `GET /api/auth/me`

No body. Requires `Authorization: Bearer <access>`.

**200 Response**
```json
{
  "data": {
    "id": 1,
    "username": "admin",
    "fullName": "Ana Pérez",
    "role": 1,
    "permissions": ["product:read", "product:write", "user:manage", "..."],
    "mustChangePassword": false,
    "tenant": { "id": "6f1c…", "ruc": "1799999990001", "legalName": "Ferretería Ejemplo S.A.", "tradeName": null },
    "tenants": [
      { "id": "6f1c…", "ruc": "1799999990001", "legalName": "Ferretería Ejemplo S.A.", "tradeName": null, "role": 1 },
      { "id": "a20e…", "ruc": "0999999999001", "legalName": "Comercial Dos S.A.", "tradeName": "Comercial Dos", "role": 4 }
    ]
  },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

Use this to build the in-memory session (`tenant`, `role`, `permissions: Set<string>`, `mustChangePassword`). `role` and `permissions` are those of the membership in `tenant`; `tenants` lists where the user can switch to (show a switcher only when there is more than one). `branches` are the active branches of `tenant` the user may enter, the choices of the branch selector and the values of `X-Branch-Id` (§6).

> **`mustChangePassword`**: when `true`, every permission-gated endpoint returns 403 `PASSWORD_CHANGE_REQUIRED`. Only `/api/auth/me` and `/api/auth/change-password` keep working. The frontend MUST redirect the user to a mandatory change-password screen and block the rest of the app until the flag flips back to `false` (which requires a new login or a fresh `/me` after change-password).

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 401 | `TOKEN_EXPIRED` | Try refresh, then retry once |
| 401 | `INVALID_TOKEN` | Force re-login |
| 401 | `TENANT_REQUIRED` | Token issued before tenants existed → force re-login |
| 403 | `PERMISSION_DENIED` | Missing/absent `Authorization` header |
| 403 | `BRANCH_ACCESS_DENIED` | `X-Branch-Id` of a branch the user can't enter (any authenticated route) |
| 422 | `INVALID_BRANCH_HEADER` | `X-Branch-Id` is not a branch id |

### 4.2 `POST /api/auth/change-password`

**Request**
```json
{ "currentPassword": "old", "newPassword": "newAtLeast8" }
```
Validation: `newPassword` ≥ 8 chars, ≤ 128.

**204 No Content** on success (no body).

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 401 | `INVALID_CREDENTIALS` | `currentPassword` wrong |
| 422 | `VALIDATION_ERROR` | `newPassword` too short (the rejected value never reaches the logs) |
| 401 | `TOKEN_EXPIRED` / `INVALID_TOKEN` | Auth problem |

**Frontend behavior**:
- On success the server clears the `mustChangePassword` flag in the DB, but **the access/refresh tokens already in the client still carry `mcp=true`**. To unblock the user, either:
  1. Log out and log back in (new tokens come with `mcp=false`), or
  2. Call `POST /api/auth/refresh` to get a fresh token pair — the refresh handler re-reads the user so the new tokens will be clean.
- The change closes every other session of the user (other devices must log in again); the session that made the change stays open, so option 2 works.

  Do this automatically after a 204; otherwise the UI stays stuck on the "must change password" screen even though the DB is updated.
- After success (and token rotation), call `GET /api/auth/me` to confirm `mustChangePassword: false`.

---

## 5. Admin-only Endpoints — User Management

Base prefix: `/api/admin/users`. All require permission `user:manage` (only `ADMIN` has it today). Any other role must get a 403 `PERMISSION_DENIED` and see a generic "no access" UI.

Everything here happens **inside the caller's tenant** (the `tid` of the token): the list shows the members of that tenant, `role` and `isActive` are those of the membership, and a user who isn't a member answers 404 `NOT_FOUND`.

### 5.1 `GET /api/admin/users` — list users (paginated)

**Query params** (all optional)
- `limit` (1..1000, default 100)
- `offset` (≥0, default 0)
- `isActive` (boolean)
- `role` (1..5)

**200 Response**
```json
{
  "data": [
    {
      "id": 1,
      "username": "admin",
      "email": "admin@faclab.local",
      "fullName": "Ana Pérez",
      "role": 1,
      "isActive": true,
      "mustChangePassword": false,
      "lastLoginAt": "2026-04-18T10:00:00Z",
      "createdAt": "2026-01-01T00:00:00Z"
    }
  ],
  "meta": {
    "requestId": "...",
    "timestamp": "...",
    "pagination": { "total": 12, "limit": 100, "offset": 0 }
  }
}
```

### 5.2 `GET /api/admin/users/{userId}` — get by id

404 `NOT_FOUND` if missing or not a member of the caller's tenant.

### 5.3 `POST /api/admin/users` — create

**Request**
```json
{
  "username": "cashier01",
  "email": "c01@faclab.local",
  "password": "MinLen8!",
  "role": 5,
  "fullName": "Luis Cajero"
}
```
Validation: `username` 1..64, `email` 1..128, `password` 8..128, `role` 1..5 (defaults to 4 `VIEWER`), `fullName` optional ≤ 64.

`fullName` is the name the user signs documents with (shift cashier, POS sale, cash movement, refund, adjustment, transfer); without one, the username signs. The API takes it from the token, never from the request body.

The user is created with a membership in the caller's tenant and the given `role`. Usernames and emails are unique across the platform: one taken in another company also answers 409. (Adding an existing user of another company is not possible from here yet.)

**200 Response**: `DataResponse<UserResponse>` (same shape as list item).

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 409 | `USERNAME_ALREADY_EXISTS` | Duplicate username |
| 409 | `EMAIL_ALREADY_EXISTS` | Duplicate email |
| 422 | `VALIDATION_ERROR` | Body invalid |

### 5.4 `PUT /api/admin/users/{userId}/role`

**Request** `{ "role": 3 }` (1..5)

Changes the role in the caller's tenant only. Returns updated `UserResponse`. 404 if user missing, 422 on bad role, 409 `LAST_ADMIN` when it would leave the tenant without an active admin.

### 5.4bis `PUT /api/admin/users/{userId}/profile`

**Request** `{ "fullName": "Luis Cajero" }` (≤ 64; empty or `null` clears it)

Returns updated `UserResponse`. 404 if user missing. Access tokens already issued keep the previous name until their next refresh. The name is the same in every tenant: 409 `USER_IN_OTHER_TENANTS` if the user also belongs to another one.

### 5.4ter `GET` / `PUT /api/admin/users/{userId}/branches`

**Request** (PUT) `{ "branchIds": [1, 3] }` · **Response** `{ "userId": 7, "branchIds": [1, 3] }`

The branches of the caller's tenant the user may enter; an empty list means all of them (the default). The PUT replaces the list. It applies from the user's next login or refresh (claim `bids`, §6), like a role change; sessions are not revoked. 404 if the user isn't in the tenant; 422 `REFERENCE_NOT_FOUND` for a branch that isn't the tenant's.

### 5.5 `POST /api/admin/users/{userId}/activate`

No body. Gives the user back access to the caller's tenant (activates the membership). Returns updated `UserResponse`; re-activating an active user is safe.

### 5.6 `POST /api/admin/users/{userId}/deactivate`

No body. Removes the user from the caller's tenant (deactivates the membership); their other tenants don't change. Returns updated `UserResponse`. Their sessions in this tenant are revoked: their **access tokens still work until they expire**, but `/refresh` fails with `INVALID_TOKEN`. 409 `LAST_ADMIN` if they are the tenant's only active admin.

### 5.7 `POST /api/admin/users/{userId}/reset-password` — admin-assisted reset

Use this when a non-admin user forgets their password. Sets a temporary password and forces a must-change on next action.

**Request**
```json
{ "newPassword": "TempPass123" }
```
Validation: `newPassword` 8..128 chars.

**200 Response**: `DataResponse<UserResponse>` with `mustChangePassword: true`.

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 404 | `NOT_FOUND` | Target user id does not exist or isn't a member of the caller's tenant |
| 409 | `USER_IN_OTHER_TENANTS` | The user also belongs to another tenant: the password works there too, so this tenant can't change it |
| 422 | `VALIDATION_ERROR` | `newPassword` too short |
| 403 | `PERMISSION_DENIED` | Caller lacks `user:manage` |

**Side effects**
- Rotates `passwordHash` for the target user.
- Sets `mustChangePassword=true` in the DB.
- Emits `UserPasswordReset` domain event (`user_id`, `username`, `reset_by_user_id`).
- Revokes every session of the target user, so their refresh tokens stop working. Access tokens already issued keep `mcp=false` until they expire (15 min).

**Frontend UX (Admin Users page)**
- Row action "Reset password" opens a modal.
- Let the admin type a temporary password (or generate one client-side and show it once — e.g. 12 random chars).
- After success, show the temp password **once** with a "Copy" button and a banner: "Comparte esta contraseña con el usuario por un canal seguro. No la podrás ver de nuevo." Admin communicates it out-of-band (chat, phone, in-person).
- Next time the user logs in with that temp password, login succeeds and the response/`/me` returns `mustChangePassword: true` → frontend routes them to the mandatory change-password screen.

---

## 5bis. "Forgot password" flow — end to end

Since there is no email-based self-service reset yet, the procedure for a user who is locked out is:

1. **User** contacts an admin (chat, phone).
2. **Admin** opens the Admin Users page, finds the user, clicks "Reset password", sets or generates a temporary password.
3. **Admin** shares the temporary password with the user via a trusted channel.
4. **User** logs in with the temp password → gets tokens with `mcp=true`.
5. Frontend (Admin or POS shell) sees `mustChangePassword: true` and redirects to the change-password screen; blocks all other navigation.
6. **User** submits `currentPassword` (the temp one) + a new `newPassword`.
7. Backend updates the DB and clears the flag. Frontend immediately calls `/refresh` (or triggers logout → login) so the new tokens carry `mcp=false`.
8. Frontend calls `/me`, confirms `mustChangePassword: false`, routes to the normal home screen.

**ADMIN who forgot their own password**: no admin can reset another admin's password via API (any USER_MANAGE holder can, but today only role=1 has it). For a single-admin deployment, use the seed script (`python -m src.auth.seed`) from the server to bootstrap a new admin, or run a direct DB update. Document this recovery path in your operations runbook.

---

## 6. Token Lifecycle

| Token | Default TTL | Env var |
|---|---|---|
| Access | 900 s (15 min) | `JWT_ACCESS_TTL_SECONDS` |
| Refresh | 604800 s (7 days) | `JWT_REFRESH_TTL_SECONDS` |
| Tenant selection | 300 s (5 min) | `JWT_SELECTION_TTL_SECONDS` |

- Tokens are JWT HS256 (opaque to the frontend; do **not** parse claims client-side for auth decisions — rely on `/me`).
- On login, `expiresIn` is the access TTL in seconds.
- Login (one tenant) or select-tenant opens a **session** (`auth_sessions`) in one tenant; both tokens carry its id in the `sid` claim and the tenant in `tid`. `/refresh` only works while the session is active and pushes its expiry forward, so an active user stays signed in.
- An access token without `tid` answers 401 `TENANT_REQUIRED` on every protected route: log in again.
- The refresh token also carries `jti`, the rotation the session currently accepts (`auth_sessions.refresh_jti`). See §3.2 for rotation, the grace for the token just replaced and `TOKEN_REUSED`.
- Sessions end on `POST /api/auth/logout`, on a password change (every session except the one that made the change), on an admin reset, when the user is removed from the tenant, and when switching tenants (the previous one). Access tokens are not checked against the session and expire on their own.
- The access token also carries `role` and `perms` (the membership's role and its permission strings) so other services, such as faclab-invoicing, authorize the same way as this API, and `name` (the user's full name) when one is set.
- When the membership is limited to some branches (§5.4ter), the access token carries their ids in `bids`; without the claim the user may enter every branch of the tenant. A request names its branch in the `X-Branch-Id` header: any authenticated route rejects one the user can't enter (403 `BRANCH_ACCESS_DENIED`) or that is not an id (422 `INVALID_BRANCH_HEADER`), and branch operations need it (400 `BRANCH_REQUIRED`; today `GET /api/pos/terminals`, and shifts, sales and cash from S2.6).

---

## 7. Error Code Catalogue

| Code | HTTP | When it happens | Frontend action |
|---|---|---|---|
| `INVALID_CREDENTIALS` | 401 | Wrong username/password; inactive user on login; deactivated user on refresh | Show "usuario o contraseña inválidos"; on refresh → force re-login |
| `TOKEN_EXPIRED` | 401 | Access or refresh token past `exp` | Access → attempt refresh; Refresh → force re-login |
| `INVALID_TOKEN` | 401 | Bad signature, wrong typ (sent refresh where access needed), malformed; on refresh, no cookie or the session ended. The message is always the generic "invalid token" | Force re-login |
| `TOKEN_REUSED` | 401 | An already used refresh token was presented; the session was revoked | Force re-login |
| `TENANT_REQUIRED` | 401 | Access token without tenant (issued before tenants existed) | Force re-login |
| `LOGIN_LOCKED` | 429 | Too many failed logins for the username or the client IP | Show the lockout message; let the user retry later |
| `PERMISSION_DENIED` | 403 | No auth header OR user lacks required permission | No header → force login; lacks perm → show "no access" view |
| `PASSWORD_CHANGE_REQUIRED` | 403 | User has `mustChangePassword=true` and is calling a permission-gated route | Redirect to change-password screen; only `/me` and `/change-password` are reachable |
| `NO_ACTIVE_TENANT` | 403 | Login with right credentials but no active membership in an active tenant | Show "sin acceso a ninguna empresa" |
| `TENANT_ACCESS_DENIED` | 403 | `select-tenant` with a tenant the user can't enter | Refresh the tenant list (`/me` or log in again) |
| `BRANCH_ACCESS_DENIED` | 403 | `X-Branch-Id` of a branch the user can't enter | Refresh the branch list (`/me`) and pick another |
| `INVALID_BRANCH_HEADER` | 422 | `X-Branch-Id` is not a branch id | Fix the client |
| `BRANCH_REQUIRED` | 400 | A branch operation without `X-Branch-Id` | Ask the user to pick a branch |
| `USERNAME_ALREADY_EXISTS` | 409 | Create user conflict | Mark `username` field error |
| `EMAIL_ALREADY_EXISTS` | 409 | Create user conflict | Mark `email` field error |
| `LAST_ADMIN` | 409 | Deactivating or demoting the tenant's only active admin | Explain that another admin is needed first |
| `USER_IN_OTHER_TENANTS` | 409 | Reset password or rename a user who also belongs to another tenant | Explain that the user (or the platform) must do it |
| `NOT_FOUND` | 404 | User id missing | Show "user not found" |
| `VALIDATION_ERROR` | 422 | Body/query validation failed | Use `errors[i].field` for inline errors |
| `INTERNAL_ERROR` | 500 | Unexpected server failure | Generic toast + retry |

---

## 8. Frontend Integration Recipe

### 8.1 Storage

- **Access token**: in memory only (lost on reload).
- **Refresh token**: the HttpOnly `faclab_refresh` cookie; scripts can't read it.
- **Nothing secret in `localStorage` or `sessionStorage`.** A non-secret flag (e.g. `fc.hasSession`) may remember that a session exists, so the app only calls `/refresh` on load when there is one.
- On load, without an access token in memory: `POST /api/auth/refresh` (with credentials) → new access token → `GET /api/auth/me`.
- Several tabs: share new access tokens and logouts between tabs (e.g. `BroadcastChannel`) so each tab doesn't refresh on its own; the 30 s grace (§3.2) covers tabs that still refresh at the same moment.

### 8.2 HTTP client

Single axios/fetch wrapper with:

1. **Request interceptor**: if there is an access token in memory → attach `Authorization: Bearer <access>`.
2. **Response interceptor**: on `401 + code=TOKEN_EXPIRED`:
   - Call `/api/auth/refresh` with credentials and no body (deduplicated — use a shared in-flight promise so 10 parallel 401s trigger one refresh).
   - On success: replace the access token, retry the original request once.
   - On failure (any error from refresh, including `TOKEN_REUSED`): clear the session, redirect to login.
3. Never retry on `INVALID_TOKEN` / `INVALID_CREDENTIALS` / `TOKEN_REUSED` from `/refresh`.
4. Send credentials only on the `/api/auth/*` calls; other services (faclab-invoicing) don't allow them.

### 8.3 Session bootstrap

On app start / after login:
```
POST /api/auth/login          → access token (+ refresh cookie), or selectionToken + tenants
POST /api/auth/select-tenant  → (several tenants) access token (+ refresh cookie)
GET  /api/auth/me             → { id, username, fullName, role, permissions, mustChangePassword, tenant, tenants }
```
Store `{ id, username, tenant, tenants, role, permissions: new Set(permissions), mustChangePassword }` in app state (e.g. Pinia/Zustand/React context). Switching tenants: `POST /api/auth/select-tenant` with the current access token, then reload `/me` and drop every cache of the previous tenant.

**If `mustChangePassword === true`**: do NOT navigate to the normal home. Route to the mandatory change-password screen and render nothing else. The router guard below handles this centrally.

### 8.4 Route / component guards

```ts
const can = (perm: string) => session.permissions.has(perm);
const hasRole = (...roles: number[]) => roles.includes(session.role);
```

- **Global guard (both apps)**: if `session.mustChangePassword`, force the URL to `/change-password` and block every other route. Only logout and the change-password form itself are reachable.
- **Admin shell** (Vue/React router):
  - Redirect to `/login` if no session.
  - On each admin route, declare `meta: { requires: 'user:manage' | 'product:write' | ... }`. Reject with 403 page if `!can(meta.requires)`.
  - Hide nav items the user cannot access (don't just disable).
- **POS shell**:
  - Require `pos:operate`. Users without it (MANAGER, OPERATOR, VIEWER) see "este usuario no puede operar caja".
  - Refunds tab only visible if `can('refund:approve')`.
  - Gate "cancel sale" button with `can('sale:cancel')`; otherwise hide.

### 8.5 Which app should a user land in?

After `/me`:
```
if role == CASHIER (5)                 → redirect to POS app
else if role in {ADMIN, MANAGER,
                 OPERATOR, VIEWER}     → redirect to Admin app
ADMIN should also have a "Open POS" link (has pos:operate).
```

### 8.6 Proactive refresh (optional, recommended)

Schedule a refresh 60 s before `accessExpiresAt`:
```
setTimeout(() => refresh(), (expiresIn - 60) * 1000);
```
Replaces reactive 400-handling for most calls; keep the interceptor as a safety net.

### 8.7 Logout flow

1. `POST /api/auth/logout` with credentials (revokes the session and clears the cookie).
2. Clear the in-memory session and tell the other tabs.
3. Navigate to `/login`.
4. (Optional) Clear any SWR/React-Query caches tied to the user.

### 8.8 Change-password UX

- Form: `currentPassword`, `newPassword`, `confirmNewPassword` (client-side match).
- On 204:
  - Toast "contraseña actualizada".
  - **Always call `POST /api/auth/refresh`** before navigating — the new tokens will have `mcp=false`. Otherwise the user's stored tokens still carry `mcp=true` and every permission-gated call will return `PASSWORD_CHANGE_REQUIRED`, trapping them on the change-password screen.
  - Re-fetch `/me` to refresh the in-memory session, then route to home.
- On 400 `INVALID_CREDENTIALS`: inline error on `currentPassword`. In the "forgot password" flow, this is the typo of the admin-provided temp password.
- **Mandatory variant** (triggered by `mustChangePassword=true`): hide the "Cancel" / "Back" button; only allow submit or logout.

### 8.9 Admin user management UX (Users page)

Features to build, all gated by `user:manage`:

| UI | Endpoint |
|---|---|
| Paginated table with filters (active, role) | `GET /api/admin/users` |
| Row → detail drawer | `GET /api/admin/users/{id}` |
| "Create user" modal (username, email, password, role, full name) | `POST /api/admin/users` |
| Role dropdown inline edit | `PUT /api/admin/users/{id}/role` |
| "Edit name" row action | `PUT /api/admin/users/{id}/profile` |
| Activate / Deactivate toggle | `POST /api/admin/users/{id}/activate` / `.../deactivate` |
| "Reset password" row action + temp-password modal | `POST /api/admin/users/{id}/reset-password` |

Show role as a badge with the label from §2.1. Map integer → label in a single `ROLE_LABELS` dict.

### 8.10 Inactive user handling

- Login with a blocked account → 401 `INVALID_CREDENTIALS` (same wording as wrong password — intentional).
- Login of a user removed from every tenant → 403 `NO_ACTIVE_TENANT`.
- Active session whose user is removed from the tenant mid-flight → access token keeps working until it expires; next `/refresh` returns `INVALID_TOKEN` → force re-login. Don't try to detect this proactively.

---

## 9. Non-Auth request pattern (for reference)

All protected endpoints (admin + POS) follow the same auth-error convention. Any route may return `TOKEN_EXPIRED` / `INVALID_TOKEN` (401) or `PERMISSION_DENIED` (403) — handle them globally in the HTTP client, not per-screen. Author fields (`cashierName`, `createdBy`, `performedBy`, `refundedBy`, `adjustedBy`, `requestedBy`) come from the token; sending them in a body has no effect.

---

## 10. Local development

- `make seed-admin` creates the default tenant (a made-up RUC locally) and its `admin` user from the `AUTH_SEED_*` settings (see `src/auth/seed.py`). More tenants: `make provision-tenant args="..."` (see `docs/auth-spec.md`).
- Swagger/Scalar: `/docs`, `/docs/admin`, `/docs/pos` — "Auth" tag shows the common auth endpoints; "Users" tag shows the admin CRUD.
- To test quickly:
  ```bash
  TOKEN=$(curl -s -c cookies.txt -XPOST localhost:3000/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"ChangeMe123!"}' | jq -r .data.accessToken)
  curl -s localhost:3000/api/auth/me -H "Authorization: Bearer $TOKEN" | jq
  # Refresh with the cookie (and keep the rotated one)
  curl -s -b cookies.txt -c cookies.txt -XPOST localhost:3000/api/auth/refresh | jq
  ```
