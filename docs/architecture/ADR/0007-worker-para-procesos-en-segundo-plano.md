# ADR-0007: Contenedor `worker` para procesos en segundo plano

- **Estado:** propuesto (2026-10-14)
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
- La variable `RUN_BACKGROUND=false` en el API mantiene el comportamiento actual durante la transición.
- Las tareas periódicas usan bloqueos en la base (`pg_try_advisory_lock` o filas con `SKIP LOCKED`), así
  que se puede correr más de un `worker` sin duplicar trabajo.
- En facturación se aplica lo mismo: el consumidor solo registra la venta. Un worker con cola en
  PostgreSQL (S4.2) firma, envía y autoriza.

## Consecuencias

- El VPS corre un contenedor más por servicio (poco costo).
- El health check del worker reporta el último ciclo exitoso de cada tarea.
- No se agrega un orquestador de tareas como Celery: no hay volumen que lo justifique.
