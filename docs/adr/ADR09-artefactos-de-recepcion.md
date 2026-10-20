# ADR09: Artefactos de recepción (manifiesto, inventario y auditoría)

- **Estado:** Propuesta
- **Tipo:** P (propuesta de este equipo; no figura en la documentación)
- **Fecha de registro:** 2026-10-19
- **Fuente:** plan de DEV00 (fases F0–F10) y `documentacion/documentos/02_Requisitos_y_plan.md`, tarea DEV00
- **Relacionado con:** `docs/actas/2026-10-19-dev00-f0-decisiones-y-r0.md` (decisión D1)

## Decisión

1. **Copia inmutable de entrada** en `datos/originales/sumo/<snapshot_id>/` (ignorada por git). El identificador es un SHA-256 sobre la lista ordenada de (ruta relativa, hash) de la configuración de entrada y de los archivos que referencia. Las salidas de SUMO y los archivos no referenciados se registran con hash, pero no forman parte de la identidad.
2. **Manifiesto de recepción, inventario de red y auditoría de rutas** como JSON con `schema_version` 1.0.0, validados con DTO (pydantic) dentro de `caso`. Se guardan en `datos/derivados/recepcion/<reception_id>/`.
3. **Corridas de SUMO** con el contrato que ya existe, `run_manifest` (`schemas/run_manifest.schema.json`), en `datos/ejecuciones/<run_id>/` y sobre una copia aislada de las entradas.
4. **Informe versionado** en `docs/recepcion/<reception_id>.md`: hashes, versión de SUMO, inventario, hallazgos y estado propuesto.
5. Cada recepción crea un `reception_id` nuevo. Nunca se sobrescribe nada.

## Motivo

DEV00 exige un inventario y una corrida base reproducibles, y la simulación seguirá cambiando. Cada recepción debe poder repetirse, compararse con la anterior y quedar trazada. Hoy ningún módulo fuera de `caso` consume el inventario; el primer consumidor será DEV03.

## Alternativas descartadas

- Publicar esquemas JSON de recepción en `schemas/` desde ahora: más trabajo sin consumidor externo todavía.
- Solo Markdown o CSV: no permite comparar recepciones de forma automática.

## Impacto

Afecta a `caso/`, `trazabilidad/`, `app/`, `cli/` y `docs/recepcion/`. Cuando DEV03 consuma el inventario, se evaluará convertirlo en contrato público, con una nueva versión de esta decisión.

## Prueba de aceptación

Nombres propuestos; se concretan al implementar cada fase:

- F2: `tests/unit/test_reception.py` (identidad por contenido, doble hash, rutas fuera del workspace).
- F3: `tests/unit/test_inventory.py`.
- F4: `tests/unit/test_audit.py`.
- F5: `tests/unit/test_run_manifest.py` (el esquema del DTO es idéntico a `schemas/run_manifest.schema.json`).
- F6: QA07 y QA08.
- F9: QA09 (réplica con la misma semilla).

**Para aceptar:** el Product Owner confirma antes de cerrar F2.
