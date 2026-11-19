# Sandbox para integradores

El sandbox es un despliegue aparte de Faclab (core, facturación y la aplicación web), con su propia
base de datos, donde cada integrador recibe una empresa de prueba con datos ficticios. Las
credenciales de integración que se crean allí son `fl_test_` y solo valen en ese despliegue; las de
producción (`fl_live_`) no sirven allí, ni al revés. Así el sandbox no comparte datos con
producción (S6.5, PUBLIC_API.md §10). El subdominio, `sandbox.<dominio>`, queda para D-9 y su
despliegue para S8.1.

## Configuración del despliegue

| Variable | Valor | Por qué |
|---|---|---|
| `INTEGRATION_ENVIRONMENT` | `sandbox` | Clientes `fl_test_`. `make sandbox` se niega con otro valor |
| `ENVIRONMENT` | `staging` (o `local`) | `make sandbox` se niega con `production` |
| `KAFKA_ENABLED` | `true` | Las ventas van a facturar al ambiente de pruebas del SRI |
| `PUBLIC_DOCS_ENABLED` | `true` | La documentación pública en `/docs/public` |
| `WEBHOOK_ALLOW_PRIVATE_URLS` | `false` | Como en producción: solo URLs https públicas |

faclab-invoicing solo llega al SRI de producción con `NODE_ENV=production`; con otro valor solo
llega a celcer (el ambiente de pruebas). El del sandbox no debe tener ese permiso, así ninguna
empresa del sandbox factura en el SRI real aunque su perfil fiscal diga ambiente 2. Hoy no hay un
interruptor propio para eso en facturación: definirlo es parte del despliegue del sandbox (S8.1).

## Crear la empresa de un integrador

```bash
PROVISION_ADMIN_PASSWORD=... make sandbox args="--ruc 0999999980001 \
  --legal-name 'Tienda Demo (sandbox)' --admin-username tienda-demo \
  --admin-email dev@tienda.example"
```

- Crea la empresa y su administrador (el mismo aprovisionamiento que `make provision-tenant`) y le
  carga el catálogo del seed local: tres sucursales con punto de emisión, bodega y caja, unos 35
  productos con presentaciones y stock, listas de precios, clientes, proveedores y algunas ventas.
  Las identificaciones son inventadas, con dígito verificador válido.
- El RUC es único en la plataforma: usa uno distinto por integrador. Si el integrador va a facturar
  en pruebas, pon el RUC del certificado con el que lo hará (ver abajo).
- Entrégale al integrador el usuario administrador: con él crea sus clientes de integración en
  **Configuración → Integraciones** y sus webhooks, como dice la guía **Primeros pasos**.
- `--client-name "Nombre"` crea además un cliente con todos los scopes y muestra su secreto una sola
  vez. Con `--credentials-file ruta`, el secreto se escribe en ese archivo (0600) y no se muestra.
- Es idempotente: una empresa que ya tiene productos no se toca. `--reset` reemplaza sus datos de
  negocio por los del seed. No borra sus clientes de integración, sus webhooks, la bitácora ni los
  usuarios. Si el integrador generó documentos que el seed no conoce (turnos, devoluciones,
  cotizaciones), el reset falla sin cambiar nada: en ese caso, crea otra empresa.

## Facturar en el ambiente de pruebas del SRI

El script del core no configura facturación. Para que las facturas de una empresa del sandbox se
autoricen en celcer, en faclab-invoicing del sandbox y con el administrador de esa empresa:

1. Perfil fiscal (`PUT /api/company-config` o **Configuración → Perfil fiscal**) con ambiente 1
   (pruebas).
2. El certificado `.p12` del RUC de la empresa (`POST /api/certificates` o **Certificados
   Digitales**) y elegirlo en el perfil.
3. `GET /api/invoicing/status` debe decir que está listo.

El SRI de pruebas valida el RUC y el certificado: hace falta un certificado real de ese RUC,
normalmente el del cliente final del integrador. Sin esto, las ventas quedan con la factura
pendiente y el resto de la API funciona igual. Automatizar estos pasos en facturación queda
pendiente (S6.5).

## Los ejemplos en el CI

El job `examples` del CI del core no usa el sandbox desplegado: levanta PostgreSQL, la API y el
worker en el mismo job (sin Kafka, con `WEBHOOK_ALLOW_PRIVATE_URLS=true` porque los receptores
corren en el runner), crea una empresa con `python -m scripts.sandbox ... --credentials-file` y
corre `docs/public-api/examples/run-all.sh`. Las descargas de facturas no corren allí. Correr los
mismos ejemplos contra el sandbox desplegado (programado, con credenciales en secretos del
repositorio y `FACLAB_SKIP_WEBHOOKS=1`) queda para S8.1.
