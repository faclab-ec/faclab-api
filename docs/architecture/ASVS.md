# ASVS 5.0 nivel 2: cumplimiento de Faclab (S9.3)

> Revisión de 2026-11-27 sobre faclab-core, faclab-invoicing, faclab-web, faclab-infra y staging, con el código de
> las ramas `fix/s9-3-revision-de-seguridad`. El informe, con los hallazgos `S-xx`, las pruebas y los escaneos, está en
> [SEGURIDAD.md](SEGURIDAD.md).

Fuente: los 253 requisitos de nivel 1 y 2 del archivo JSON oficial de OWASP ASVS 5.0.0
(`OWASP_Application_Security_Verification_Standard_5.0.0_en.json`). Cada requisito se comprobó contra el código, la
configuración del stack de producción y las pruebas; la evidencia apunta al archivo o a la sección del informe.

- **Cumple**: el requisito se satisface en los cuatro repos.
- **Parcial**: se satisface en parte, o en un servicio y no en otro; la nota dice qué falta y dónde se planifica.
- **No cumple**: no se satisface; la nota nombra el hallazgo y la sesión que lo resuelve.
- **No aplica**: la funcionalidad no existe (GraphQL, WebSocket, WebRTC, OIDC, segundo factor hasta S9.5).

## Resumen

| Capítulo | Cumple | Parcial | No cumple | No aplica |
|---|---|---|---|---|
| V1. Codificación y saneamiento | 19 | 2 | 0 | 6 |
| V2. Validación y lógica de negocio | 10 | 1 | 0 | 0 |
| V3. Seguridad del frontend web | 15 | 4 | 0 | 0 |
| V4. API y servicios web | 2 | 1 | 1 | 6 |
| V5. Manejo de archivos | 8 | 0 | 0 | 1 |
| V6. Autenticación | 15 | 2 | 6 | 12 |
| V7. Gestión de sesiones | 7 | 5 | 4 | 2 |
| V8. Autorización | 5 | 2 | 0 | 0 |
| V9. Tokens autocontenidos | 7 | 0 | 0 | 0 |
| V10. OAuth y OIDC | 8 | 0 | 0 | 21 |
| V11. Criptografía | 7 | 6 | 1 | 0 |
| V12. Comunicación segura | 4 | 1 | 2 | 2 |
| V13. Configuración | 7 | 6 | 0 | 0 |
| V14. Protección de datos | 6 | 2 | 1 | 0 |
| V15. Codificación y arquitectura seguras | 9 | 4 | 0 | 0 |
| V16. Registro de seguridad y manejo de errores | 11 | 4 | 1 | 0 |
| V17. WebRTC | 0 | 0 | 0 | 7 |
| **Total (253)** | **140** | **40** | **16** | **57** |

De los 196 requisitos que aplican, 140 se cumplen, 40 en parte y 16 no. Los
incumplimientos de nivel 1 son 6.2.4 (contraseñas comunes), 6.2.8 (truncado de bcrypt) y 7.4.1 (access token vigente tras el
logout), y van en S9.4, antes del piloto; el de nivel 2 más importante, 6.3.3 (segundo factor), va en S9.5, también antes del
piloto. 11.4.3 (SHA-1 en la firma) es un riesgo aceptado: lo exige el SRI.

## V1. Codificación y saneamiento

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 1.1.1 | L2 | Decodificar la entrada una sola vez y antes de procesarla | Cumple | FastAPI/Pydantic y Fastify/zod decodifican JSON, query y formularios una vez. |
| 1.1.2 | L2 | Codificar la salida al final, para el intérprete de destino | Cumple | Respuestas JSON serializadas por el framework; React escapa al renderizar; XML con xmlbuilder2. |
| 1.2.1 | L1 | Codificación de salida según el contexto (HTML, XML) | Cumple | React; XML de comprobantes con valores escapados (invoicing `invoice-xml-builder.ts`); HTML del correo escapado (`invoice-email.ts`). |
| 1.2.2 | L1 | Codificar los datos al construir URLs | Cumple | web arma las rutas con parámetros del cliente HTTP; core no construye URLs con datos de terceros salvo los webhooks, validados (`src/webhooks/infra/urls.py`). |
| 1.2.3 | L1 | Codificar al construir JavaScript o JSON | Cumple | `config.js` de web: valores validados y escritos como literal JSON (`docker/entrypoint.sh`). |
| 1.2.4 | L1 | Consultas parametrizadas u ORM contra inyección | Parcial | SQLAlchemy y `$n` en invoicing; todo `text()` es estático o con parámetros. Dos LIKE no escapan `%` y `_` (S-34, solo comodines). |
| 1.2.5 | L1 | Sin inyección de comandos del sistema operativo | Cumple | Sin `subprocess`, `child_process` ni `eval` en el código de los servicios; xmllint corre en WebAssembly. |
| 1.2.6 | L2 | Sin inyección LDAP | No aplica | No hay LDAP. |
| 1.2.7 | L2 | Sin inyección XPath | Cumple | xml-crypto usa expresiones fijas para las referencias de la firma; ninguna viene del usuario. |
| 1.2.8 | L2 | Procesadores LaTeX seguros | No aplica | No hay LaTeX. |
| 1.2.9 | L2 | Escapar metacaracteres en expresiones regulares | Cumple | Ninguna expresión regular se arma con datos del usuario. |
| 1.3.1 | L1 | Sanear HTML de editores WYSIWYG | No aplica | No se acepta HTML de usuarios. |
| 1.3.2 | L1 | Sin eval ni ejecución dinámica de código | Cumple | Sin `eval`, `exec`, `new Function` ni `pickle` (revisión de S9.3). |
| 1.3.3 | L2 | Sanear datos antes de un contexto peligroso | Parcial | Sin contextos de ejecución con datos del usuario; los CSV y XLSX exportados no neutralizan fórmulas (S-30). |
| 1.3.4 | L2 | Validar o sanear SVG subidos | Cumple | Solo se suben logos PNG o JPEG, decodificados y validados (`logo.ts`). |
| 1.3.5 | L2 | Sanear Markdown, CSS u otras plantillas del usuario | No aplica | No se renderiza contenido de ese tipo. |
| 1.3.6 | L2 | Proteger contra SSRF con lista de protocolos y destinos | Cumple | Webhooks: HTTPS, direcciones globales comprobadas al registrar y al enviar, conexión a la IP verificada, sin redirecciones; NAT64 desde S9.3 (S-14). Pruebas manuales §5.3 del informe. |
| 1.3.7 | L2 | Sin inyección de plantillas | Cumple | PDF y correos con texto, nunca plantillas armadas con datos del usuario. |
| 1.3.8 | L2 | Sin inyección JNDI | No aplica | No hay JNDI. |
| 1.3.9 | L2 | Sanear datos enviados a memcache | No aplica | No hay memcache. |
| 1.3.10 | L2 | Cadenas de formato seguras | Cumple | Logs estructurados con campos; ningún formato viene del usuario. |
| 1.3.11 | L2 | Sin inyección SMTP o IMAP | Cumple | core usa `EmailMessage`; invoicing nodemailer, destinatario validado sin saltos de línea. |
| 1.4.1 | L2 | Memoria segura contra desbordamientos | Cumple | Python y TypeScript gestionan la memoria. |
| 1.4.2 | L2 | Prevenir desbordamientos de enteros | Cumple | Montos y cantidades en `Decimal`/`numeric(18,6)`; Pydantic y zod limitan rangos. |
| 1.4.3 | L2 | Liberar memoria y recursos | Cumple | Lenguajes con recolector; sesiones y archivos con context managers. |
| 1.5.1 | L1 | Parsers XML sin entidades externas (XXE) | Cumple | xmldom no resuelve entidades externas; ElementTree (openpyxl) tampoco y expat limita la expansión. |
| 1.5.2 | L2 | Deserialización segura de datos no confiables | Cumple | Solo JSON validado por esquemas; nada de `pickle` ni `yaml.load`. |

## V2. Validación y lógica de negocio

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 2.1.1 | L1 | Documentar las reglas de validación de entrada | Cumple | Especificaciones en `docs/*-spec.md` y esquemas OpenAPI (internos y públicos). |
| 2.1.2 | L2 | Documentar la consistencia entre datos combinados | Cumple | Reglas de cada módulo en sus especificaciones (precios, presentaciones, crédito, notas de crédito). |
| 2.1.3 | L2 | Documentar los límites de negocio por usuario y globales | Cumple | Planes y límites (S8.4), límites de crédito, de la API pública, de importación. |
| 2.2.1 | L1 | Validación positiva contra listas, patrones y rangos | Cumple | Pydantic, zod y los value objects (`TaxId`, `Email`, cantidades por unidad). |
| 2.2.2 | L1 | Validar en una capa de servicio confiable | Cumple | Toda validación se repite en core e invoicing; la de web es solo de usabilidad. |
| 2.2.3 | L2 | Combinaciones de datos razonables | Cumple | Reglas de dominio (materiales de construcción, consumidor final, presentaciones). |
| 2.3.1 | L1 | Flujos en el orden esperado, sin saltar pasos | Cumple | Máquinas de estado: ventas, turnos, ajustes, transferencias, paso a producción. |
| 2.3.2 | L2 | Límites de negocio implementados | Cumple | Stock nunca negativo, crédito, planes, pagos que no superan el saldo. |
| 2.3.3 | L2 | Transacciones a nivel de negocio | Cumple | Una transacción por request; outbox en la misma transacción. |
| 2.3.4 | L2 | Bloqueos para recursos limitados | Cumple | `FOR UPDATE` en stock, `FOR NO KEY UPDATE` en crédito y planes, numeración con upsert. |
| 2.4.1 | L2 | Controles contra automatización excesiva | Parcial | Límites por IP en Caddy, bloqueo de login, límites por cliente y empresa en la API pública; la API interna solo tiene el de IP. |

## V3. Seguridad del frontend web

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 3.2.1 | L1 | Evitar que el navegador interprete contenido en otro contexto | Cumple | `nosniff` en todas las respuestas, tipos de contenido correctos, CSP en la app. |
| 3.2.2 | L1 | Mostrar texto con funciones seguras | Cumple | React; sin `dangerouslySetInnerHTML` ni `innerHTML` en web. |
| 3.3.1 | L1 | Cookies con Secure y prefijo __Host- o __Secure- | Parcial | `faclab_refresh` es Secure, HttpOnly y SameSite=Strict, sin prefijo (S-35, S9.4). |
| 3.3.2 | L2 | SameSite según el propósito | Cumple | `SameSite=Strict` (`src/auth/infra/cookies.py`). |
| 3.3.3 | L2 | Prefijo __Host- salvo cookies compartidas | Parcial | Desviación: `__Host-` exige `Path=/` y la cookie se limita a `Path=/api/auth` para no viajar en cada request (S-35). |
| 3.3.4 | L2 | HttpOnly en cookies que el script no necesita | Cumple | La cookie de refresh es HttpOnly; el access token vive en memoria. |
| 3.4.1 | L1 | HSTS de al menos un año, con subdominios en L2 | Cumple | Caddy: `max-age=31536000; includeSubDomains` desde S9.3 (S-13); staging usa 300 s a propósito. |
| 3.4.2 | L1 | CORS con origen fijo o validado contra lista | Cumple | `CORS_ORIGINS` explícito, `*` rechazado fuera de local, en core e invoicing; prueba manual §5.6. |
| 3.4.3 | L2 | Content-Security-Policy | Parcial | CSP en la app (con `style-src 'unsafe-inline'`); las respuestas JSON del API no la llevan (S9.9). |
| 3.4.4 | L2 | X-Content-Type-Options: nosniff en todas las respuestas | Cumple | Caddy en ambos sitios y core. |
| 3.4.5 | L2 | Referrer-Policy | Cumple | Caddy `strict-origin-when-cross-origin`, core `no-referrer`. |
| 3.4.6 | L2 | frame-ancestors en cada respuesta | Parcial | La app sí; core manda `X-Frame-Options: DENY`; invoicing nada (S-29, S9.9). |
| 3.5.1 | L1 | Solicitudes entre orígenes sin depender del preflight | Cumple | El API usa tokens Bearer; la cookie de refresh es SameSite=Strict y solo va a `/api/auth`. |
| 3.5.2 | L1 | Preflight no evitable | Cumple | Las rutas sensibles exigen `Authorization`, que fuerza el preflight. |
| 3.5.3 | L1 | Operaciones sensibles con métodos no seguros | Cumple | Escrituras con POST, PUT o DELETE; los GET no cambian datos. |
| 3.5.4 | L2 | Aplicaciones separadas en nombres de host distintos | Cumple | `app.<dominio>` y `api.<dominio>` (D-9). |
| 3.5.5 | L2 | Validar el origen de postMessage | Cumple | No hay oyentes de `postMessage`; las pestañas se coordinan con BroadcastChannel del mismo origen. |
| 3.7.1 | L2 | Tecnologías de cliente soportadas | Cumple | React 19 y Vite, sin plugins. |
| 3.7.2 | L2 | Redirecciones automáticas solo a destinos permitidos | Cumple | `safeRedirectPath` solo acepta rutas internas. |

## V4. API y servicios web

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 4.1.1 | L1 | Content-Type con charset correcto | Cumple | JSON (UTF-8 por definición), PDF y XML con su tipo. |
| 4.1.2 | L2 | Solo los endpoints de usuario redirigen HTTP a HTTPS | No cumple | Caddy también redirige el API (S-36); un cliente que manda credenciales por HTTP ya las expuso. |
| 4.1.3 | L2 | Cabeceras que pone un intermediario no las puede fijar el usuario | Parcial | Caddy reemplaza `X-Forwarded-For`; `X-Request-Id` pasa del cliente (core lo valida, invoicing no: S-29). |
| 4.2.1 | L2 | Límites del mensaje HTTP según la versión (smuggling) | Cumple | Caddy termina HTTP/2 y habla HTTP/1.1 con uvicorn y Fastify, parsers estrictos. |
| 4.3.1 | L2 | Límites de consultas GraphQL | No aplica | No hay GraphQL. |
| 4.3.2 | L2 | Introspección GraphQL apagada | No aplica | No hay GraphQL. |
| 4.4.1 | L1 | WebSocket solo sobre TLS | No aplica | No hay WebSocket. |
| 4.4.2 | L2 | Origen validado en el handshake WebSocket | No aplica | No hay WebSocket. |
| 4.4.3 | L2 | Tokens dedicados para WebSocket | No aplica | No hay WebSocket. |
| 4.4.4 | L2 | Tokens WebSocket obtenidos por la sesión HTTPS | No aplica | No hay WebSocket. |

## V5. Manejo de archivos

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 5.1.1 | L2 | Documentar tipos, extensiones y tamaños de cada carga | Cumple | Importación (`docs/imports-guide.md`, límites de S9.3 en el informe), certificado .p12 (64 KB), logo (PNG/JPEG, 300 KB). |
| 5.2.1 | L1 | Solo archivos de un tamaño procesable | Cumple | Desde S9.3 (S-02, S-03, S-04): topes de bytes, líneas, columnas, iteraciones y descompresión. |
| 5.2.2 | L1 | La extensión coincide con el contenido | Cumple | Firmas `PK`/OLE en la importación, bytes mágicos del logo, el .p12 se abre con su clave. |
| 5.2.3 | L2 | Tope de tamaño descomprimido y de archivos en comprimidos | Cumple | XLSX: 64 MiB, 16 MiB de cadenas, 1000 entradas (S9.3); PNG: lo que dice la cabecera. |
| 5.3.1 | L1 | Archivos subidos nunca se ejecutan | Cumple | Se guardan en la base o en el almacenamiento de objetos; nada se sirve desde una carpeta pública. |
| 5.3.2 | L1 | Rutas de archivo con datos internos | Cumple | Exportaciones y logos con rutas armadas desde el tenant del token y nombres del servidor. |
| 5.4.1 | L2 | Nombres de archivo del usuario ignorados en las descargas | Cumple | Las descargas usan nombres del servidor (número de documento, id). |
| 5.4.2 | L2 | Nombres de archivo codificados en cabeceras | Cumple | Nombres generados por el servidor, sin datos del usuario. |
| 5.4.3 | L2 | Antivirus sobre archivos no confiables | No aplica | No se sirve de vuelta ningún archivo subido salvo el logo, que se decodifica y valida como imagen. |

## V6. Autenticación

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 6.1.1 | L1 | Documentar límites y anti automatización contra ataques de credenciales | Cumple | `docs/auth-spec.md` (bloqueo por usuario e IP) y los límites de Caddy (`deploy/production/README.md`). |
| 6.1.2 | L2 | Lista documentada de palabras del contexto prohibidas en contraseñas | No cumple | No existe (S-20, S9.4). |
| 6.1.3 | L2 | Documentar todas las vías de autenticación | Cumple | Usuarios, operadores de plataforma y clientes OAuth en `docs/auth-spec.md` y ADR-0013. |
| 6.2.1 | L1 | Contraseñas de al menos 8 caracteres | Cumple | Mínimo 8 (`PlainPassword`); se recomienda subirlo a 15 en S9.4. |
| 6.2.2 | L1 | Los usuarios pueden cambiar su contraseña | Cumple | `POST /api/auth/change-password`. |
| 6.2.3 | L1 | El cambio pide la contraseña actual y la nueva | Cumple | `change_password.py`. |
| 6.2.4 | L1 | Rechazar las 3000 contraseñas más comunes | No cumple | No se comprueba (S-20, S9.4). |
| 6.2.5 | L1 | Sin reglas de composición | Cumple | Solo longitud. |
| 6.2.6 | L1 | Campos de contraseña enmascarados | Cumple | `PasswordInput` en web. |
| 6.2.7 | L1 | Permitir pegar y gestores de contraseñas | Cumple | No se bloquea el pegado. |
| 6.2.8 | L1 | Verificar la contraseña exacta, sin truncarla | No cumple | bcrypt usa solo los primeros 72 bytes (S-20, S9.4). |
| 6.2.9 | L2 | Permitir contraseñas de 64 caracteres o más | Parcial | Se aceptan hasta 128, pero se truncan a 72 bytes (S-20). |
| 6.2.10 | L2 | Sin rotación periódica obligatoria | Cumple | No se exige. |
| 6.2.11 | L2 | Usar la lista de palabras del contexto | No cumple | No existe (S-20, S9.4). |
| 6.2.12 | L2 | Rechazar contraseñas filtradas | No cumple | No se comprueba (S-20, S9.4). |
| 6.3.1 | L1 | Controles contra relleno de credenciales y fuerza bruta | Cumple | Bloqueo por usuario (5) e IP (20) en 15 min, hash ficticio para usuarios inexistentes, 20 logins por minuto por IP en Caddy; prueba manual §5.5. |
| 6.3.2 | L1 | Sin cuentas por defecto | Cumple | El primer admin se crea con contraseña propia (`AUTH_SEED_*`, `PROVISION_ADMIN_PASSWORD`). |
| 6.3.3 | L2 | Segundo factor o combinación de factores (L2) | No cumple | No hay segundo factor (S-21, S9.5). |
| 6.3.4 | L2 | Sin vías de autenticación no documentadas | Cumple | Las tres vías están documentadas y cubiertas por pruebas de guardia. |
| 6.4.1 | L1 | Contraseñas iniciales aleatorias, que vencen pronto | Parcial | El admin fija la temporal (web la genera al azar sin sesgo desde S9.3) y se fuerza el cambio; no vence. |
| 6.4.2 | L1 | Sin pistas ni preguntas secretas | Cumple | No existen. |
| 6.4.3 | L2 | Recuperación de contraseña segura | Cumple | No hay recuperación por correo; el admin resetea y se fuerza el cambio. Un operador ya no puede ser reseteado desde una empresa (S-01). |
| 6.4.4 | L2 | Pérdida de un factor con prueba de identidad | No aplica | Sin segundo factor hasta S9.5. |
| 6.5.1 | L2 | Códigos de un solo uso usables una vez | No aplica | Sin segundo factor hasta S9.5. |
| 6.5.2 | L2 | Secretos de búsqueda con hash si tienen poca entropía | No aplica | Sin segundo factor hasta S9.5. |
| 6.5.3 | L2 | Semillas TOTP generadas con CSPRNG | No aplica | Sin segundo factor hasta S9.5. |
| 6.5.4 | L2 | Códigos con al menos 20 bits de entropía | No aplica | Sin segundo factor hasta S9.5. |
| 6.5.5 | L2 | Vida definida de códigos y TOTP | No aplica | Sin segundo factor hasta S9.5. |
| 6.6.1 | L2 | OTP por SMS solo si el riesgo lo permite | No aplica | No se usa teléfono. |
| 6.6.2 | L2 | Códigos fuera de banda ligados a su solicitud | No aplica | No hay autenticación fuera de banda. |
| 6.6.3 | L2 | Límites contra fuerza bruta de códigos | No aplica | No hay autenticación fuera de banda. |
| 6.8.1 | L2 | Identidad no suplantable entre proveedores | No aplica | Un solo proveedor de identidad: core. |
| 6.8.2 | L2 | Firma de las aserciones siempre validada | Cumple | JWT EdDSA verificados en core e invoicing (prueba manual §5.2: firma cambiada, permisos agregados y alg=none dan 401). |
| 6.8.3 | L2 | Aserciones SAML usadas una vez | No aplica | No hay SAML. |
| 6.8.4 | L2 | Fuerza de autenticación exigida a un IdP externo | No aplica | No hay IdP externo. |

## V7. Gestión de sesiones

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 7.1.1 | L2 | Documentar inactividad y vida máxima de sesión, con justificación | Parcial | Duraciones en `docs/auth-spec.md`; falta la vida absoluta y su justificación (S-19, S9.4). |
| 7.1.2 | L2 | Documentar sesiones concurrentes por cuenta | No cumple | No está documentado (S9.4). |
| 7.1.3 | L2 | Documentar sistemas de identidad federada | No aplica | No hay federación. |
| 7.2.1 | L1 | Verificar tokens en el backend | Cumple | core e invoicing verifican cada request. |
| 7.2.2 | L1 | Tokens dinámicos, no secretos estáticos | Cumple | Access tokens de 15 min y refresh rotativo. |
| 7.2.3 | L1 | Tokens de referencia únicos y aleatorios | Cumple | El refresh lleva un `jti` aleatorio ligado a `auth_sessions`. |
| 7.2.4 | L1 | Nuevo token al autenticar y fin del anterior | Cumple | Login crea sesión; cambiar de empresa revoca la sesión anterior. |
| 7.3.1 | L2 | Tiempo de inactividad que exige reautenticar | Parcial | El refresh vence a los 7 días sin uso; falta documentar la decisión (S9.4). |
| 7.3.2 | L2 | Vida máxima absoluta de la sesión | No cumple | El refresh se extiende en cada uso (S-19, S9.4). |
| 7.4.1 | L1 | Al cerrar la sesión no se puede seguir usando | No cumple | El refresh se revoca al instante, pero el access token vale hasta 15 min (S-18, S9.4). |
| 7.4.2 | L1 | Terminar sesiones al desactivar una cuenta | Parcial | Se revocan las sesiones; los access tokens emitidos viven hasta 15 min (S-18). |
| 7.4.3 | L2 | Opción de cerrar las otras sesiones al cambiar la contraseña | Cumple | Se cierran solas al cambiarla. |
| 7.4.4 | L2 | Logout visible en las páginas autenticadas | Cumple | Menú de usuario de web. |
| 7.4.5 | L2 | Los administradores pueden terminar sesiones | Parcial | Desactivar y resetear revocan; no hay acción explícita (S9.4). |
| 7.5.1 | L2 | Reautenticar antes de cambiar atributos sensibles | Parcial | El cambio de contraseña pide la actual; el paso a producción pide el RUC; el resto no (S9.4/S9.5). |
| 7.5.2 | L2 | El usuario ve y cierra sus sesiones activas | No cumple | No existe (S9.4). |
| 7.6.1 | L2 | Vida de sesión entre RP e IdP | No aplica | No hay federación. |
| 7.6.2 | L2 | Crear sesión requiere una acción del usuario | Cumple | Solo el login crea sesiones. |

## V8. Autorización

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 8.1.1 | L1 | Documentar reglas de acceso por función y por dato | Cumple | `src/auth/domain/permissions.py`, `docs/auth-spec.md`, MULTI_TENANCY.md. |
| 8.1.2 | L2 | Documentar reglas de acceso por campo | Parcial | Solo implícitas en los esquemas de respuesta por rol. |
| 8.2.1 | L1 | Acceso por función solo con permiso explícito | Cumple | Cada ruta declara su permiso o scope (pruebas de guardia en core e invoicing, la de invoicing nueva en S9.3); prueba manual §5.2. |
| 8.2.2 | L1 | Acceso por dato (IDOR) solo con permiso explícito | Cumple | Empresa por RLS forzada y filtro de aplicación, sucursal por `bids`; suite de aislamiento y probes (S-15). |
| 8.2.3 | L2 | Acceso por campo solo con permiso explícito | Parcial | Los esquemas de respuesta limitan campos; no hay reglas por rol a nivel de campo. |
| 8.3.1 | L1 | Autorización en una capa confiable | Cumple | En core e invoicing, nunca en web. |
| 8.4.1 | L2 | Controles entre empresas en aplicaciones multiempresa | Cumple | RLS forzada, claves foráneas compuestas, `tenant_criteria`, suite de aislamiento con meta-prueba (S9.3); invoicing filtra por `tid` (sin RLS: S-26). |

## V9. Tokens autocontenidos

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 9.1.1 | L1 | Validar la firma antes de leer el token | Cumple | PyJWT y `verifyAccessToken`. |
| 9.1.2 | L1 | Solo algoritmos de una lista | Cumple | Solo `EdDSA` en core e invoicing. |
| 9.1.3 | L1 | Llaves de fuentes preconfiguradas | Cumple | JWKS de la URL configurada; el `kid` debe estar publicado; sin `jku` ni `x5u`. |
| 9.2.1 | L1 | Respetar la ventana de validez | Cumple | `exp` (y `iat` en core); invoicing no mira `nbf`/`iat` (baja, S9.9). |
| 9.2.2 | L2 | Validar el tipo y propósito del token | Cumple | `typ` (`access`, `refresh`, `selection`, `platform`) por uso. |
| 9.2.3 | L2 | Solo tokens para este servicio (aud) | Cumple | core exige `faclab-core`, invoicing `faclab-invoicing`. |
| 9.2.4 | L2 | Audiencia propia por servicio con la misma llave | Cumple | Cada token lista las audiencias que puede usar. |

## V10. OAuth y OIDC

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 10.1.1 | L2 | Tokens solo a los componentes que los necesitan | Cumple | El access token va a core e invoicing; el refresh solo a `/api/auth`. |
| 10.1.2 | L2 | El cliente acepta valores del servidor de autorización solo de su flujo | No aplica | No somos cliente OAuth. |
| 10.2.1 | L2 | Cliente con code flow protegido contra CSRF | No aplica | No somos cliente OAuth. |
| 10.2.2 | L2 | Cliente contra ataques de mezcla de servidores | No aplica | No somos cliente OAuth. |
| 10.3.1 | L2 | El servidor de recursos acepta solo su audiencia | Cumple | Ver 9.2.3; los tokens de integración llevan las audiencias de core e invoicing. |
| 10.3.2 | L2 | Decisiones por los claims de autorización delegada | Cumple | Scopes acotados al cliente vigente y al plan (`require_scope`). |
| 10.3.3 | L2 | Usuario único por iss + sub | Cumple | `sub` es el id del usuario o `client:<id>`; un solo emisor. |
| 10.3.4 | L2 | Fuerza de autenticación del token | No aplica | No se exige fuerza por ruta (hasta S9.5). |
| 10.4.1 | L1 | Redirect URIs exactas y registradas | No aplica | Solo client credentials: no hay redirecciones. |
| 10.4.2 | L1 | Código de autorización de un solo uso | No aplica | Sin code flow. |
| 10.4.3 | L1 | Código de autorización de vida corta | No aplica | Sin code flow. |
| 10.4.4 | L1 | Solo los grants que el cliente necesita | Cumple | Solo `client_credentials`. |
| 10.4.5 | L1 | Contra reutilización de refresh de clientes públicos | No aplica | Los clientes de integración no tienen refresh. |
| 10.4.6 | L2 | PKCE en el code flow | No aplica | Sin code flow. |
| 10.4.7 | L2 | Registro dinámico de clientes controlado | No aplica | Solo el ADMIN crea clientes. |
| 10.4.8 | L2 | Refresh con vencimiento absoluto | No aplica | Sin refresh OAuth; el refresh propio de web no lo tiene (7.3.2, S-19). |
| 10.4.9 | L2 | Revocación de credenciales por un usuario autorizado | Cumple | El ADMIN revoca clientes y secretos (`/api/admin/integrations`). |
| 10.4.10 | L2 | Cliente confidencial autenticado en el canal de fondo | Cumple | Basic o `client_secret_post`; secreto con SHA-256 (prueba manual §5.2). |
| 10.4.11 | L2 | Solo los scopes necesarios al cliente | Cumple | El ADMIN elige los scopes y el plan los acota. |
| 10.5.1 | L2 | Contra reutilización de ID Token | No aplica | No somos cliente OIDC. |
| 10.5.2 | L2 | Usuario único por los claims del ID Token | No aplica | No somos cliente OIDC. |
| 10.5.3 | L2 | Contra suplantación del servidor de autorización | No aplica | No somos cliente OIDC. |
| 10.5.4 | L2 | Audiencia del ID Token | No aplica | No somos cliente OIDC. |
| 10.5.5 | L2 | Logout de canal de fondo | No aplica | No somos cliente OIDC. |
| 10.6.1 | L2 | Modos de respuesta del proveedor OpenID | No aplica | No somos proveedor OIDC. |
| 10.6.2 | L2 | Contra logout forzado en el proveedor OpenID | No aplica | No somos proveedor OIDC. |
| 10.7.1 | L2 | Consentimiento del usuario por solicitud | No aplica | Client credentials: no hay usuario que consienta. |
| 10.7.2 | L2 | Información clara al pedir consentimiento | No aplica | Sin consentimiento. |
| 10.7.3 | L2 | Revisar y revocar consentimientos | No aplica | Sin consentimiento. |

## V11. Criptografía

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 11.1.1 | L2 | Política documentada de gestión de llaves | Parcial | Rotación de la llave JWT (`docs/auth-spec.md`), llaves Fernet múltiples, llaves de respaldos (RESPALDOS.md); la del cifrado de certificados de invoicing no rota (S9.9). |
| 11.1.2 | L2 | Inventario criptográfico | Parcial | Disperso en la documentación; se reúne en S9.8. |
| 11.2.1 | L2 | Implementaciones validadas por la industria | Cumple | cryptography, Node crypto, bcrypt, PyJWT; node-forge solo para PKCS#12 y la firma XAdES del SRI. |
| 11.2.2 | L2 | Agilidad criptográfica | Parcial | `kid` en JWT y varias llaves Fernet; el cifrado de certificados solo tiene prefijo `v1:`. |
| 11.2.3 | L2 | Al menos 128 bits de seguridad | Parcial | Ed25519, AES-256-GCM, Fernet; los certificados de firma de las CA son RSA 2048 (112 bits), fuera de nuestro control (S-43). |
| 11.3.1 | L1 | Sin modos ECB ni relleno débil | Parcial | Sin ECB; la firma XAdES usa RSA PKCS#1 v1.5 con SHA-1 porque el SRI lo exige (S-43). |
| 11.3.2 | L1 | Solo cifrados aprobados (AES-GCM) | Cumple | AES-256-GCM (certificados), Fernet (secretos de webhooks), AES-256-CBC de pgBackRest y rclone crypt en los respaldos. |
| 11.3.3 | L2 | Cifrado autenticado | Cumple | GCM y Fernet (encrypt-then-MAC); pgBackRest verifica sumas de cada archivo. |
| 11.4.1 | L1 | Solo funciones hash aprobadas | Parcial | SHA-256 en general; SHA-1 en XAdES por exigencia del SRI (S-43). |
| 11.4.2 | L2 | Contraseñas con una función de hash costosa | Cumple | bcrypt (`password_hasher.py`). |
| 11.4.3 | L2 | Hash resistente a colisiones en firmas | No cumple | La firma XAdES-BES usa SHA-1: riesgo aceptado, lo exige el SRI (S-43). |
| 11.4.4 | L2 | Derivar llaves de contraseñas con estiramiento | Cumple | PKCS#12 de las CA (con topes desde S9.3) y la passphrase de pgBackRest. |
| 11.5.1 | L2 | Valores no adivinables con CSPRNG | Cumple | `secrets`, `crypto.randomBytes`/`randomInt` (ids XAdES desde S9.3, S-16). |
| 11.6.1 | L2 | Algoritmos aprobados para generar llaves y firmar | Cumple | Ed25519 para JWT; RSA de los certificados de las CA para XAdES. |

## V12. Comunicación segura

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 12.1.1 | L1 | Solo TLS 1.2 y 1.3 | Cumple | testssl.sh contra staging: TLS 1.2 y 1.3, nada anterior (§5.8). |
| 12.1.2 | L2 | Solo suites recomendadas, las más fuertes primero | Cumple | Secreto hacia adelante, AEAD, X25519MLKEM768 (§5.8). |
| 12.1.3 | L2 | Certificados de cliente mTLS confiables | No aplica | No hay mTLS. |
| 12.2.1 | L1 | TLS en todo servicio expuesto, sin caer a texto plano | Cumple | Caddy con HTTPS automático y redirección 308. |
| 12.2.2 | L1 | Certificados públicos confiables | Cumple | ACME (Let's Encrypt o ZeroSSL) en producción; staging usa la CA interna de Caddy. |
| 12.3.1 | L2 | TLS en toda conexión entrante y saliente, monitoreo y base incluidos | No cumple | PostgreSQL, Kafka, JWKS y OTLP viajan en claro por redes internas de Docker (S-24, S9.8; G-49). |
| 12.3.2 | L2 | Los clientes TLS validan el certificado | Parcial | Webhooks, SRI y SMTP validan; las conexiones internas no usan TLS (S-24). |
| 12.3.3 | L2 | TLS entre servicios HTTP internos | No cumple | invoicing lee el JWKS por HTTP interno; el Collector recibe OTLP sin TLS (S-24). |
| 12.3.4 | L2 | Certificados confiables entre servicios internos | No aplica | Sin TLS interno todavía (S-24). |

## V13. Configuración

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 13.1.1 | L2 | Documentar todas las comunicaciones | Cumple | ADR-0011, `deploy/production/README.md`, OBSERVABILITY.md. |
| 13.2.1 | L2 | Comunicaciones de fondo autenticadas | Parcial | PostgreSQL con roles y contraseña; Kafka sin SASL (S-24). |
| 13.2.2 | L2 | Cuentas de mínimo privilegio entre componentes | Parcial | core con cuatro roles; invoicing con un rol dueño (S-39); el Collector ve el Docker API (S-23). |
| 13.2.3 | L2 | Sin credenciales por defecto | Cumple | Secretos de producción propios (sops); los de desarrollo solo existen en local y se rechazan fuera. |
| 13.2.4 | L2 | Lista de recursos externos permitidos | Parcial | SRI y servicios fijos por configuración; webhooks a cualquier host público por diseño. |
| 13.2.5 | L2 | El servidor solo pide recursos de una lista | Parcial | Sin firewall de salida; los destinos salen de la configuración salvo los webhooks. |
| 13.3.1 | L2 | Gestión de secretos (bóveda) | Parcial | sops + age fuera del repo; en el servidor tres secretos como archivos y el resto como variables (S-23, S9.8). |
| 13.3.2 | L2 | Acceso a secretos con mínimo privilegio | Parcial | El Collector puede leer las variables de todos los contenedores (S-23). |
| 13.4.1 | L1 | Sin metadatos de control de versiones desplegados | Cumple | `.dockerignore` excluye `.git` en las cuatro imágenes. |
| 13.4.2 | L2 | Modos de depuración apagados en producción | Cumple | `DOCS_ENABLED` falso, sin `--reload`, `ENVIRONMENT=production` por defecto en la imagen de core (S-08). |
| 13.4.3 | L2 | Sin listados de directorios | Cumple | Caddy `file_server` sin `browse`. |
| 13.4.4 | L2 | Sin método TRACE | Cumple | FastAPI y Fastify solo atienden los métodos declarados. |
| 13.4.5 | L2 | Documentación interna y monitoreo no expuestos | Cumple | En el borde: `/docs`, `/openapi.json`, `/health*` dan 404; `/docs/public` es intencional (§5.8). |

## V14. Protección de datos

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 14.1.1 | L2 | Datos sensibles identificados y clasificados | Cumple | `docs/data-protection.md` y el registro de tratamientos LOPDP (S8.7). |
| 14.1.2 | L2 | Requisitos de protección por nivel | Cumple | Mismos documentos: cifrado, retención, logs. |
| 14.2.1 | L1 | Datos sensibles fuera de la URL | Parcial | Las búsquedas por RUC o cédula van en la query; desde S9.3 el borde no las guarda en su log (S-12). |
| 14.2.2 | L2 | Sin datos sensibles en cachés del servidor | Cumple | No hay cachés intermedias. |
| 14.2.3 | L2 | Datos sensibles no enviados a terceros | Cumple | Sin rastreadores; la telemetría del navegador va al Collector propio con redacción. |
| 14.2.4 | L2 | Controles de datos sensibles implementados | Cumple | Redacción de PII en logs y spans (S8.7), cifrado de certificados, exportación y baja. |
| 14.3.1 | L1 | Borrar datos del cliente al cerrar sesión | Parcial | web borra su estado en memoria; no envía `Clear-Site-Data`. |
| 14.3.2 | L2 | Cache-Control: no-store en respuestas sensibles | No cumple | Solo `/api/oauth/token` lo pone (S-22, S9.4). |
| 14.3.3 | L2 | Sin datos sensibles en el almacenamiento del navegador | Cumple | localStorage solo guarda un indicador de sesión, sucursal y terminal, y el tema. |

## V15. Codificación y arquitectura seguras

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 15.1.1 | L1 | Plazos de remediación documentados | Cumple | SEGURIDAD.md §2 (críticas 7 días, altas 30, medias 90). |
| 15.1.2 | L2 | Inventario de componentes (SBOM) | Cumple | SBOM CycloneDX de cada imagen en el CI (`security.yml`, S9.3); su firma, en S9.8. |
| 15.1.3 | L2 | Documentar la funcionalidad costosa | Parcial | CARGA.md (S9.2) y la guía de importación; falta un inventario. |
| 15.2.1 | L1 | Componentes dentro de los plazos de remediación | Cumple | Sin altas ni críticas en producción tras S9.3; las medias quedan dentro de 90 días. |
| 15.2.2 | L2 | Defensas para funcionalidad costosa | Parcial | Importación y exportación en el worker con topes (S9.3); valoración y rotación sin paginar (S9.2). |
| 15.2.3 | L2 | Producción solo con lo necesario | Parcial | La imagen de invoicing trae npm para las migraciones y la CLI; web empaqueta los mocks sin ejecutarlos (S-42). |
| 15.3.1 | L1 | Devolver solo los campos necesarios | Cumple | Esquemas de respuesta explícitos. |
| 15.3.2 | L2 | Sin seguir redirecciones en llamadas salientes | Cumple | Webhooks sin redirecciones; las demás URLs son fijas. |
| 15.3.3 | L2 | Contra asignación masiva | Cumple | Modelos Pydantic explícitos; la API pública rechaza campos desconocidos. |
| 15.3.4 | L2 | IP original transmitida por campos confiables | Parcial | Caddy reescribe `X-Forwarded-For`; core confía en cualquier origen (solo alcanzable por Caddy); invoicing no configura `trustProxy`. |
| 15.3.5 | L2 | Tipos estrictos y comparaciones estrictas | Cumple | Pydantic, ty y TypeScript estricto. |
| 15.3.6 | L2 | Sin contaminación de prototipos | Cumple | Fastify parsea JSON quitando `__proto__`; sin fusiones profundas de datos del usuario. |
| 15.3.7 | L2 | Contra contaminación de parámetros HTTP | Cumple | FastAPI y Fastify validan cada parámetro contra su esquema. |

## V16. Registro de seguridad y manejo de errores

| Id | Nivel | Requisito | Estado | Evidencia y notas |
|---|---|---|---|---|
| 16.1.1 | L2 | Inventario de logs por capa | Cumple | OBSERVABILITY.md. |
| 16.2.1 | L2 | Metadatos de cada entrada: cuándo, dónde, quién, qué | Cumple | JSON con request id, empresa, sucursal y traza; la bitácora guarda actor, acción y recurso. |
| 16.2.2 | L2 | Relojes sincronizados y marcas en UTC | Cumple | Marcas ISO 8601 en UTC. |
| 16.2.3 | L2 | Logs solo a destinos documentados | Cumple | stdout y el Collector. |
| 16.2.4 | L2 | Formato común legible por el procesador | Cumple | JSON en core, invoicing y Caddy. |
| 16.2.5 | L2 | Registrar datos sensibles según su nivel | Cumple | `redact_sensitive` y `scrubMessage` (S8.7); el log del borde ya no guarda la query (S-12). |
| 16.3.1 | L2 | Registrar toda autenticación, exitosa o no | Cumple | Logs del comando de login, `login_failures` y `faclab.auth.login.attempts`. |
| 16.3.2 | L2 | Registrar los intentos de autorización fallidos | Cumple | Los 403 se registran como WARN con su código. |
| 16.3.3 | L2 | Registrar eventos de seguridad e intentos de evasión | Parcial | Bitácora de 71 acciones en core; invoicing solo registra quién pasó a producción (S-26). |
| 16.3.4 | L2 | Registrar errores inesperados y fallas de controles | Cumple | ERROR con el tipo y el traceback; reintentos y mensajes fallidos con su evento. |
| 16.4.1 | L2 | Codificar los datos contra inyección en logs | Cumple | Logs JSON, que escapan los saltos de línea. |
| 16.4.2 | L2 | Logs protegidos de acceso y cambios | Parcial | La bitácora es append-only; los logs de Docker solo los lee root, sin protección contra cambios. |
| 16.4.3 | L2 | Logs en un sistema separado | No cumple | La telemetría de producción está apagada hasta D-1 (S-27, S8.6). |
| 16.5.1 | L2 | Mensajes genéricos ante errores inesperados | Parcial | core genérico; invoicing devuelve el texto de algunos errores del parser y de la base (S-29). |
| 16.5.2 | L2 | Operar seguro si falla un recurso externo | Cumple | Outbox, reintentos con espera, facturas pendientes con el SRI caído. |
| 16.5.3 | L2 | Fallar de forma segura, sin fail-open | Parcial | Los límites de la API pública dejan pasar si falla su almacén (decisión D-6). |

## V17. WebRTC

Faclab no usa WebRTC: los siete requisitos de nivel 1 y 2 no aplican.

