# Revisión de seguridad y aislamiento (S9.3)

> 2026-11-27 · faclab-core, faclab-invoicing, faclab-web, faclab-infra y staging · ramas
> `fix/s9-3-revision-de-seguridad` · ASVS 5.0 nivel 2 requisito por requisito en [ASVS.md](ASVS.md)

## 1. Resumen

La revisión antes del piloto encontró **7 hallazgos altos y ninguno crítico**. Los siete quedaron corregidos en las ramas de
la sesión, igual que 10 de los medios y bajos baratos de cerrar. El resto quedó planificado en sesiones nuevas:

- **S9.4 (sesiones y contraseñas) y S9.5 (segundo factor)**, antes del piloto;
- **S9.8 (cadena de suministro y secretos) y S9.9 (endurecimiento de facturación)**, después.

| Severidad | Encontrados | Corregidos en S9.3 | Planificados | Aceptados |
|---|---|---|---|---|
| Crítica | 0 | — | — | — |
| Alta | 7 | 7 | 0 | 0 |
| Media | 17 | 6 | 11 | 0 |
| Baja | 19 | 4 | 13 | 2 |
| Informativa | 2 | — | — | 2 |

Lo más grave:

- **S-01:** el ADMIN de una empresa podía tomar la cuenta de un operador de plataforma y entrar a la consola, que ve todas las
  empresas.
- **S-02, S-03 y S-04:** una empresa, con su propio ADMIN, podía dejar sin servicio a todas con un archivo pequeño:
  - un XLSX de 4 KB ocupaba unos diez minutos de CPU del API;
  - un `.p12` con iteraciones sin tope bloqueaba invoicing;
  - un PNG de 299 KB se descomprimía a 300 MiB.
- **S-05, S-06 y S-07:** dependencias, imágenes y GitHub Actions con avisos críticos y altos, o sin fijar.

El aislamiento entre empresas no falló en ninguna prueba: ni en las automáticas (la suite de PostgreSQL con 20 probes nuevos y
una meta-prueba que exige probar cada campo de id), ni en las manuales.

Quedan en el CI de los cuatro repos:

- escaneo de dependencias y de imágenes con Trivy, que bloquea con altas y críticas que tengan arreglo, y SBOM de cada imagen;
- actions fijadas por SHA;
- Dependabot, escaneo de secretos con bloqueo en push y CodeQL, activados en GitHub.

En ASVS nivel 2, de los 196 requisitos que aplican: 140 se cumplen, 40 en parte y 16 no. Los tres incumplimientos de nivel 1
van en S9.4.

## 2. Método, alcance y criterio

**Alcance.**
- El código de las cuatro ramas.
- El stack de producción tal como lo describe faclab-infra (`deploy/production`).
- El borde de la VM de staging (`faclab-staging`, encendida para esto y apagada al final).
- **Fuera:** el SRI y producción, contra los que no se probó nada.

**Cómo se revisó.**
1. Lectura del código de cada superficie: autenticación, autorización, aislamiento, cargas, salidas a terceros, cabeceras,
   errores, logs, Dockerfiles, compose, Caddy y workflows.
2. Lista ASVS 5.0 completa: los 253 requisitos de nivel 1 y 2 del JSON oficial de OWASP.
3. Escaneo de dependencias e imágenes antes y después de corregir.
4. Pruebas automatizadas nuevas en las suites de cada repo, y pruebas manuales contra un core local con dos empresas y contra
   el borde de staging.
5. Cada hallazgo alto se reprodujo antes de corregirlo y se volvió a probar después.

**Herramientas.**

| Herramienta | Versión | Uso |
|---|---|---|
| Trivy | 0.76.2, imagen fijada por digest `sha256:8f6bb947…`, la misma en Docker Hub y GHCR | Dependencias e imágenes |
| OSV.dev | API | Severidad de los avisos de Python |
| npm audit | — | Dependencias de invoicing y web |
| CodeQL | Configuración por defecto de GitHub | Análisis estático |
| testssl.sh | 3.2 | TLS del borde |
| nmap | 7.98 | Puertos expuestos |

Sobre Trivy: no se usa `aquasecurity/trivy-action`, cuyos tags fueron reemplazados por versiones que robaban secretos del CI
en marzo de 2026 (CVE-2026-33634, GHSA-69fq-xp46-6x23). Aqua no publica firmas cosign ni atestaciones para la imagen; la
confianza viene del digest y de su release inmutable en GitHub.

**Severidad.**
- **Crítica:** sin autenticarse, alguien lee o cambia datos de otra empresa o toma la plataforma.
- **Alta:** se cumple alguna de estas condiciones:
  - una empresa, aunque sea su ADMIN, alcanza datos de otra, la disponibilidad de todas o la consola de plataforma;
  - una dependencia de ejecución expuesta a entradas de terceros tiene un aviso alto o crítico con arreglo;
  - la cadena de publicación puede inyectar código en las imágenes o en el servidor.
- **Media:** exige condiciones adicionales o tiene impacto acotado. También caen aquí:
  - los incumplimientos de ASVS L1 y L2 sin explotación directa;
  - los avisos de componentes que solo hablan por la red interna (Kafka, socket proxy).
- **Baja:** endurecimiento.
- **Informativa:** riesgo aceptado o tarea del dueño de la cuenta.

**Plazos de remediación (ASVS 15.1.1).** Corren desde que el escaneo semanal o un PR lo detectan:

| Severidad | Plazo |
|---|---|
| Crítica | 7 días |
| Alta | 30 días |
| Media | 90 días |
| Baja | Próximo ciclo de dependencias |

Una excepción en `.trivyignore.yaml` necesita un motivo y una fecha de vencimiento (`expired_at`); al vencer, el job vuelve a
fallar.

## 3. Hallazgos

### 3.1 Corregidos en S9.3

**Altos**

| Id | Repo | Hallazgo | Corrección (commit) |
|---|---|---|---|
| S-01 | core | El ADMIN de la única empresa de un operador de plataforma podía resetearle la contraseña o renombrarlo (`USER_IN_OTHER_TENANTS` solo miraba otras membresías) y entrar a `/api/platform`, que corre como faclab_worker (BYPASSRLS) sobre todas las empresas. El login de plataforma tampoco miraba `must_change_password`. | Reset y rename responden 409 `USER_IS_PLATFORM_OPERATOR` por el puerto `PlatformOperators` (`src/shared/app/platform.py`); el login de plataforma rechaza una contraseña temporal (403 `PASSWORD_CHANGE_REQUIRED`). `5d85173` |
| S-02 | core | Un XLSX de 4 KB con `<dimension ref="A1:XFD1048576">` y una fila lejana hacía que openpyxl rellenara cada hueco con 16.384 celdas vacías: medido 0,69 s por 20.000 × 1.000 celdas, unos 10 minutos por subida en el caso extremo, con el GIL tomado. Una fila de millones de celdas agotaba la memoria del API (768 MiB). | Tope de tamaño descomprimido (64 MiB, 16 MiB de cadenas, 1000 entradas), recorrido previo de la hoja en streaming (filas, celdas por fila y elementos fuera de las filas), `reset_dimensions()` con `max_col`, y líneas vacías contadas en CSV y XLSX. Cuesta ~1,6 s extra en un XLSX legítimo de 50.000 filas. `f1f7b44` |
| S-03 | invoicing | node-forge toma de cada `.p12` el número de iteraciones de sus derivaciones y las corre en JavaScript, en el único hilo: un certificado con miles de millones bloqueaba el servicio de todas las empresas al subirlo, en cada readiness y en cada firma. | Las derivaciones corren con tope por llave (200.000) y por archivo (600.000, ~1 s; cada iteración cuesta ~1,6 µs); la subida acepta hasta 64 KB. `ed15298` |
| S-04 | invoicing | `inflateSync` del logo sin `maxOutputLength`: un PNG de 299 KB (bajo el límite de 300 KB) se descomprimía a 300 MiB, más que la memoria del API en producción (384 MiB). | zlib para en lo que dice la cabecera de la imagen. `0ca54e8` |
| S-05 | core, invoicing, web | Dependencias de ejecución con avisos críticos o altos (§4.2). | Subidas de versión. `481a2f0`, `bafb2de`, `3944668`, y vitest 5 en `d21f474` |
| S-06 | los cuatro | Ninguna GitHub Action estaba fijada por SHA, ni las imágenes de los workflows por digest, y los workflows de release (`packages: write`) y deploy (la llave SSH que termina en `sudo`) las usaban. | Cada `uses:` fijado por SHA con su versión en un comentario; `oasdiff` y `actionlint` por digest; Dependabot mueve las actions una vez al mes. `c5953c7` y los commits `ci:` de cada repo |
| S-07 | core, invoicing, infra | Imágenes con paquetes o binarios con avisos altos que ya tenían arreglo: libpam (CVE-2025-6020) en core e invoicing, el npm de la imagen base de Node, Kerberos, zlib y zstd en faclab-postgres, `golang.org/x/net` 0.60 en faclab-caddy. | `apt-get upgrade` en los stages de ejecución, npm 11 en invoicing y faclab-caddy compilado con x/net 0.62. `5503020`, `6ba7ea4`, `02f6eb7` |

**Medios**

| Id | Repo | Hallazgo | Corrección |
|---|---|---|---|
| S-08 | core | Sin `ENVIRONMENT`, la imagen caía en la configuración local (llaves de desarrollo, docs abiertas). El compose de producción ya lo exigía con `:?`. | `ENV ENVIRONMENT=production` en la imagen; el job `image-scan` comprueba que se niega a arrancar sin configuración. `5503020` |
| S-09 | infra | `/api/platform/auth/login` estaba fuera de la zona `login_ip` de Caddy (20 por minuto). | Agregado a la zona. `a14abdb` |
| S-10 | GitHub | Los tags `v*` no estaban protegidos, y la llave de despliegue ejecuta como root lo que apunte el tag. | Dos rulesets en cada repo, «Tags de versión inmutables» y «solo los crean los admins»: nadie mueve ni borra un `v*`. Para borrar los `rc` viejos hay que desactivar un momento el primero. |
| S-11 | GitHub | Repos públicos sin escaneo de secretos, alertas de Dependabot ni CodeQL. | Activados (§6). |
| S-12 | infra | El access log del borde guardaba la URI completa: `?taxId=` con un RUC o una cédula, `?search=` con nombres (LOPDP). | Filtro de log: queda la ruta y `?[redacted]` (comprobado con un request real). `0e448bc` |
| S-13 | infra | HSTS sin `includeSubDomains` (ASVS 3.4.1, L2). | Agregado; solo alcanza a los nombres bajo `app.` y `api.`. `5f77ff1` |

**Bajos**

| Id | Repo | Hallazgo | Corrección |
|---|---|---|---|
| S-14 | core | El guard SSRF no desenvolvía NAT64 (`64:ff9b::/96`) ni rechazaba `::/96` y `64:ff9b:1::/48`, que Python cuenta como globales. | `cab0644` |
| S-15 | core | 19 campos de id que las rutas aceptan nunca se probaban con el valor de otra empresa. Ninguno filtró al probarlo. | `PROBES` y una meta-prueba sin base de datos que falla si un campo `*Id` queda sin probar. `e2ec967` |
| S-16 | core, invoicing, web | CodeQL encontró: `Math.random()` en los ids de la firma XAdES, sesgo por módulo en las contraseñas temporales de web, y TLS 1.0 permitido en el receptor de pruebas de webhooks. | `ea287e9`, `f4b7cb8`, `cfccd05` |
| S-17 | invoicing | vitest 1.6 (solo desarrollo) traía tinypool (crítico) y vite (alto). | vitest 5 con vite 8. `d21f474` |

### 3.2 Planificados

| Id | Severidad | Repo | Hallazgo | Sesión |
|---|---|---|---|---|
| S-18 | Media | core, invoicing | El access token sigue valiendo hasta 15 min después del logout, de una baja o de un cambio de rol o de sucursales (ASVS 7.4.1, L1; 7.4.2). | S9.4 |
| S-19 | Media | core | La sesión no tiene vida máxima absoluta: el refresh se extiende en cada uso (7.3.2, 10.4.8). | S9.4 |
| S-20 | Media | core | Sin lista de contraseñas comunes ni filtradas (6.2.4, L1; 6.2.12); bcrypt trunca a 72 bytes (6.2.8, L1). | S9.4 |
| S-21 | Media | core, web | Sin segundo factor para ADMIN ni para los operadores de plataforma (6.3.3). | S9.5 |
| S-22 | Media | core, invoicing | Las respuestas con tokens o datos personales no llevan `Cache-Control: no-store` (14.3.2). | S9.4 |
| S-23 | Media | infra | El Collector puede leer el `Env` de todos los contenedores por el socket proxy, y casi todos los secretos viajan como variables (13.3). | S9.8 |
| S-24 | Media | infra, invoicing | Tráfico interno sin TLS: PostgreSQL, Kafka (sin SASL), el JWKS por HTTP y OTLP (12.3; G-49). Kafka es además la frontera de empresa de invoicing (`tenant_id` del mensaje). | S9.8 |
| S-25 | Media | los cuatro | Imágenes sin firma ni verificación al desplegar, bases fijadas por tag, Python sin lock con hashes. | S9.8 |
| S-26 | Media | invoicing | Sin RLS (solo filtro de aplicación) y sin bitácora de las acciones de administración (certificado, perfil, secuenciales, logo). | S9.9 |
| S-27 | Media | infra | Los logs de producción no salen a un sistema separado: la telemetría está apagada hasta D-1 (16.4.3). | S8.6 |
| S-28 | Media | infra | Imágenes de terceros con avisos altos, solo en la red interna: socket proxy v0.5.0 (9 de Alpine) y Kafka (174 en 7.9.0; S9.3 lo sube a 7.9.11, que deja 5 en sus herramientas de Python). | S9.8 |
| S-29 | Baja | invoicing | Sin cabeceras de seguridad propias; `/docs` registrado (el borde no lo expone); errores de Fastify como 500; `X-Request-ID` sin validar; algunos logs con `{ error }` que escapan al saneo. | S9.9 |
| S-35 | Baja | core | Cookie de refresh sin prefijo `__Secure-` (3.3.1). | S9.4 |
| S-39 | Baja | invoicing | Un solo rol de base, dueño, para migraciones y ejecución. | S9.9 |
| S-40 | Baja | infra | Los dumps previos a cada despliegue quedan sin cifrar en el host (root, 0600). | S9.8 |
| S-41 | Baja | infra | Las tareas del compose no tienen `no-new-privileges`; el socket proxy no tiene `cap_drop`. | S9.8 |
| S-45 | Baja | core, invoicing | Sin token se responde 403 y no 401. | S9.4 |
| S-30 | Baja | core | Los CSV y XLSX exportados (reporte de errores de importación, exportación de datos) no neutralizan celdas que empiezan con `= + - @` (ASVS 1.2.10, L3). | Pendiente |
| S-31 | Baja | core | Un `X-Branch-Id` de otra empresa se acepta en rutas sin sucursal y queda en `audit_log.branch_id` e `import_jobs.branch_id`, sin clave foránea. Integridad de la bitácora, no fuga: las rutas de sucursal responden 404. | Pendiente |
| S-32 | Baja | core | El alta de usuarios dice si un username o un email ya existe en otra empresa (identidad global). | Pendiente |
| S-33 | Baja | core | Webhooks: se acepta cualquier puerto, y el error de entrega es visible para el cliente; un oráculo de puertos limitado a hosts públicos. | Pendiente |
| S-34 | Baja | core | Dos LIKE no escapan `%` ni `_`: solo comodines. | Pendiente |
| S-36 | Baja | infra | El borde redirige el API de HTTP a HTTPS en lugar de rechazarlo (4.1.2). | Pendiente |
| S-42 | Baja | web | `miragejs` figura en `dependencies` y el mock se importa en el bundle, aunque solo corre fuera de producción. | Pendiente |

### 3.3 Aceptados

| Id | Severidad | Hallazgo | Por qué |
|---|---|---|---|
| S-37 | Baja | La imagen de web trae Caddy 2.11.9 con `golang.org/x/net` 0.60 (GO-2026-6860, el parser de HTML). | El Caddyfile del contenedor solo sirve archivos: nada parsea HTML. Excepción en `.trivyignore.yaml` hasta el 2027-01-31 o hasta que Caddy publique una versión con x/net 0.62. |
| S-38 | Baja | El `gosu` de la imagen oficial de PostgreSQL (1.20, Go 1.24.6) arrastra avisos de la biblioteca estándar de Go. | Solo baja de root al usuario postgres al arrancar: no abre red ni lee nada de un cliente. El job lo salta (`--skip-files`) y el resumen lo sigue listando. |
| S-43 | Info | La firma XAdES-BES usa RSA-SHA1 y PKCS#1 v1.5, y los certificados de las CA son RSA 2048. | Lo exige la ficha técnica del SRI. Alerta de CodeQL descartada con esa razón. |
| S-44 | Info | La organización de GitHub no exige segundo factor. | Lo activa su dueño (`Settings → Authentication security`). |

## 4. Escaneos

### 4.1 En el CI

Un workflow `security.yml` en cada repo:

- **Cuándo corre:** en cada PR, en cada push a `master`, cada lunes y a mano.
- **Permisos:** `contents: read`, sin secretos.
- **Trivy:** fijado por digest, lee las imágenes desde un archivo, nunca desde el socket de Docker.
- **SBOM:** CycloneDX de cada imagen como artefacto, 90 días.

| Repo | Job | Qué revisa | Bloquea |
|---|---|---|---|
| core | `dependencies` | Las dependencias de ejecución tal como resuelve `requirements.txt` hoy, transitivas incluidas (entorno propio, sin pip) | Altas y críticas con arreglo |
| core | `image-scan` | La imagen de producción: paquetes de Debian y de Python. También comprueba que se niega a arrancar sin configuración. Cubre el pendiente de S8.2 «un job `image` en el CI del core». | Ídem |
| invoicing, web | `dependencies` | Las dependencias de producción de `package-lock.json`; el resumen incluye las de desarrollo | Ídem |
| invoicing, web | `image-scan` | La imagen de producción | Ídem |
| infra | `image-scan (caddy)`, `image-scan (postgres)` | faclab-caddy y faclab-postgres, sin el `gosu` de esta última (S-38) | Ídem |
| infra | `third-party-images` | Las imágenes de terceros del compose de producción | Nunca: su arreglo es subir de versión |

Después del merge pasan a checks requeridos de `master`. Dependabot lleva:

- `github-actions` una vez al mes, para mantener al día los SHA;
- `pip`/`npm` solo para actualizaciones de seguridad, que se activan después del merge para que no abran PR duplicados de
  estas subidas.

### 4.2 Antes y después

Altas y críticas con arreglo disponible:

| Qué | Antes (`master`) | Después (ramas de S9.3) |
|---|---|---|
| core: dependencias de ejecución | PyJWT 2.9.0 (1 crítica, 6 altas), python-multipart 0.0.20 (3 altas) | 0 (quedan 2 medias de opentelemetry-api 1.32) |
| core: imagen | libpam (4 paquetes, CVE-2025-6020) | 0 |
| invoicing: producción (npm audit) | 2 críticas, 19 altas, 35 medias | 0 críticas, 0 altas, 8 medias |
| invoicing: árbol completo | 4 críticas, 21 altas | 0 críticas, 0 altas, 8 medias |
| invoicing: imagen | libpam y el npm de la base (10 altas) | 0 |
| web: producción (npm audit) | 2 altas (zod, follow-redirects), 4 medias | 0 altas, 3 medias (cambios mayores: react-router 7, i18next 27) |
| web: imagen | x/net en el binario de Caddy | 0 (excepción S-37) |
| infra: faclab-caddy | x/net 0.60 | 0 |
| infra: faclab-postgres | 60 altas de Debian con arreglo; `gosu`: 1 crítica y 26 altas de Go | 0 (`gosu` aceptado, S-38) |
| Kafka (`confluentinc/cp-kafka`) | 7.9.0: 5 críticas, 169 altas | 7.9.11: 5 altas en herramientas de Python (S-28) |
| garage, otel-collector, rclone | 0 | 0 |
| docker-socket-proxy v0.5.0 | 9 altas (Alpine) | Sin cambio: 3.4 sale limpia, va en S9.8 (S-28) |

Sin arreglo publicado (no bloquean): la base Debian 12 de core e invoicing trae unas 100 altas y 2 críticas. Pasar a Debian 13
las baja a la mitad y deja 0 críticas; va en S9.8, con las bases fijadas por digest.

## 5. Pruebas

Las manuales de §5.1 a §5.7 corrieron contra un core local con el código de la rama:

- base aislada `faclab_s93`, migrada y con `scripts.seed`: dos empresas con el mismo catálogo;
- un ADMIN desechable en ambas;
- `KAFKA_ENABLED=false`.

El guion completo quedó fuera del repo; cada fila dice qué se mandó y qué respondió.

### 5.1 Acceso cruzado entre empresas (A con ids de B)

| Prueba | Respuesta |
|---|---|
| `GET` de un producto de B | 404 `NOT_FOUND` |
| `PUT` de un cliente de B | 404 |
| `DELETE` de una bodega de B | 404 |
| Movimiento de A con el producto de B | 422 `REFERENCE_NOT_FOUND`, igual que un producto inexistente; nada se escribe |
| `X-Branch-Id` de B en una ruta de sucursal (`/api/pos/terminals`) | 404 |
| `X-Branch-Id` de B en una ruta sin sucursal | Se ignora y queda en la bitácora (S-31) |
| Listado de productos de A | Sin filas de B |
| Integración de A pide el producto de B en `/api/v1` | 404 |

### 5.2 Escalamiento de permisos y tokens

| Prueba | Respuesta |
|---|---|
| CAJERO lista usuarios / lee la bitácora / importa | 403 `PERMISSION_DENIED` |
| GERENTE lista usuarios, se sube a ADMIN, crea una integración | 403 `PERMISSION_DENIED` |
| Sin token | 403 `PERMISSION_DENIED` (S-45) |
| Token con la firma cambiada | 401 `INVALID_TOKEN` |
| Token con rol y permisos agregados (firma original) | 401 `INVALID_TOKEN` |
| Token `alg=none` | 401 `INVALID_TOKEN` |
| Token de integración en `/api/admin` | 403 `INTEGRATION_NOT_ALLOWED` |
| Integración sin el scope (`customers:read`) | 403 `INSUFFICIENT_SCOPE` |
| Token OAuth con un secreto equivocado | 401 `invalid_client` |

### 5.3 SSRF en webhooks

Se intentó registrar un endpoint con cada una de estas URLs. Todas respondieron 422 `WEBHOOK_URL_NOT_ALLOWED`:

- loopback y nombres locales: `https://127.0.0.1/`, `https://localhost/`, `https://[::1]/`;
- metadatos de la nube: `https://169.254.169.254/latest/meta-data`;
- red privada: `https://10.0.0.5/`, `https://[fd00::1]/`;
- IPv4 dentro de IPv6: `https://[::ffff:127.0.0.1]/` y `https://[64:ff9b::7f00:1]/` (NAT64, nuevo);
- un nombre que resuelve a loopback: `https://127.0.0.1.nip.io/`;
- otros esquemas o credenciales en la URL: `http://example.com/`, `https://user:pass@example.com/`, `file:///etc/passwd`.

Las redirecciones y el rebinding en el momento del envío los cubren las pruebas unitarias (`tests/unit/webhooks/test_http.py`).

### 5.4 Cargas de archivos

| Prueba | Respuesta |
|---|---|
| XLSX de 4 KB con dimensión `A1:XFD1048576` y una fila lejana | 422 `IMPORT_FILE_INVALID` en 23 ms (antes: minutos de CPU) |
| XLSX de 112 KB con una fila de un millón de celdas | 422 en 17 ms |
| CSV de 9 MB de líneas vacías | 422 en 156 ms |
| Archivo de 12 MB | 413 antes de leer el cuerpo |
| `.xls` | 422 |
| Importación por un CAJERO | 403 |
| `.p12` con 2.000 millones de iteraciones en su MAC; PFX con ocho derivaciones de 100.000 | `P12IterationsError` en menos de 1 s (`test/certificate/p12-parser.test.ts`) |
| `.p12` de más de 64 KB | 400 sin procesarlo (`certificate-routes.test.ts`) |
| PNG de 64 KB que se descomprime a 64 MiB | Rechazado en menos de 200 ms (`logo.test.ts`) |

### 5.5 Límites

| Prueba | Respuesta |
|---|---|
| Cuerpo JSON de 1,5 MiB | 413 `REQUEST_TOO_LARGE` |
| Sexto login fallido del mismo usuario | 429 `LOGIN_LOCKED` |
| 70 lecturas seguidas de la API pública | 57 × 200 y 13 × 429 `RATE_LIMITED` con `Retry-After` |
| JSON mal formado | 422 genérico, sin repetir la entrada |

### 5.6 Cabeceras y CORS

- core responde con `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` y `X-Request-Id`.
- Un preflight desde `https://evil.example` recibe 400 sin `Access-Control-Allow-Origin`.

### 5.7 Operador de plataforma (S-01)

Un usuario de la empresa A dado de alta como operador con la CLI:

| Prueba | Respuesta |
|---|---|
| El ADMIN de A le resetea la contraseña | 409 `USER_IS_PLATFORM_OPERATOR` |
| El ADMIN de A lo renombra | 409 `USER_IS_PLATFORM_OPERATOR` |
| Login de consola con la contraseña que el ADMIN intentó poner | 401 |
| Login de consola del operador | 200 |
| Token de plataforma en `/api/admin` | 403 `PLATFORM_NOT_ALLOWED` |
| Token de empresa en `/api/platform` | 403 |

Las dos pruebas nuevas de `test_platform_console.py` fallan con el código de `master` y pasan con el de la rama.

### 5.8 Borde en staging

Staging corre las versiones 0.1.0 y 0.2.0-rc.9: los cambios de Caddy de esta sesión se validaron en local con
`caddy validate` y un request real.

**Cabeceras.**
- **app:** CSP con `frame-ancestors 'none'` y `object-src 'none'`, `Permissions-Policy`, `X-Frame-Options: DENY`, `nosniff`,
  `Referrer-Policy` y HSTS (300 s en staging, a propósito; 1 año en producción).
- **API:** HSTS, `nosniff` y `Referrer-Policy`; core agrega `X-Frame-Options`; invoicing ninguna propia (S-29).

**Redirección.** `http://` responde 308 a `https://`, también en el API (S-36).

**Rutas internas.** `/health`, `/health/ready`, `/docs`, `/docs/admin`, `/openapi.json` y `/openapi/admin.json` dan 404. Por
diseño dan 200 `/docs/public`, `/openapi/public.json` y `/.well-known/jwks.json`. `/api/v1/invoices` sin token da 403.

**Cuerpo de 3 MiB al API.** 413 de Caddy.

**25 logins seguidos.** 5 × 401 y después 429: el bloqueo por usuario de core corta antes que el límite por IP de Caddy.

**TLS (testssl.sh).**
- Solo TLS 1.2 y 1.3, con secreto hacia adelante y suites AEAD.
- KEM X25519MLKEM768, ALPN h2.
- Ninguno de Heartbleed, ROBOT, CRIME, BREACH, POODLE, SWEET32, FREAK, DROWN, LOGJAM, BEAST, LUCKY13 ni RC4.

**Puertos (nmap, los 65.535 TCP).** Abiertos solo 22, 80 y 443; el resto, filtrado por el firewall.

### 5.9 Pruebas automatizadas nuevas

- **core:**
  - pruebas unitarias de A1, del lector de hojas (dimensión, fila lejana, fila ancha, elementos acumulados, descompresión,
    líneas vacías, encabezado ancho) y de NAT64;
  - en PostgreSQL: el operador, el secreto OAuth de otra empresa y 20 probes de aislamiento;
  - la meta-prueba `tests/integration/test_isolation_id_fields.py`.

  Resultado: `pytest tests/` 2.988 pasan; `make test-integration` 896 pasan.
- **invoicing:**
  - límites del `.p12` y de la subida, y el PNG;
  - `test/http/route-guards.test.ts`: llama a todas las rutas sin token, como usuario sin permisos y como integración sin el
    scope; todas deben responder 403;
  - `findOnboardingTest` por empresa en PostgreSQL.

  Resultado: 541 pruebas y 68 de PostgreSQL pasan.
- **web:** el generador de contraseñas sin sesgo. 577 pruebas pasan.
- **faclab-infra `e2e/run.sh`:** construye las cuatro ramas con Kafka 7.9.11 y recorre del turno a la conciliación; pasa con 0
  mensajes fallidos y 0 dead letters.

## 6. Configuración de GitHub

Aplicada con `gh api` en los cuatro repos el 2026-11-27:

- **Dependabot:** alertas activadas. Las actualizaciones de seguridad se activan después del merge.
- **Escaneo de secretos con bloqueo en push:** activado. Su única alerta, en core, era el vector de prueba público de la
  especificación Standard Webhooks (`tests/unit/webhooks/test_signing.py`); se cerró como usado en pruebas.
- **CodeQL (configuración por defecto):** activado. Primeras alertas:
  - 5 altas;
  - 3 corregidas (S-16);
  - 2 descartadas con justificación: SHA-1 de XAdES (S-43) y el secreto que `scripts/sandbox.py` muestra una sola vez al
    operador cuando no se le pasa `--credentials-file`, como lo hace el API al crear el cliente.
- **Rulesets de tags `v*`:** activos (S-10).
- **Pendiente del dueño:** exigir 2FA en la organización (S-44).

## 7. Mantenimiento

- **Una alerta nueva del escaneo semanal:** se corrige subiendo la versión. Si no se puede, va a `.trivyignore.yaml` con
  motivo y `expired_at` dentro del plazo de su severidad, y se anota aquí.
- **Una excepción vencida:** vuelve a romper el job.
- **Un cambio de versión de Caddy, Kafka o del socket proxy:** se revisa el job informativo `third-party-images` de infra.
- **El reemplazo de x/net en faclab-caddy (S-07):** se quita cuando el `go.mod` de Caddy traiga 0.62; lo mismo con la
  excepción de web (S-37).
