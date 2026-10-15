# ADR-0003: Identidad global con membresías, token por empresa y sucursal validada

- **Estado:** propuesto (2026-10-14)
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

## Consecuencias

- `require_permission` pasa a evaluar los permisos de la membresía activa.
- El frontend agrega selección de empresa (solo si hay varias) y selector de sucursal.
- Los eventos y mensajes llevan `tenant_id` tomado del contexto, nunca del cuerpo.
- Las credenciales de integración (ADR-0008) son principales de servicio con `tid` fijo.
