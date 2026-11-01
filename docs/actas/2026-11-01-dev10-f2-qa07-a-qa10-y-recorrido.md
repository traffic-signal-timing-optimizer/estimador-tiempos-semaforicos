# Acta 2026-11-01: DEV10 · F2 (QA07 a QA10 y recorrido completo de la base sintética)

Written for: el Product Owner y el equipo, para revisar qué se corrigió al importar aforos y cómo se comprobó el recorrido completo con SUMO.

- **Tipo:** fase F2 de DEV10 (HU01–HU04 y HU14). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D1 (solo se cambia `src/` si hay un defecto real), D8 (enlaces simbólicos) y D9 (recorrido completo) de F0.
- **Datos:** sintéticos.

## Verificación de QA07 a QA10

| QA | Preparación del catálogo | Resultado esperado | Prueba que lo afirma | Conclusión |
|---|---|---|---|---|
| QA07 | SUMO fijado y red recibida o ejecutable | `succeeded` solo si proceso y salidas son válidos; originales intactos | `test_runner_sumo` (corrida del ejemplo, versión de SUMO `1.27.1` registrada), `test_prepared_run_sumo` (la corrida se completa, hasta el fin del manifiesto, huella de cada entrada, entradas originales intactas y de solo lectura), `test_run_inputs_sumo` | Cubierto |
| QA08 | Red inválida y salida XML truncada | `failed` con motivo; sin métricas | `test_runner_sumo` (caso inválido, salidas incoherentes, tiempo agotado), `test_runner` (salida truncada, vacía o ausente), `test_run_control_sumo` (cancelación y topes) | Cubierto |
| QA09 | Dos ejecuciones con los mismos insumos y semilla | Iguales dentro de tolerancia; horas fuera | `test_replica`, `test_replica_sumo` (DEV08) | Cubierto |
| QA10 | Ruta con recorrido o enlace, XML con DTD, gzip excesivo, nombre con metacaracteres | Rutas, entidades y límites bloqueados; sin shell | Rutas: `test_paths`, `test_run_inputs`, `test_retry`, `test_dev07_run` (`retry_of` hostil). DTD y entidades: `test_tripinfo`, `test_reconcile`, `test_dev06_inputs`. gzip: `test_inventory`, `test_tripinfo`, `test_bounded_read`. Metacaracteres: `test_prepared_run_sumo`, `test_dev07_run`. Enlaces: `test_run_inputs`, `test_reconcile`, `test_process_edges`, `test_case_file`, **y ahora el importador de aforos** | Cubierto, con la salvedad de D8 |

## Hallazgo H1 corregido (QA10 al importar)

El importador de aforos (`read_counts`) abría el archivo sin comprobar si era un enlace o una unión. El lector del caso sí lo rechazaba, y la documentación pide probar «ruta con traversal/symlink» al importar. **Corregido:** `datos/importer.py` rechaza un archivo que sea un enlace simbólico o una unión, con el mensaje «el archivo es un enlace o una unión y no se sigue» (un solo problema, sin fila ni campo). Solo se comprueba el archivo en sí: si una carpeta intermedia es una unión, el archivo se lee normal, porque no cambia a dónde apunta la ruta que el analista dio.

Pruebas: enlace simbólico real (se salta en este equipo, ver D8), dos pruebas que simulan que el sistema informa un enlace o una unión, y una con una unión real a una carpeta que contiene el archivo (se lee bien).

## Recorrido completo de la base sintética (D9)

`tests/integration/test_base_sintetica_sumo.py`: caso → aforos → calidad → programa → entradas → dos corridas con SUMO real → réplica → revisión de todo el espacio. **Cada valor se compara con un cálculo hecho a mano** que está escrito en la prueba:

| Paso | Cálculo a mano | Lo que comprueba la prueba |
|---|---|---|
| Aforos | N_S: (90 + 10) / 900 s × 3600 = **400 veh/h**, 0.9 y 0.1; E_W: 50 / 900 × 3600 = **200 veh/h**, 1.0 y 0.0 | Los flujos y la composición normalizados son exactamente esos |
| Escenario | 400 × 0.25 h = 100 vehículos y 200 × 0.25 h = 50: **150** de cohorte | El escenario pide los mismos flujos que los aforos |
| Calidad | Control con 100 autos en N_S: error absoluto 10, relativo 10/100 = **0.1**; el resto coincide. Cobertura de 08:00 a 08:15: 900/900 = **1** | Esos números; el reporte se publica y se lee verificado |
| Entradas | Escenario y semilla de demanda 100 | El manifiesto las registra |
| Corridas | Se piden 150: 90 autos + 10 buses en N_S y 50 autos en E_W | Terminados + sin terminar + sin entrar = 150, por movimiento y clase. E_W con buses pide 0 y no genera ningún vehículo |
| Réplica | Mismas entradas y semilla | `equivalent`, sin motivos |
| Revisión | — | La cadena de la corrida está completa y el espacio queda íntegro, con corridas, programas, entradas, calidad y réplicas |

## Verificación

**Pruebas.** 4 nuevas (3 del importador, 1 con SUMO real; más 1 que se salta por enlaces). Suite completa: **1873 pasan, 12 saltadas** (las 10 de antes, la nueva de enlace simbólico real y la de otro sistema). Formato, lint, tipos y contratos sin observaciones.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | **H1:** el importador seguía enlaces | Corregido y probado (arriba) |
| 2 | Mi primera versión del recorrido esperaba una fila de E_W con buses en la conciliación; no existe porque pide 0 vehículos | Era un error de la expectativa, no del código: se corrigió la prueba y se documentó |
| 3 | Todo lo demás del recorrido pasó a la primera con valores hechos a mano | Confirma que la base sintética funciona de punta a punta |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
