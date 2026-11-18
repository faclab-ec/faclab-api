# ADR-0008: API pública versionada, OAuth 2.0 *client credentials* y tokens asimétricos

- **Estado:** aceptado. Propuesto el 2026-10-14; el punto 3, la firma asimétrica, implementado en
  S6.1 (2026-11-17); el punto 2, la autenticación de integraciones, en S6.2 (2026-11-17); los puntos
  1, 4, 5 y 6 (fachada, versionado, escrituras y límites) en S6.3 (2026-11-17)
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
   - Decidido en S6.3:
     - El módulo `src/public_api/` es una capa de composición, como el POS: sus lecturas son read
       models con `tenant_criteria` y sus escrituras llaman a los comandos existentes (la venta, al
       mismo checkout del POS, `SaleCheckout`).
     - Un código de error fuera del catálogo público se traduce al genérico de su estado.
     - Cada campo de una respuesta se envía siempre y el OpenAPI lo marca requerido: quitarlo es un
       cambio incompatible que el CI detecta.
     - Una venta de la API indica su punto de emisión y su ubicación, no tiene turno ni caja y llega
       pagada en línea (sin efectivo ni crédito).
2. **Autenticación de integraciones**:
   - OAuth 2.0 *client credentials* (`POST /api/oauth/token`) con `client_id` y secreto (guardado como
     hash).
   - Scopes por recurso (`products:read`, `stock:read`, `sales:write`, `invoices:read`,
     `webhooks:manage`…) y restricción opcional por sucursal.
   - El token lleva `tid`, `azp` (cliente), `scope` y `bids`.
   - La integración es un principal de servicio de la empresa: RLS y los permisos se aplican igual.
   - Decidido en S6.2:
     - Los secretos se guardan con SHA-256, no con bcrypt ni argon2: son 256 bits aleatorios, no
       contraseñas.
     - El entorno (`fl_live_` o `fl_test_`) lo fija el despliegue y el endpoint de token rechaza
       clientes de otro.
     - Las respuestas del endpoint de token siguen RFC 6749.
     - Las rutas internas rechazan los tokens de integración (`INTEGRATION_NOT_ALLOWED`); las que los
       aceptan declaran `require_scope`.
     - El estado del cliente se cachea como máximo 60 s, así una revocación rige en ese plazo.
3. **Firma de tokens asimétrica** (decidida en S6.1: **EdDSA con Ed25519**):
   - El core publica `/.well-known/jwks.json` y facturación valida con la clave pública.
   - Se rota con `kid` y conviven dos claves durante la rotación.
   - Se eligió EdDSA porque lo soportan las dos partes sin dependencias pesadas: PyJWT con
     `cryptography` en el core y el módulo `crypto` de Node en facturación, sin bibliotecas nuevas.
     Además, sus claves y firmas son cortas y no admiten parámetros débiles. RS256 quedaba como
     alternativa si alguna parte no lo soportaba.
   - El `kid` es la huella RFC 7638 de la clave pública: no se configura y dos claves nunca
     comparten uno.
   - Los tokens llevan `aud`: refresh y selección solo `faclab-core`, y el access también los
     servicios que lo aceptan (`faclab-invoicing`). Así facturación rechaza un refresh token aunque
     su firma sea válida.
   - Facturación guarda el JWKS en memoria. Lo vuelve a pedir a los 10 minutos y, como máximo cada
     30 s, cuando llega un `kid` que no conoce; si el core no responde, sigue con las claves que ya
     tiene.
   - Procedimiento de rotación en `docs/auth-spec.md`.
4. **Versionado**:
   - Mayor en la URL (`/api/v1`). Los cambios aditivos no rompen.
   - Cada servicio guarda su OpenAPI público en `docs/public-api/openapi-v1.json` y el CI lo compara
     con el de la rama base con `oasdiff` (S6.3).
   - Un cambio incompatible crea `/api/v2`, con al menos 6 meses de convivencia y encabezados
     `Deprecation` y `Sunset`. Se acompaña con un changelog público.
5. **Escrituras**:
   - Siempre por comandos de negocio (crear venta, registrar cliente), nunca actualizaciones genéricas
     de tablas.
   - `Idempotency-Key` obligatorio en los POST que crean documentos.
6. **Límites de solicitudes**: por cliente y por empresa, más límites por IP en el proxy. D-6
   resuelta en S6.3: PostgreSQL con GCRA (un upsert por clave), detrás de un puerto para pasar a
   Redis si el volumen lo pide.

## Consecuencias

- El frontend sigue usando las rutas internas; la API pública se puede documentar y congelar.
- Facturación expone sus recursos públicos (`/api/v1/invoices`) detrás del mismo dominio vía el proxy,
  validando el mismo token por JWKS.
- Más superficie que probar: cada endpoint público entra en las pruebas de aislamiento.
