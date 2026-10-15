# ADR-0008: API pública versionada, OAuth 2.0 *client credentials* y tokens asimétricos

- **Estado:** propuesto (2026-10-14)
- **Relacionado:** [PUBLIC_API.md](../PUBLIC_API.md), [ADR-0003](0003-identidad-global-y-contexto-de-sucursal.md)

## Contexto

Las rutas `/api/admin` y `/api/pos` son el contrato interno del frontend: se despliegan juntas y
cambian con él. Los clientes quieren integrar contabilidad, ecommerce y aplicaciones propias. Hoy no
hay credenciales de máquina a máquina y facturación valida tokens con el mismo secreto HS256 con el que
se firman (G-48).

## Decisión

1. **Fachada `/api/v1`**:
   - Usa routers nuevos que llaman a los comandos y consultas existentes.
   - Los recursos públicos tienen esquemas Pydantic propios; nunca se exponen los modelos ni los
     validadores internos.
   - Tiene su propio OpenAPI (`/openapi/public.json`).
   - Las rutas internas no se versionan y pueden cambiar con el frontend.
2. **Autenticación de integraciones**:
   - OAuth 2.0 *client credentials* (`POST /api/oauth/token`) con `client_id` y secreto (guardado como
     hash).
   - Scopes por recurso (`products:read`, `stock:read`, `sales:write`, `invoices:read`,
     `webhooks:manage`…) y restricción opcional por sucursal.
   - El token lleva `tid`, `azp` (cliente), `scope` y `bids`.
   - La integración es un principal de servicio de la empresa: RLS y los permisos se aplican igual.
3. **Firma de tokens asimétrica** (EdDSA o RS256, se decide en S6.1):
   - El core publica `/.well-known/jwks.json` y facturación valida con la clave pública.
   - Se rota con `kid` y conviven dos claves durante la rotación.
4. **Versionado**:
   - Mayor en la URL (`/api/v1`). Los cambios aditivos no rompen.
   - Un cambio incompatible crea `/api/v2`, con al menos 6 meses de convivencia y encabezados
     `Deprecation` y `Sunset`. Se acompaña con un changelog público.
5. **Escrituras**:
   - Siempre por comandos de negocio (crear venta, registrar cliente), nunca actualizaciones genéricas
     de tablas.
   - `Idempotency-Key` obligatorio en los POST que crean documentos.
6. **Límites de solicitudes**: por cliente y por empresa (almacén según D-6), más límites por IP en el
   proxy.

## Consecuencias

- El frontend sigue usando las rutas internas; la API pública se puede documentar y congelar.
- Facturación expone sus recursos públicos (`/api/v1/invoices`) detrás del mismo dominio vía el proxy,
  validando el mismo token por JWKS.
- Más superficie que probar: cada endpoint público entra en las pruebas de aislamiento.
