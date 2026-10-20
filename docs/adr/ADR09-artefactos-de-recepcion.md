# ADR09: Artefactos de recepción (manifiesto, inventario y auditoría)

- **Estado:** Aceptada (2026-10-19), con las recomendaciones del Product Owner
- **Tipo:** P (propuesta de este equipo; no figura en la documentación)
- **Fecha de registro:** 2026-10-19
- **Fecha de aceptación:** 2026-10-19
- **Fuente:** plan de DEV00 (fases F0–F10) y `documentacion/documentos/02_Requisitos_y_plan.md`, tarea DEV00
- **Relacionado con:** `docs/actas/2026-10-19-dev00-f0-decisiones-y-r0.md` (decisiones D1 y D6)

## Decisión

1. **Identidad de la copia (`snapshot_id`).** La copia de entrada va a `datos/originales/sumo/<snapshot_id>/`, ignorada por git.
   - El `snapshot_id` es el SHA-256 de una lista ordenada con una línea por archivo: `<ruta relativa>\t<sha256>\n`.
   - La lista incluye el `.sumocfg` de entrada y los archivos de su sección `<input>`. Si un valor es una lista separada por comas, cada archivo cuenta por separado. Las rutas se resuelven respecto a la carpeta del `.sumocfg`.
   - Quedan fuera de la identidad la sección `<gui_only>` (vistas), la sección `<output>`, las salidas de SUMO y los archivos no referenciados. Se registran con hash en el manifiesto, pero no cambian el `snapshot_id`.
   - La copia contiene únicamente los archivos de identidad. Los demás archivos se registran en el manifiesto con su hash y su rol, pero no se copian.
   - Consecuencia: volver a ejecutar la GUI no crea una versión nueva; cambiar una ruta o la red sí.

2. **Dos identificadores distintos.**
   - `snapshot_id`: qué contiene la copia, por contenido.
   - `reception_id`: cada análisis sobre una copia. Formato: `<AAAAMMDDTHHMMSSZ>_<primeros 8 caracteres del snapshot_id>`, con hora UTC para evitar ambigüedad.
   - Una copia puede tener muchas recepciones. Cada recepción es nueva y nunca sobrescribe otra.

3. **Manifiesto, inventario y auditoría** como JSON con `schema_version` 1.0.0, validados con DTO pydantic dentro de `caso`. Se guardan en `datos/derivados/recepcion/<reception_id>/`. `pydantic` y `defusedxml` pasan a dependencias de ejecución en F2.

4. **Corridas de SUMO** con el contrato existente `run_manifest` (`schemas/run_manifest.schema.json`), en `datos/ejecuciones/<run_id>/`, siempre sobre una copia aislada de las entradas.

5. **Publicación en el repositorio.** El repositorio es público, así que `docs/recepcion/<reception_id>.md` contiene solo:
   - el `snapshot_id`, el `reception_id`, la versión de SUMO, la fecha, el estado propuesto y la lista de archivos con sus hashes;
   - rutas relativas, nunca rutas absolutas de un equipo.
   
   Los hallazgos detallados (red, semáforos, rutas, demanda y resultados) quedan en `datos/derivados/recepcion/<reception_id>/hallazgos.md`, ignorado por git, hasta que el Product Owner los revise y autorice su publicación.

6. **Copia R0 (`R0-provisional`).** La carpeta actual `datos/originales/sumo/R0-provisional/` no se renombra. Se registra como alias del `snapshot_id` que calcule F2, y ese alias se anota en el acta.

## Motivo

DEV00 exige un inventario y una corrida base reproducibles, y la simulación seguirá cambiando. Cada recepción debe poder repetirse, compararse con la anterior y quedar trazada. Hoy ningún módulo fuera de `caso` consume el inventario; el primer consumidor será DEV03.

## Alternativas descartadas

- Publicar esquemas JSON de recepción en `schemas/` desde ahora: más trabajo sin consumidor externo todavía.
- Solo Markdown o CSV: no permite comparar recepciones de forma automática.
- Publicar los hallazgos detallados desde el inicio: el repositorio es público y la simulación aún no está revisada.

## Impacto

Afecta a `caso/`, `trazabilidad/`, `app/`, `cli/`, `docs/recepcion/` y `datos/derivados/recepcion/`. Cuando DEV03 consuma el inventario, se evaluará convertirlo en contrato público, con una nueva versión de esta decisión.

## Prueba de aceptación

Nombres propuestos; se concretan al implementar cada fase:

- F2: `tests/unit/test_ids.py` (identidad por contenido y orden invariante), `tests/unit/test_sumo_config.py` (referencias, listas separadas por comas y XML peligroso), `tests/unit/test_reception_models.py` (el manifiesto solo admite rutas relativas) y `tests/unit/test_reception.py` (identidad con entradas y sin `gui_only` ni `output`, doble hash, enlaces, rutas fuera de la carpeta y archivos bloqueados).
- F3: `tests/unit/test_inventory.py`.
- F4: `tests/unit/test_audit.py`.
- F5: `tests/unit/test_run_manifest.py` (el esquema del DTO es idéntico a `schemas/run_manifest.schema.json`).
- F6: QA07 y QA08.
- F8: el informe publicado no contiene rutas absolutas.
- F9: QA09 (réplica con la misma semilla).

**Aceptada por el Product Owner el 2026-10-19.** Implementada en F2 (copia, identidad y manifiesto), F3 (inventario de red y semáforos), F4 (auditoría de rutas, demanda y comportamiento) F5 (manifiesto y carpeta de ejecución) F6 (corridas de SUMO sobre copias aisladas), F7 (registro de la recepción y CLI) F8 (informe público verificado sin rutas absolutas, planillas QA23 y QA24 y comparación entre recepciones) y F9 (recepción de R0 de punta a punta, QA07, QA08 y QA09).
