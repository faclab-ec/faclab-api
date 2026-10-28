# ADR-0007: Contenedor `worker` para procesos en segundo plano

- **Estado:** aceptado (2026-10-28, S3.4; propuesto el 2026-10-14)
- **Relacionado:** [ADR-0005](0005-kafka-outbox-y-consumidores-idempotentes.md), [ADR-0011](0011-despliegue-en-vps-con-docker-compose.md)

## Contexto

El relay del outbox, el productor y el consumidor de Kafka corren como hilos dentro de cada proceso del
API (`main.py:80-110`). Con varios workers de uvicorn se multiplican. Si el API se reinicia por un
despliegue, la mensajería se detiene. En facturación, el consumidor también ejecuta las llamadas al SRI
(G-13). Pronto se sumarán entregas de webhooks, conciliación y limpieza de sesiones y outbox.

## Decisión

- Misma imagen, dos comandos:
  - `api` sirve HTTP con gunicorn y workers uvicorn, sin hilos de mensajería.
  - `worker` ejecuta el relay, los consumidores y las tareas periódicas (conciliación, purga del outbox
    y de `auth_sessions`, entregas de webhooks).
- La variable `RUN_BACKGROUND` decide si el API también corre la mensajería: `true` mantiene el
  comportamiento anterior durante la transición (y sirve para volver atrás), `false` la deja solo en
  el worker.
- Las tareas periódicas usan bloqueos en la base (`pg_try_advisory_lock` o filas con `SKIP LOCKED`), así
  que se puede correr más de un `worker` sin duplicar trabajo.
- En facturación se aplica lo mismo: el consumidor solo registra la venta. Un worker con cola en
  PostgreSQL (S4.2) firma, envía y autoriza.

## Consecuencias

- El VPS corre un contenedor más por servicio (poco costo).
- El health check del worker reporta el último ciclo exitoso de cada tarea.
- No se agrega un orquestador de tareas como Celery: no hay volumen que lo justifique.

## Implementación (S3.4, 2026-10-28)

- `worker.py` en la raíz. Con `KAFKA_ENABLED` arranca productor, relay y consumidor
  (`src/background/messaging.py`), y siempre las purgas del outbox publicado, las claves de
  idempotencia y las sesiones revocadas o vencidas (`src/background/tasks.py`), cada
  `WORKER_PURGE_INTERVAL_SECONDS`.
- Apagado ordenado con SIGTERM/SIGINT: consumidor, relay, productor y OpenTelemetry
  (`service.name=faclab-core-worker`).
- Salud: `WorkerHealth` escribe el último ciclo exitoso de cada tarea en `WORKER_HEALTH_FILE`, y
  `python -m src.shared.infra.worker.health` es el healthcheck del contenedor.
- Las purgas no toman lock porque son DELETE idempotentes. El relay usa un advisory lock por lote.
- `RUN_BACKGROUND` vale `true` por defecto. `docker-compose.yml` del core lo pone en `false` y levanta el
  servicio `worker`, y el stack de producción (S8.1) hará lo mismo.
- El API sigue con uvicorn y `WEB_CONCURRENCY` workers (S1.2), no con gunicorn.
- Staging y producción exigen `DATABASE_URL_WORKER` siempre.
