# ADR-0013 — Operadores de plataforma y consola

- **Estado:** Aceptado (S8.5, 2026-11-25)
- **Sesiones:** S8.5

## Contexto

Hasta S8.4 la plataforma (alta de empresas, planes, suscripciones) solo se operaba con comandos del
servidor (`python -m src.tenancy.provision`, `python -m src.subscriptions.cli`), como `faclab_worker`.
Toda identidad de la API era de una empresa: cada token llevaba `tid`, cada sesión pertenecía a una
empresa y el contexto de la solicitud era su empresa. Hacía falta que el equipo de Faclab diera de alta,
listara y suspendiera empresas sin la terminal, sin darle a ese equipo una forma de entrar a los datos de
una empresa como si fuera uno de sus usuarios.

## Alternativas

1. **Una marca en `users` y el mismo login.** Menos código, pero mezcla la identidad de empresa y la de
   plataforma, y obliga a que una sesión pueda no tener empresa (`auth_sessions.tenant_id` es NOT NULL).
2. **Un rol de plataforma en las membresías de una empresa especial.** Reutiliza todo, pero deja al
   operador con un token que las rutas de empresa aceptan.
3. **Tabla `platform_operators` y token propio sin empresa** (elegida).

## Decisión

- `platform_operators` (tabla de plataforma, sin RLS): quién del equipo puede entrar. La API solo la lee
  (`faclab_app` no tiene INSERT, UPDATE ni DELETE); el equipo se administra con
  `python -m src.platform_console.cli` (`make platform`), como `faclab_worker`.
- El operador es un usuario global existente y entra con su contraseña en `POST /api/platform/auth/login`
  (mismo bloqueo por intentos que el login de empresa; quien no es operador falla igual que con una
  contraseña equivocada). El token es `typ=platform`, sin `tid`, `role`, `perms` ni `sid`, con
  `aud=faclab-core` solamente (faclab-invoicing lo rechaza), de `PLATFORM_TOKEN_TTL_SECONDS` (900) y sin
  refresh: al vencer se vuelve a ingresar.
- `AuthMiddleware` lo reconoce y deja la solicitud **sin** `TenantContext`. En las rutas de una empresa
  (`/api/admin`, `/api/pos`, `/api/v1`) un token de plataforma responde 403 `PLATFORM_NOT_ALLOWED`; en
  `/api/platform` uno de empresa responde 403 `PERMISSION_DENIED`.
- Cada operación de `/api/platform` pasa por `PlatformConsole.run`: comprueba que el operador siga activo
  (una baja rige de inmediato, no al vencer el token) y abre **una transacción como `faclab_worker`**
  (BYPASSRLS), dentro del contexto de la empresa cuando actúa sobre una (`TenantSource.TASK`, con el
  operador como actor). Es el único uso de `worker_session_maker` dentro de una solicitud, acotado a
  `/api/platform`.
- Auditoría: lo que el operador hace **sobre una empresa** (`tenant.provisioned`, `tenant.suspended`,
  `tenant.activated`, `subscription.changed`) queda en el `audit_log` de esa empresa, con el operador como
  actor y origen `task`. Lo que no tiene empresa (altas y bajas de operadores) queda en el log
  estructurado con `by`.
- Suspender una empresa (`tenants.status = suspended`) impide el login y el refresh y revoca sus sesiones;
  los access tokens ya emitidos duran hasta vencer (15 minutos). Es distinto del estado de la
  suscripción (solo lectura, S8.4), que la consola cambia aparte.

## Consecuencias

- La consola no puede actuar como un usuario de la empresa ni llamar a faclab-invoicing por ella: lo que
  pasa en facturación (perfil fiscal, certificado, factura de prueba, paso a producción) lo hace el
  administrador de la empresa con su propio token. La consola ve la facturación con lo que core ya sabe
  (ventas por estado de factura, diferencias, comprobantes del mes).
- Un operador con la contraseña robada puede ver y suspender todas las empresas: el token es corto y sin
  refresh, la contraseña tiene bloqueo por intentos y la tabla se edita solo desde el servidor. Falta una
  segunda verificación (pendiente).
- `PLATFORM_CONSOLE_ENABLED=false` apaga la consola entera (503 `PLATFORM_CONSOLE_DISABLED`).
