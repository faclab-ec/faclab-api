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
- **Public routes** (no auth): `POST /api/auth/login`, `POST /api/auth/refresh`.
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

**200 Response**
```json
{
  "data": {
    "accessToken": "eyJhbGciOi...",
    "refreshToken": "eyJhbGciOi...",
    "tokenType": "Bearer",
    "expiresIn": 900
  },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 400 | `INVALID_CREDENTIALS` | Wrong user/pass **or** user inactive |
| 422 | `VALIDATION_ERROR` | Missing/invalid body |

**Frontend behavior**
- On 200: persist `accessToken`, `refreshToken`, compute `accessExpiresAt = now + expiresIn*1000`.
- Then call `GET /api/auth/me` to hydrate the session (role + permissions).

### 3.2 `POST /api/auth/refresh`

**Request**
```json
{ "refreshToken": "eyJhbGciOi..." }
```

**200 Response**: same shape as `/login` (new access + refresh tokens). Treat as full rotation; replace both.

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 400 | `TOKEN_EXPIRED` | Refresh token expired → force re-login |
| 400 | `INVALID_TOKEN` | Not a refresh token / malformed → force re-login |
| 400 | `INVALID_CREDENTIALS` | User was deactivated or deleted → force re-login |

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
    "role": 1,
    "permissions": ["product:read", "product:write", "user:manage", "..."],
    "mustChangePassword": false
  },
  "meta": { "requestId": "...", "timestamp": "..." }
}
```

Use this to build the in-memory session (`role`, `permissions: Set<string>`, `mustChangePassword`).

> **`mustChangePassword`**: when `true`, every permission-gated endpoint returns 403 `PASSWORD_CHANGE_REQUIRED`. Only `/api/auth/me` and `/api/auth/change-password` keep working. The frontend MUST redirect the user to a mandatory change-password screen and block the rest of the app until the flag flips back to `false` (which requires a new login or a fresh `/me` after change-password).

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 400 | `TOKEN_EXPIRED` | Try refresh, then retry once |
| 400 | `INVALID_TOKEN` | Force re-login |
| 400 | `PERMISSION_DENIED` | Missing/absent `Authorization` header |

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
| 400 | `INVALID_CREDENTIALS` | `currentPassword` wrong |
| 422 | `VALIDATION_ERROR` | `newPassword` too short |
| 400 | `TOKEN_EXPIRED` / `INVALID_TOKEN` | Auth problem |

**Frontend behavior**:
- On success the server clears the `mustChangePassword` flag in the DB, but **the access/refresh tokens already in the client still carry `mcp=true`**. To unblock the user, either:
  1. Log out and log back in (new tokens come with `mcp=false`), or
  2. Call `POST /api/auth/refresh` to get a fresh token pair — the refresh handler re-reads the user so the new tokens will be clean.

  Do this automatically after a 204; otherwise the UI stays stuck on the "must change password" screen even though the DB is updated.
- After success (and token rotation), call `GET /api/auth/me` to confirm `mustChangePassword: false`.

---

## 5. Admin-only Endpoints — User Management

Base prefix: `/api/admin/users`. All require permission `user:manage` (only `ADMIN` has it today). Any other role must get a 400 `PERMISSION_DENIED` and see a generic "no access" UI.

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

404 `NOT_FOUND` if missing.

### 5.3 `POST /api/admin/users` — create

**Request**
```json
{
  "username": "cashier01",
  "email": "c01@faclab.local",
  "password": "MinLen8!",
  "role": 5
}
```
Validation: `username` 1..64, `email` 1..128, `password` 8..128, `role` 1..5 (defaults to 4 `VIEWER`).

**200 Response**: `DataResponse<UserResponse>` (same shape as list item).

**Errors**
| Status | Code | Meaning |
|---|---|---|
| 400 | `USERNAME_ALREADY_EXISTS` | Duplicate username |
| 400 | `EMAIL_ALREADY_EXISTS` | Duplicate email |
| 422 | `VALIDATION_ERROR` | Body invalid |

### 5.4 `PUT /api/admin/users/{userId}/role`

**Request** `{ "role": 3 }` (1..5)

Returns updated `UserResponse`. 404 if user missing, 422 on bad role.

### 5.5 `POST /api/admin/users/{userId}/activate`

No body. Returns updated `UserResponse`. Idempotent-ish (re-activating active user is safe; check server if needed).

### 5.6 `POST /api/admin/users/{userId}/deactivate`

No body. Returns updated `UserResponse`. After this call, the target user's **access tokens still work until they expire**, but `/refresh` will fail with `INVALID_CREDENTIALS`. UI should assume the user is effectively signed-out on next token rotation.

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
| 404 | `NOT_FOUND` | Target user id does not exist |
| 422 | `VALIDATION_ERROR` | `newPassword` too short |
| 403 | `PERMISSION_DENIED` | Caller lacks `user:manage` |

**Side effects**
- Rotates `passwordHash` for the target user.
- Sets `mustChangePassword=true` in the DB.
- Emits `UserPasswordReset` domain event (`user_id`, `username`, `reset_by_user_id`).
- **Does NOT invalidate the target user's existing tokens** — old tokens issued before the reset keep `mcp=false` until they expire. For sensitive scenarios, combine with `/{userId}/deactivate` then `/activate`, or wait for access TTL to expire. (A future server-side `tokenVersion` would close this gap.)

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

- Tokens are JWT HS256 (opaque to the frontend; do **not** parse claims client-side for auth decisions — rely on `/me`).
- On login, `expiresIn` is the access TTL in seconds.
- Every refresh issues a **new refresh token**; discard the old one.
- On logout: client-side only — clear tokens from storage. There is no `/logout` endpoint.

---

## 7. Error Code Catalogue

| Code | HTTP | When it happens | Frontend action |
|---|---|---|---|
| `INVALID_CREDENTIALS` | 400 | Wrong username/password; inactive user on login; deactivated user on refresh | Show "usuario o contraseña inválidos"; on refresh → force re-login |
| `TOKEN_EXPIRED` | 400 | Access or refresh token past `exp` | Access → attempt refresh; Refresh → force re-login |
| `INVALID_TOKEN` | 400 | Bad signature, wrong typ (sent refresh where access needed), malformed | Force re-login |
| `PERMISSION_DENIED` | 400 | No auth header OR user lacks required permission | No header → force login; lacks perm → show "no access" view |
| `PASSWORD_CHANGE_REQUIRED` | 403 | User has `mustChangePassword=true` and is calling a permission-gated route | Redirect to change-password screen; only `/me` and `/change-password` are reachable |
| `USERNAME_ALREADY_EXISTS` | 400 | Create user conflict | Mark `username` field error |
| `EMAIL_ALREADY_EXISTS` | 400 | Create user conflict | Mark `email` field error |
| `NOT_FOUND` | 404 | User id missing | Show "user not found" |
| `VALIDATION_ERROR` | 422 | Body/query validation failed | Use `errors[i].field` for inline errors |
| `INTERNAL_ERROR` | 500 | Unexpected server failure | Generic toast + retry |

> Note: several auth failures surface as HTTP 400 (not 401/403) per the shared `ApplicationError` convention. Discriminate by `errors[0].code`, not status code alone.

---

## 8. Frontend Integration Recipe

### 8.1 Storage

- **Admin web**: `localStorage` keys `fc.access`, `fc.refresh`, `fc.accessExpiresAt`. Acceptable for internal tool.
- **POS web**: same. If POS runs on shared devices, prefer `sessionStorage` + short access TTL; consider auto-lock on idle.

### 8.2 HTTP client

Single axios/fetch wrapper with:

1. **Request interceptor**: if `fc.access` present → attach `Authorization: Bearer <access>`.
2. **Response interceptor**: on `400 + code=TOKEN_EXPIRED`:
   - Call `/api/auth/refresh` with `fc.refresh` (deduplicated — use a shared in-flight promise so 10 parallel 401s trigger one refresh).
   - On success: replace tokens, retry the original request once.
   - On failure (any error from refresh): clear tokens, redirect to login.
3. Never retry on `INVALID_TOKEN` / `INVALID_CREDENTIALS` from `/refresh`.

### 8.3 Session bootstrap

On app start / after login:
```
POST /api/auth/login → tokens
GET  /api/auth/me    → { id, username, role, permissions, mustChangePassword }
```
Store `{ id, username, role, permissions: new Set(permissions), mustChangePassword }` in app state (e.g. Pinia/Zustand/React context).

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

1. Clear `fc.*` storage keys.
2. Clear in-memory session.
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
| "Create user" modal (username, email, password, role) | `POST /api/admin/users` |
| Role dropdown inline edit | `PUT /api/admin/users/{id}/role` |
| Activate / Deactivate toggle | `POST /api/admin/users/{id}/activate` / `.../deactivate` |
| "Reset password" row action + temp-password modal | `POST /api/admin/users/{id}/reset-password` |

Show role as a badge with the label from §2.1. Map integer → label in a single `ROLE_LABELS` dict.

### 8.10 Inactive user handling

- Login with inactive user → 400 `INVALID_CREDENTIALS` (same wording as wrong password — intentional).
- Active session that is deactivated mid-flight → access token keeps working until it expires; next `/refresh` returns `INVALID_CREDENTIALS` → force re-login. Don't try to detect this proactively.

---

## 9. Non-Auth request pattern (for reference)

All protected endpoints (admin + POS) follow the same 400-auth-error convention. Any route may return `TOKEN_EXPIRED`, `INVALID_TOKEN`, or `PERMISSION_DENIED` — handle them globally in the HTTP client, not per-screen.

---

## 10. Local development

- Bootstrap seed creates an `admin` user: username `admin`, password `ChangeMe123!` (see `src/auth/seed.py`).
- Swagger/Scalar: `/docs`, `/docs/admin`, `/docs/pos` — "Auth" tag shows the 4 common endpoints; "Users" tag shows the admin CRUD.
- To test quickly:
  ```bash
  TOKEN=$(curl -s -XPOST localhost:3000/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"ChangeMe123!"}' | jq -r .data.accessToken)
  curl -s localhost:3000/api/auth/me -H "Authorization: Bearer $TOKEN" | jq
  ```
