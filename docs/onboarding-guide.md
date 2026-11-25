# Guía de alta de empresas (para operadores de la plataforma)

Cómo dar de alta una ferretería y dejarla facturando en el ambiente de pruebas del SRI, y cómo pasarla a
producción. Sesión S8.5; decisiones en [ADR-0013](architecture/ADR/0013-operadores-de-plataforma-y-consola.md).

## 1. Quién es operador

El equipo de Faclab entra a la consola de plataforma (`/platform` en la web) con un usuario que tiene
una fila en `platform_operators`. Se agrega con la CLI, en el servidor, nunca por HTTP:

```bash
make platform args="operator-add --username ana --by <quien lo hace>"
make platform args="operators"
make platform args="operator-remove --username ana --by <quien lo hace>"
```

El usuario debe existir (cualquier usuario de la plataforma). Entra con su contraseña de siempre; el
token dura 15 minutos y no se renueva: al vencer, se ingresa de nuevo. Quitar a un operador rige de
inmediato.

## 2. Alta de la empresa (consola)

1. **Empresas → Nueva empresa**: RUC (13 dígitos), razón social, el usuario y correo del administrador,
   y opcionalmente la dirección de la matriz, el plan y los días de prueba.
2. La plataforma crea la empresa, a su administrador, la sucursal matriz `001` con su punto de emisión
   `001`, la bodega `BOD-001`, la ubicación `GENERAL`, la caja `CAJA-01` y la suscripción.
3. La **contraseña temporal** del administrador se muestra una sola vez: entrégala por un canal seguro.
   Debe cambiarla al ingresar. Si el usuario ya existía, ingresa con la contraseña de siempre.

El alta es idempotente por RUC: repetirla completa lo que haya quedado a medias.

## 3. Lo que hace el administrador de la empresa

Con su usuario entra a **Configuración → Puesta en marcha** y sigue los pasos:

| Paso | Qué es | Obligatorio |
|---|---|---|
| Perfil fiscal | RUC, razón social, dirección de la matriz, régimen | Sí |
| Certificado de firma | El `.p12` de la empresa (del mismo RUC) | Sí |
| Sucursales y puntos de emisión | Cada establecimiento del SRI | Sí (la matriz ya viene) |
| Cajas del punto de venta | Terminales por sucursal | Sí (`CAJA-01` ya viene) |
| Usuarios | Cajeros, gerentes | No |
| Importación inicial | Productos, clientes, proveedores, saldos | No |
| Secuenciales iniciales | Solo si viene de otro sistema | No |
| Verificación en pruebas | Facturación lista y una factura de prueba autorizada por el SRI | Sí |
| Paso a producción | Cambia al ambiente real del SRI | Sí, al final |

Cada paso se marca solo cuando está hecho: el asistente no guarda nada aparte, así que se puede dejar y
retomar, y lo hecho en otras pantallas cuenta. **El asistente nunca muestra contraseñas**: la del
certificado solo se escribe al subirlo.

### La factura de prueba

Con el perfil y el certificado listos, **Emitir factura de prueba** envía una factura de 1 centavo al
consumidor final por todo el flujo (firma, recepción, autorización) contra el ambiente de pruebas del SRI.
No es una venta de core ni se le avisa a core; usa el primer punto de emisión (`001-001`). Si el SRI la
rechaza se muestra el motivo.

### El paso a producción

Solo se activa con una factura de prueba autorizada. Pide **escribir el RUC de la empresa** y aceptar;
queda registrado con quién lo hizo (tabla `issuer_audit` de faclab-invoicing, que no se puede editar ni
borrar). Al pasar: la factura de prueba se olvida y los números que usó **vuelven al contador** (si
siguen siendo los últimos), de modo que la primera factura real toma el número que el asistente dejó
fijado. No hay forma de volver al ambiente de pruebas. Un servidor con `NODE_ENV` distinto de
`production` (local) rechaza el paso con `ENVIRONMENT_NOT_ALLOWED`.

## 4. Suspender, reactivar y cambiar el plan (consola)

- **Suspender**: nadie de la empresa puede ingresar ni renovar la sesión, y sus sesiones se cierran
  (los access tokens ya emitidos duran hasta 15 minutos). Pide confirmación y un motivo opcional.
  Queda en la bitácora de la empresa.
- **Reactivar**: la empresa vuelve a poder ingresar.
- **Plan y estado de la suscripción**: cambia el plan y el estado (`trial`, `active`, `suspended`,
  `cancelled`; los dos últimos y una prueba vencida dejan la empresa en solo lectura, S8.4).
- El detalle de la empresa muestra su uso contra los límites del plan y su facturación según core:
  facturas autorizadas, pendientes y rechazadas, ventas sin factura, diferencias abiertas y comprobantes
  del mes. El certificado y el perfil fiscal los ve el administrador de la empresa.

## 5. Si algo falla

- `PLATFORM_CONSOLE_ENABLED=false` oculta toda la consola (503); no afecta a ninguna empresa.
- La contraseña de un operador es la de su usuario global: se restablece como la de cualquier usuario
  ([auth-spec.md](auth-spec.md)).
- Pasar a producción por error no se deshace desde la consola: hay que corregirlo en la base de
  faclab-invoicing (`issuers.environment`) y anotarlo.
