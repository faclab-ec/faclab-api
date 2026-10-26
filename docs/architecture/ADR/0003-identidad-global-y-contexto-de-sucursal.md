# ADR-0003: Identidad global con membresías, token por empresa y sucursal validada

- **Estado:** aceptado (2026-10-15; empresa y membresías implementadas en S2.1, sucursal en S2.5)
- **Relacionado:** [ADR-0002](0002-multiempresa-base-compartida-con-rls.md), [MULTI_TENANCY.md](../MULTI_TENANCY.md)

## Contexto

Hoy un usuario tiene un único rol global y los tokens no llevan empresa ni sucursal. En Ecuador es
común que un contador externo atienda a varias empresas y que un dueño administre varias sucursales.
La empresa activa no puede depender de un `tenant_id` enviado libremente por el frontend.

## Alternativas

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| A. Usuario pertenece a una sola empresa; usuario único por empresa | Simple | Login ambiguo si se repite el usuario en dos empresas; contador externo necesita varias cuentas |
| B. Identidad global + membresías (usuario ↔ empresa con rol) y token emitido para una empresa | Un login para varias empresas; cambio de empresa explícito; aislamiento en el token | Una tabla más y un paso de selección cuando hay varias empresas |
| C. Token con todas las empresas del usuario | Sin cambio de token | Cada request debe indicar la empresa y validarla; token más grande |

## Decisión

**B.**

- `users` es global (usuario y email únicos en la plataforma). `memberships(user_id, tenant_id, role,
  active)` define el rol en cada empresa.
- El login devuelve la lista de empresas si hay más de una. `POST /api/auth/select-tenant` emite un par
  de tokens con el claim `tid`. Cambiar de empresa es pedir un token nuevo.
- Permisos por empresa: `perms` se calcula con el rol de la membresía.
- **Sucursal**:
  - `user_branch_access(membership_id, branch_id)` define a qué sucursales puede entrar el usuario.
    Si no tiene filas, puede entrar a todas, lo que equivale al rol de administración de la empresa.
  - Las operaciones de sucursal (POS, stock, caja) llevan el encabezado `X-Branch-Id`, que el API
    valida contra esos accesos.
  - El token incluye `bids` (ids de las sucursales permitidas) cuando son pocas, para validar sin
    consultar la base.
- Usuarios de plataforma (soporte, operación SaaS) usan un rol de plataforma separado, sin membresía
  implícita en las empresas.

### Precisiones de la implementación (S2.1)

- Con una sola empresa activa, el login abre la sesión directamente. Con varias, devuelve un token de
  selección de 5 minutos (`typ=selection`, que no sirve como access token) y la lista. Sin ninguna,
  responde `NO_ACTIVE_TENANT` (403).
- Cambiar de empresa es `select-tenant` con el access token vigente: exige que la sesión actual siga
  activa y la cierra.
- Un token de acceso sin `tid` recibe `TENANT_REQUIRED` (401).
- La contraseña y el nombre son globales. Por eso, el admin de una empresa no puede cambiarlos si el
  usuario también pertenece a otra (`USER_IN_OTHER_TENANTS`, 409).
- Activar y desactivar desde la administración actúan sobre la membresía. `users.is_active` queda como
  bloqueo global de la cuenta.
- Pendiente:
  - el rol de plataforma (S8.5).

### Precisiones de la implementación (S2.5)

- `user_branch_access` lleva también `tenant_id`, con FKs compuestas a la membresía y a la sucursal.
  No tiene RLS, como `memberships`: auth la lee al emitir tokens. Una sucursal con accesos no se puede
  borrar, porque el usuario pasaría a entrar a todas.
- `bids` va en el access token siempre que la membresía tenga filas, con la lista completa; sin el
  claim, el usuario entra a todas. No hay umbral de "pocas": una ferretería tiene pocas sucursales y
  el token no crece de forma apreciable. Si algún día se necesita, el umbral se agrega con un claim
  distinto para "consultar la base", nunca omitiendo `bids`, que significa todas.
- Un cambio de accesos rige desde el próximo login o refresh (como un cambio de rol) y no revoca
  sesiones: el access token anterior dura como máximo 15 minutos.
- `X-Branch-Id` se valida contra `bids` en `AuthMiddleware`, sin consultar la base; toda ruta
  autenticada rechaza uno ajeno (`BRANCH_ACCESS_DENIED`, 403). Que la sucursal exista y esté activa lo
  revisa cada operación de sucursal (`require_branch` y su comando).
- Administración: `GET`/`PUT /api/admin/users/{id}/branches` (`user:manage`); `/api/auth/me` devuelve
  las sucursales a las que el usuario puede entrar, para el selector.

### Precisiones de la implementación (S2.9)

- La web pide la empresa en un segundo paso del login solo cuando hay varias; el token de selección
  no sale de la memoria. Cambiar de empresa descarta todo lo cargado en el navegador y avisa a las
  otras pestañas.
- La web recuerda por navegador la sucursal elegida en cada empresa y la caja vinculada en cada
  sucursal, siempre validadas contra `/me` y contra las cajas activas. Envía `X-Branch-Id` en toda
  llamada de administración y del POS, y `X-Terminal-Id` en las del POS.
- Ante `BRANCH_ACCESS_DENIED` renueva el token, que trae los `bids` vigentes, y reintenta una vez.

## Consecuencias

- `require_permission` pasa a evaluar los permisos de la membresía activa.
- El frontend agrega selección de empresa (solo si hay varias) y selector de sucursal.
- Los eventos y mensajes llevan `tenant_id` tomado del contexto, nunca del cuerpo.
- Las credenciales de integración (ADR-0008) son principales de servicio con `tid` fijo.
