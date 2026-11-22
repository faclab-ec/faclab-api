## Descripción

<!-- Describe brevemente los cambios realizados -->

## Tipo de cambio

<!-- Marca con una 'x' el tipo de cambio que aplica -->

- [ ] Nueva funcionalidad (feature)
- [ ] Corrección de bug (fix)
- [ ] Refactorización (refactor)
- [ ] Documentación (docs)
- [ ] Pruebas (test)
- [ ] Otros

## Checklist

- [ ] El código sigue las convenciones del proyecto
- [ ] Se han ejecutado las pruebas y pasan correctamente
- [ ] Se han actualizado las migraciones de base de datos (si aplica)

## Observabilidad (definición de terminado)

<!-- docs/architecture/OBSERVABILITY.md §10. Marca lo que aplica; si algo no aplica, explica por qué -->

- [ ] Los logs nuevos tienen un evento estable (`snake_case`, que da su `event.name`), sin secretos ni datos personales (§4.6)
- [ ] Las operaciones nuevas tienen sus métricas en `src/shared/infra/telemetry_instruments.py` y en el `CATALOG` de `tests/unit/shared/test_metric_attributes.py`, sin ids como atributos; un histograma en segundos tiene sus cubetas en `histogram_views()`
- [ ] Las rutas críticas nuevas o cambiadas tienen sus spans y una prueba que los fija, con su padre y su traza (`span_exporter`, `json_logs` y `tests/telemetry.py`)
- [ ] Si el cambio trae un modo de fallo nuevo, tiene su panel o su alerta (con runbook) en `faclab-infra/observability/signoz/`
