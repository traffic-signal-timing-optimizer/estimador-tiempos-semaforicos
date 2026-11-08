# DEV31 F4c C2: preparación y validación de candidata

**Fecha:** 2026-11-08 (hora de Lima)

**Alcance:** C2.1–C2.7, puertas P0–P7 del plan aprobado `2026-11-07-dev31-plan-correcciones-auditoria.md`.
**Estado de esta acta:** P0–P7 aprobados por evidencia; falta D11 del Product Owner para ejecutar P8 y P9. Esta acta no cierra C2.

## Resultado

Se implementaron las correcciones de C2 y se preparó la candidata `semaforo_candidata_20261108053049`. La base `semaforo` pasó P0 contra la referencia Git. P1–P5 y P7 pasaron en la candidata; P6 pasó en bases desechables con el mismo esquema y catálogo. La puerta completa terminó correctamente: 5434 pruebas pasaron, 1 se omitió y los contratos dieron 43/43.

La candidata queda esperando la decisión D11. No se ejecutaron P8 ni P9, no se cambió el nombre de la base vigente y no se escribió en `semaforo`.

## Cambios implementados

- **C2.1, cola con arreglos nativos:** `QueueSeries` y la base validan tipos, valores finitos y no negativos, tiempos ordenados y longitudes. La inserción usa arreglos PostgreSQL por la ruta normal, sin expandirlos en matrices para `unnest`.
- **C2.2, conciliación por contenido:** compara posición por posición la serie de cola y, por clave, accesos, movimientos, vehículos, demora recalculada y eventos. La prueba detecta intercambio y cambio de valor.
- **C2.3, accesos sin cohorte:** cada acceso medido produce su fila. `con_cohorte` distingue una demora ausente legítima y la restricción impide mezclarla con valores de demora.
- **C2.4, protocolo de métricas:** el manifiesto nuevo es 1.1.0 e incluye la huella SHA-256 del archivo de protocolo. Los manifiestos 1.0.0 siguen legibles y se reportan como legado. Se exige igualdad del protocolo en búsquedas y etapas finales cuando la corrida declara protocolo; los diagnósticos históricos sin protocolo propio conservan el protocolo de sus métricas.
- **C2.5, selección congelada:** el hito de congelación registra selección y huella; la selección exige protocolo congelado y unicidad por modelo ganador; la apertura comprueba la misma selección, partición, modelo y protocolo.
- **C2.6, cegado:** el diseño exige razón explícita para relaciones con datos cegados. Se filtran planes por usos visibles, réplicas por sus dos corridas, diferencias por sus dos comparaciones y archivos por alcance. Se limitó `semaforo_panel` a vistas aprobadas.

Durante la revisión se encontró que `control.archivo_escenarios` podía mostrar la ruta incluida en `artefacto_id`, aunque el archivo estuviera oculto. Se añadió `control.archivo_visible()` y se usa la misma regla para el archivo y sus enlaces. El barrido P6 cubre las 57 tablas y 12 vistas; antes de abrir la prueba oculta escenario, corridas, búsqueda, archivo, plan y duración exclusiva de prueba para lector y panel.

## Puertas de reconstrucción

| Puerta | Resultado comprobado |
|---|---|
| P0 | `semaforo` coincide con referencia Git: 272 raíces, 0 cambios. |
| P1 | Candidata temporal creada: `semaforo_candidata_20261108053049`. |
| P2 | 140 unidades cargadas; 130 corridas. Las 3 exclusiones tienen decisión aceptada. Sin pendientes, rechazos ni elementos no cargables. |
| P3 | Conciliación igual, cobertura completa y 0 diferencias. |
| P4 | Regeneración desde cero con la misma huella de contenido. |
| P5 | Respaldo restaurado en base temporal; archivo, versión y huella de contenido coinciden. |
| P6 | Pruebas de reglas y barrido completo pasan en base desechable. La versión y huella de reglas coinciden con la candidata. |
| P7 | Se midieron las tres referencias para presentar al PO. |

Lectura final con `semaforo_lectura`: la candidata tiene 130 corridas, 130 filas con métricas, 2615 artefactos, 1 911 000 filas en `vistas.cola_por_segundo`, tres decisiones `accepted_risk` y una carga `completed`.

### Valores de D11

- **Versión del esquema:** `sql-891b34e6c96bf201`
- **Huella de contenido:** `9980fa130cc294af764f764c31320153d58edac0b073cefd5568b4982a33a9f2`
- **Huella de reglas:** `82d7c55d8c12abb4f85899f320740c4aca598c602680a104d4238cdd2774610d`

El respaldo asociado está en `datos/reportes/bd/dev31-c2-20261108/respaldos/sql-891b34e6c96bf201/20261108T053639Z.dump`, con ficha, SHA-256 y resultado de restauración en la misma carpeta.

## Pruebas y controles

- `scripts/check.ps1`: pasó completo el 2026-11-08; 5434 pruebas pasaron y 1 se omitió en Windows.
- Contratos: 43/43.
- Ruff, formato y Pyright: sin errores.
- Esquema generado: 57 tablas, 880 columnas y 117 relaciones; diccionario y SQL al día.
- Antes de SUMO: se midieron 3,16 GiB libres y no había procesos SUMO, Python ni pytest activos. No se cerraron procesos del usuario.
- Las pruebas y consultas de P6 usaron bases `semaforo_pruebas_*`; una base desechable para comparar el catálogo con la candidata se eliminó al terminar.
- P0 fue solo lectura. La inspección final usó `semaforo_lectura`.

## Incidencias corregidas durante C2

1. P2 rechazó inicialmente 28 corridas de diagnóstico histórico porque carecen de protocolo propio en el manifiesto, aunque las métricas sí declaran el protocolo de medición. Se acotó la igualdad al protocolo declarado por la corrida; se conservaron pruebas que rechazan métricas de otro protocolo en búsquedas.
2. Un fixture de respaldo omitía `alcance`, nuevo campo obligatorio; se actualizó con `desconocido`, que conserva el comportamiento oculto.
3. Una prueba de publicación de métricas SUMO no publicaba el archivo de protocolo requerido por el nuevo manifiesto; se corrigió el espacio de prueba.
4. Una prueba de reversión de `bd reconstruir` falló una vez en la puerta completa y pasó tanto aislada como en la puerta repetida. La repetición completa no volvió a mostrar el fallo.
5. El manual de instalación tenía 56 tablas y no señalaba que D8/C0.5 debe crear `semaforo_panel` antes de instalar C2 en otra laptop. Se actualizó y marca esa instalación como pendiente de verificación.

## Pendiente

El PO debe aprobar o rechazar D11 para estos tres valores. Solo después se puede ejecutar `bd reconstruir cambiar` (P8–P9) con reversión. Si P9 coincide, se genera `docs/bd/huellas.json` en un commit separado, según el plan. La base anterior se conserva conforme a D12. C2 no se declara cerrada hasta completar esa secuencia.

**Complejidad:** alta. **Esfuerzo estimado en el plan:** dos sesiones. **Riesgo:** medio. **Modelo sugerido por el plan:** Opus.
