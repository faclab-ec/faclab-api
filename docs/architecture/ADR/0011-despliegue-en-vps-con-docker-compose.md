# ADR-0011: Despliegue en VPS con Docker Compose y Caddy

- **Estado:** aceptado (2026-11-22, S8.1; propuesto el 2026-10-14)
- **Relacionado:** [TARGET_ARCHITECTURE.md](../TARGET_ARCHITECTURE.md), [ADR-0007](0007-worker-para-procesos-en-segundo-plano.md)

## Contexto

El usuario eligió desplegar en un VPS con Docker. No hay infraestructura de producción, imágenes
publicadas ni respaldos (G-59). PostgreSQL 14 deja de recibir parches el 12/11/2026 (G-58).

## Alternativas

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| A. Docker Compose en uno o dos VPS + Caddy | Simple, barato, entendible por una persona | Sin autoescalado; la alta disponibilidad requiere trabajo manual |
| B. Kubernetes ligero (k3s) | Despliegues declarativos, escalado | Complejidad desproporcionada para el volumen actual |
| C. Servicios administrados en la nube | Menos operación | Contradice la decisión del usuario; costo mayor |

## Decisión

**A.**

- **VPS de aplicación**:
  - Caddy (TLS automático, proxy por dominio y ruta, límites por IP).
  - `core-api`, `core-worker`, `invoicing-api` e `invoicing-worker`.
  - `web`: estáticos servidos por Caddy.
  - PostgreSQL 17 con dos bases (`faclab`, `faclab_invoicing`), Kafka KRaft y OTel Collector.
- **VPS de observabilidad** separado, o SigNoz Cloud (decisión D-1).
- **Imágenes** en GitHub Container Registry con tags semánticos. El despliegue corre por SSH desde CI:
  1. `docker compose pull`.
  2. Migraciones como tarea única.
  3. `up -d`.
  4. Verificación de `/health/ready`.
- **Secretos**: archivos `.env` cifrados con sops y age en un repositorio de despliegue, o Docker
  secrets. Nunca en las imágenes (`.dockerignore`).
- **Red**: solo 80 y 443 abiertos; PostgreSQL, Kafka y el Collector en la red interna de Docker; acceso
  de administración por SSH con llave o VPN.
- **Respaldos**: PostgreSQL con recuperación a un punto en el tiempo (PITR, por ejemplo pgBackRest o
  WAL-G) hacia almacenamiento externo, y una prueba de restauración mensual.

## Consecuencias

- Las actualizaciones tienen una breve interrupción. Aceptable para el piloto; se puede mejorar con dos
  réplicas del API detrás de Caddy.
- Hay que documentar runbooks de despliegue, reversión y restauración (S8.2, S8.3).

## Avance

- **S1.2 (2026-10-14)**: el core ya tiene lo que este despliegue espera de su imagen:
  - `.dockerignore`, así que no entran secretos;
  - etapa `production` sin compiladores, como usuario `app`, con `WEB_CONCURRENCY` workers y
    `--proxy-headers`, confiando en `FORWARDED_ALLOW_IPS` porque solo Caddy la expone;
  - `HEALTHCHECK` sobre `/health/live`;
  - `/health/ready` para el paso 4 del despliegue;
  - `alembic` incluido para correr las migraciones como tarea única.

  PostgreSQL 17 ya corre en local y en CI. Falta el compose de producción (S8.1) y la publicación de
  imágenes (S8.2).

- **S1.3 (2026-10-15)**: invoicing y web también tienen su imagen.
  - **Invoicing**:
    - `node:22-bookworm-slim` como `app`, con `HEALTHCHECK` en `/health`;
    - toda la configuración que depende del entorno sale de variables, y producción no arranca sin
      ellas;
    - el ambiente del SRI lo fija cada emisor en su configuración (`PUT /api/company-config`), no una
      variable: `SRI_ENVIRONMENT` no existe. Con `NODE_ENV=production` puede llegar a los dos ambientes.
  - **Web**:
    - Caddy en Alpine en el puerto 8080, sin TLS: se lo pone el Caddy de entrada;
    - `API_BASE_URL` e `INVOICING_API_URL` se leen al arrancar, así que la misma imagen sirve en
      cualquier entorno.
    - La decisión dice "estáticos servidos por Caddy". Puede ser este contenedor detrás del proxy, o
      el Caddy de entrada sirviendo los archivos; S8.1 elige.
  - Para S8.1 queda:
    - con `read_only`, la web necesita un tmpfs en `/srv/runtime` del usuario `app`;
    - las URLs públicas tienen que coincidir con `CORS_ORIGINS` del core y de invoicing.

- **S8.1 (2026-11-22)**: el stack de producción está en `faclab-infra/deploy/production`. Lo que se
  decidió aquí:
  - **Dominios (D-9).**
    - `app.<dominio>` sirve la web y `/otlp`, que va al receptor OTLP/HTTP del Collector con 1 MiB y
      límite por IP.
    - `api.<dominio>` sirve el core y manda a invoicing `/api/v1/invoices*`, `/api/invoices*`,
      `/api/invoicing*`, `/api/certificates*`, `/api/company-config*` y `/api/sequences*`, así que
      `INVOICING_API_URL` es igual a `API_BASE_URL`.
    - La documentación pública queda en `api.<dominio>/docs/public`.
    - Al ser el mismo sitio, la cookie `SameSite=Strict` funciona.
  - **La web**: su contenedor detrás del Caddy de entrada, `read_only` con tmpfs en `/srv/runtime`,
    para conservar su `config.js` de tiempo de ejecución.
  - **Caddy de entrada**:
    - una imagen propia con `caddy-ratelimit`, fijado en un commit porque no publica versiones;
    - límites por IP (general, login y OAuth, `/otlp`) y de cuerpo (2 MiB, 11 MiB en importaciones);
    - HSTS, CSP en la web, `nosniff`, `Referrer-Policy` y `Permissions-Policy`;
    - `/health` no es público;
    - TLS de Let's Encrypt, o de su CA interna en staging.
  - **PostgreSQL**:
    - una instancia 17 con las dos bases;
    - los roles del core los crea `db_roles` con el superusuario solo en esa corrida; el de invoicing,
      `init-invoicing-db.sh`;
    - las migraciones corren como tareas únicas antes de los servicios.
  - **Kafka**: un nodo, PLAINTEXT solo en una red interna, sin puertos ni kafka-ui. G-49 queda mitigada
    por aislamiento; TLS y SASL hacen falta si sale del servidor.
  - **Almacenamiento de objetos (D-2)**: Garage, un nodo, en la red interna.
  - **Secretos**:
    - sops y age, en archivos cifrados por entorno fuera del repositorio;
    - se descifran en la máquina del operador y llegan por SSH a `/etc/faclab`, cada archivo con el
      dueño que lo lee;
    - como Docker secrets van la llave JWT, las llaves Fernet y la contraseña del superusuario; lo
      demás, como variables;
    - la rotación de cada uno está en la guía.
  - **Red**: tres redes, `egress`, `proxy` (interna) y `data` (interna). Solo Caddy publica 80, 443 y
    443/udp. ufw cierra lo demás del host, pero no filtra los puertos que publica Docker.
  - **Imágenes**: hasta S8.2, el servidor las construía desde Git en una ref fija
    (`compose.build.yml`); S8.2 las trae de GHCR.
  - **Un solo VPS** de aplicación; SigNoz sigue fuera (D-1, S8.6).

- **S8.2 (2026-11-22)**: la entrega continua que pedía la decisión ("imágenes en GitHub Container
  Registry con tags semánticos; el despliegue corre por SSH desde CI").
  - **Versiones:** cada repositorio tiene tags `vX.Y.Z`, su CHANGELOG y `scripts/release.sh`. Hasta el
    piloto van en 0.x.
  - **Imágenes:** un tag publica la del repositorio, para amd64 y arm64, con `service.version` igual a
    la versión: `faclab-api`, `faclab-invoicing`, `faclab-web` y el Caddy de entrada, `faclab-caddy`.
    Los paquetes son públicos, como los repositorios.
  - **Versiones por entorno:** `deploy/production/versions/<entorno>.env` en faclab-infra; cambiarlas
    es un PR, y el CI lo rechaza si la combinación no está en `COMPATIBILITY.md` (publica, acepta y
    requiere de cada versión).
  - **Despliegue:** el workflow `Deploy`, o `deploy.sh` desde la máquina del operador, entra por SSH
    con una llave que solo puede correr `remote.sh`. Allí `stack.sh deploy`:
    - toma un lock y hace checkout de faclab-infra en su tag;
    - fija las imágenes por digest;
    - respalda las dos bases con `pg_dump`;
    - mueve el esquema, hacia atrás si la versión es más vieja, y migra;
    - actualiza infra, invoicing, core y web en ese orden, cada uno con su salud;
    - comprueba Caddy, la versión de cada contenedor y que nada se reinicie.
  - **Reversión:**
    - si algo falla, vuelve sola a la versión anterior: baja el esquema con las imágenes nuevas y
      levanta las anteriores por digest;
    - a mano, es un comando (`deploy.sh <entorno> rollback`);
    - `restore-predeploy` restaura el respaldo previo, para las migraciones que no se revierten.
  - **Migraciones:** las nuevas deben ser aditivas (expand/contract). La guía clasifica las anteriores
    por cómo se revierten.
  - Se probó en la VM de staging, con una versión rota que se revirtió sola. La primera corrida del
    workflow desde GitHub queda para el primer VPS: la VM no tiene IP pública.

- **S8.3 (2026-11-24)**: respaldos y recuperación (`faclab-infra/deploy/production/RESPALDOS.md`).
  - **PostgreSQL:** pgBackRest dentro de su contenedor, con la imagen `faclab-postgres` (la oficial
    más pgBackRest, publicada por el release de faclab-infra):
    - WAL continuo, a lo sumo 60 s después de cada escritura;
    - un completo semanal y un incremental diario, cifrados con AES-256 antes de salir;
    - todo a un bucket compatible con S3 de otro proveedor, y 4 completos de retención (de 4 a 5
      semanas de recuperación a un punto en el tiempo).

    Es un respaldo físico: la seguridad por filas forzada no lo afecta, a diferencia de `pg_dump`.
  - **Comprobantes:** Garage no tiene versionado ni Object Lock. rclone copia su bucket, cifrado
    (crypt), a otro bucket con versionado y Object Lock en modo compliance durante el plazo legal
    (7 años, por confirmar con el contador), con una llave que no borra.
  - **Operación:**
    - timers de systemd que instala `stack.sh deploy` con `BACKUPS=on`;
    - métricas `faclab.backup.*` al Collector y alertas `respaldo-fallido`, `respaldo-atrasado` y
      `wal-sin-archivar`;
    - `stack.sh restore <hora|latest>` restaura a un punto en el tiempo, en un servidor limpio o en
      el mismo, y despliega las versiones anotadas en el respaldo; `restore-objects` trae los
      comprobantes.
  - **Objetivos:** RPO de 5 minutos y RTO de 2 horas. El simulacro en una VM limpia tardó 10 minutos
    de máquina, con el resumen idéntico al origen en el punto elegido; la pérdida medida fue menor a
    77 s.
  - **El contenedor de PostgreSQL** corre con docker-init como PID 1 y `CAP_KILL` (lo pidió el
    archivo asíncrono de pgBackRest), y su archivo de WAL va en `postgresql.auto.conf`, no en la línea
    de comandos.
  - Staging usa un sustituto local de S3 (versitygw). El proveedor real llega con el primer VPS. La
    prueba de restauración mensual de esta decisión sigue la guía de `RESPALDOS.md`.
