# ADR-0011: Despliegue en VPS con Docker Compose y Caddy

- **Estado:** propuesto (2026-10-14)
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
    - `SRI_ENVIRONMENT` es explícito.
  - **Web**:
    - Caddy en Alpine en el puerto 8080, sin TLS: se lo pone el Caddy de entrada;
    - `API_BASE_URL` e `INVOICING_API_URL` se leen al arrancar, así que la misma imagen sirve en
      cualquier entorno.
    - La decisión dice "estáticos servidos por Caddy". Puede ser este contenedor detrás del proxy, o
      el Caddy de entrada sirviendo los archivos; S8.1 elige.
  - Para S8.1 queda:
    - con `read_only`, la web necesita un tmpfs en `/srv/runtime` del usuario `app`;
    - las URLs públicas tienen que coincidir con `CORS_ORIGINS` del core y de invoicing.
