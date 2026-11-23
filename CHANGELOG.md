# Cambios

Cada versión de faclab-core y lo que trae, la más reciente arriba. Sigue
[versionado semántico](https://semver.org/lang/es/): mientras empiece por 0 (hasta el piloto), una
versión menor puede romper la compatibilidad. `scripts/release.sh` escribe cada sección a partir de
los commits convencionales de `master` (README, "Versiones y publicación").

Si una versión cambia lo que publica o acepta por Kafka (`schema_version`, `contracts/`) o trae una
migración que no se puede revertir, su sección lo dice en una línea **Contratos** o **Migraciones**.
Qué versiones de core, invoicing y web funcionan juntas lo dice la
[matriz de compatibilidad](https://github.com/faclab-ec/faclab-infra/blob/master/deploy/production/COMPATIBILITY.md).

## [0.1.0] - 2026-11-22

Primera versión etiquetada: todo lo construido hasta la entrega continua (S8.2). La historia anterior
está en el historial de Git y en `docs/architecture/ROADMAP.md`.

- **Contratos:** publica `sales.confirmed` v3 y `credit_notes.requested` v2; acepta `invoices` v1 y
  `credit_notes.results` v1. API pública `/api/v1` 1.1.0.
- **Migraciones:** la cadena desde la línea base `80ccdab134c7` hasta `e5b8c1d4a7f2`. La guía de
  despliegue de faclab-infra lista las que fallan o pierden datos al revertirse.
