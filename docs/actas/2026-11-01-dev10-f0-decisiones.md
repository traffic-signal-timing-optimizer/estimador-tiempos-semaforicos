# Acta 2026-11-01: DEV10 · F0 (decisiones y mapa de verificación)

Written for: el Product Owner y el equipo, para revisar qué se decidió antes de verificar la base sintética y qué huecos aparecieron.

- **Tipo:** fase F0 de DEV10 (HU01–HU04 y HU14; P0, tamaño M). Dependencias: DEV02, DEV04, DEV05, DEV07 y DEV08, cerradas. **No depende de DEV09.**
- **Autorización:** el Product Owner aprobó el plan y pidió ejecutar F0 a F5 seguidas, parando solo para confirmar algo, cambiar de modelo, ante errores que bloquearan o ante cambios de alcance.
- **Datos:** sintéticos. No se toca el `datos/` real.

## Qué pide la documentación

- `02_Requisitos_y_plan.md`, DEV10: «Pruebas unitarias e integración, éxito/fallo de SUMO y repetición fijada; archivar evidencia». Resultado: «Base de ENT1 demostrable». Verificación: «QA01 a QA10 sin fallos críticos».
- `03_Pruebas_y_operacion.md`, «Catálogo y evidencia»: «Cada ejecución de pruebas conserva comando, fecha, entorno, commit, fixture, resultado y log. Los fallos de prueba se clasifican por severidad y se vinculan a tareas. No completar las tablas de resultados del Sprint 1 con "aprobado" hasta ejecutar y archivar evidencia».
- `03_Pruebas_y_operacion.md`, «Criterios del incremento sintético» (los de la base): el caso válido produce artefactos; el inválido se rechaza con motivo; las unidades y la composición coinciden con el cálculo manual; una corrida fallida no publica métricas; dos repeticiones fijadas son equivalentes dentro de tolerancias declaradas. (Los criterios del modelo y de las particiones son de F2 del plan.)
- «La cobertura informa huecos, no sustituye pruebas de comportamiento».

## Mapa de QA01 a QA10 frente a lo que ya existe

Pruebas clave que demuestran el «resultado esperado» de cada caso de la documentación. Esta lista pasa a ser el catálogo ejecutable de F4.

| QA | Qué pide el resultado esperado | Pruebas clave (archivo) | Tarea de origen | Estado |
|---|---|---|---|---|
| QA01 | Válido aceptado; copias rechazadas con campo y motivo | `test_case_rules`: caso de referencia, ID repetido, grupo con tramo inexistente, rechazo con campo y motivo | DEV02 | Cubierto |
| QA02 | Sin doble conteo de solapes; inválidos nunca aceptados | `test_case_rules`: todas las `test_qa02_*` (límites, tick, solapes, ciclo incoherente) y las dos propiedades | DEV02 | Cubierto |
| QA03 | 400 veh/h; proporciones 0.9/0.1; original intacto | `test_counts`: normalización del ejemplo, original sin cambiar un byte, ida y vuelta con lo registrado | DEV04 | Cubierto |
| QA04 | Errores identificables; ninguna aceptación silenciosa | `test_counts`: campo ausente, duplicado, `-1`, clase desconocida, fecha inválida, todos los problemas a la vez, línea de cada error | DEV04 | Cubierto |
| QA05 | Cero conserva 0 y composición nula; faltante no es cero | `test_counts`: cero observado, fila faltante, periodos completos e incompletos; `test_quality`: faltante nunca se compara como cero | DEV04, DEV05 | Cubierto |
| QA06 | Error absoluto 10/5; relativo 0.1/nulo; cobertura exacta | `test_quality::test_qa06_*`, `test_quality_report::test_qa06_*`, `test_coverage` | DEV05 | Cubierto; **verificar en F1** que un mismo caso muestre los tres resultados juntos |
| QA07 | `succeeded` solo si proceso y salidas válidos; originales intactos | `test_runner_sumo`, `test_prepared_run_sumo`, `test_run_inputs_sumo` | DEV00, DEV06, DEV07 | Cubierto |
| QA08 | `failed` con motivo; sin métricas | `test_runner_sumo` (red inválida, salida incoherente, tiempo agotado), `test_runner` (salida truncada o ausente), `test_run_control_sumo` | DEV00, DEV07 | Cubierto |
| QA09 | Iguales dentro de tolerancia; horas fuera | `test_replica`, `test_replica_sumo` | DEV08 | Cubierto |
| QA10 | Rutas, entidades y límites bloqueados; sin shell | `tests/security/*`, `test_tripinfo` (DTD, bomba, gzip), `test_reconcile`, `test_process_edges`, `test_prepared_run_sumo` (metacaracteres) | DEV00, DEV06, DEV07 | Cubierto en la corrida; **hueco en la importación** (ver H1) |

## Huecos y hallazgos de F0

| # | Hallazgo | Dónde se cierra |
|---|---|---|
| H1 | **QA10, importación:** el importador de aforos (`read_counts`) abre el archivo sin comprobar si es un enlace o una unión. El lector de JSON del caso sí lo rechaza. La documentación pide probar «ruta con traversal/symlink» al importar | F2: se rechaza el enlace en el importador y se prueba con una unión (se puede crear en Windows) |
| H2 | **No hay recorrido completo de la base sintética.** Caso → aforos → calidad → programa → entradas → corrida → réplica → verificación solo se prueba por tramos. Lo exige el criterio «las unidades y la composición coinciden con el cálculo manual» | F2: prueba de recorrido por el código, con cálculo manual de los valores |
| H3 | **No hay mapa QA → pruebas ni registro de ejecución archivado** | F4 |
| H4 | **10 pruebas de enlaces simbólicos se saltan** en este equipo (no permite crear enlaces sin privilegios) | Se declaran como «no ejecutadas» en la evidencia; ver D8 |
| H5 | **No hay herramienta de cobertura** instalada | Ver D7 |
| H6 | **Los comandos `case validate` y `data prepare/quality`** del diseño no existen; el recorrido se prueba por el código, no por la línea de comandos | Fuera de DEV10; queda anotado en el cierre |

## Decisiones

| # | Tema | Decisión | Por qué |
|---|---|---|---|
| D1 | Alcance | DEV10 verifica y documenta. Solo cambia código de `src/` si una prueba descubre un defecto real, y cada cambio queda registrado como hallazgo (H1 es el primero) | «Verificar base sintética», no construir |
| D2 | Mapa | `tests/qa_catalog.py` lista, por QA, las pruebas clave (archivo y nombre o prefijo de nombre). `tests/unit/test_qa_catalog.py` comprueba que cada entrada existe, que están QA01 a QA10 del catálogo de la documentación (`matrices/pruebas.csv`) y que ninguno queda vacío | Sin tocar cientos de pruebas con marcas; el mapa no se pudre sin que una prueba falle |
| D3 | Registro de ejecución | `scripts/evidencia.py` corre las pruebas del catálogo y escribe: comando, fecha UTC, entorno (Python, sistema, versión de SUMO, paquetes, memoria), commit (y si hay cambios sin guardar), huella de los datos de prueba (`tests/fixtures`), resultado por QA y por prueba, saltos con su motivo, fallos con severidad y tarea, y el registro completo | Es lo que exige «Catálogo y evidencia» |
| D4 | Dónde se guarda | Resumen **sin rutas de la máquina** en `docs/evidencia/<fecha>_<commit>/` (versionado: el repositorio es público) y el registro completo en `datos/reportes/evidencia/<fecha>_<commit>/` (no versionado) | El resumen se puede revisar; el registro puede tener datos locales |
| D5 | Severidad de un fallo | **Crítico:** falla una prueba clave de un QA (bloquea la puerta de F1). **Mayor:** falla otra prueba, o se salta una prueba clave sin declararlo. **Menor:** aviso sin efecto en un resultado esperado. Cada fallo se vincula a la tarea de origen de la tabla de arriba | La documentación pide clasificar y vincular; no define niveles |
| D6 | Ensayo de sensibilidad | Para cada QA, se rompe a propósito la regla que protege y se comprueba que alguna prueba clave lo detecta. Se ejecuta de a una mutación, sin paralelo, y se archiva su resultado | La cobertura sola no prueba comportamiento |
| D7 | Cobertura | **No se agrega `coverage`.** Este equipo no tiene `uv`, y editar `uv.lock` a mano para una dependencia nueva rompería la verificación de versiones. El ensayo de D6 cumple el papel de encontrar huecos. Queda como mejora para DEV29 (automatizar validación) | Evita una dependencia sin poder bloquearla de forma segura |
| D8 | Enlaces simbólicos | Las 10 pruebas se declaran «no ejecutadas en este equipo» en la evidencia. Si el Product Owner activa el Modo de desarrollador de Windows, se vuelve a correr el registro y quedan cubiertas | No se detiene el trabajo por una acción que depende del Product Owner |
| D9 | Recorrido completo | Prueba en `tests/integration/` que arma, en un espacio temporal, el caso del ejemplo, sus aforos con un conteo de control, el reporte de calidad, el programa derivado, las entradas, dos corridas con SUMO real, la réplica y la revisión del espacio, y compara cada valor con un cálculo manual escrito en la prueba | Criterio «unidades y composición coinciden con cálculo manual» |
| D10 | Tablas del Sprint 1 | DEV10 entrega la evidencia; **no escribe «aprobado»** en ninguna tabla de la tesis | Lo pide la documentación |
| D11 | Recursos | Mutaciones de a una, nunca en paralelo; temporales borrados al cerrar cada fase; el `datos/` real no se toca | Regla vigente |
| D12 | Modelo | Sonnet (esfuerzo alto) para todas las fases | Ninguna fase requiere más; riesgo bajo |

## Fases

| Fase | Qué se hace | Criterio de cierre | Complejidad | Modelo |
|---|---|---|---|---|
| F1 | Verificar QA01 a QA06 línea por línea y cerrar los huecos que aparezcan | Cada resultado esperado tiene una prueba clave que lo afirma con los números de la documentación | Media-baja | Sonnet |
| F2 | Cerrar H1 (enlaces al importar), verificar QA07 a QA10 y el recorrido completo (D9) | El recorrido pasa con valores de cálculo manual; importar un enlace se rechaza | Media | Sonnet |
| F3 | Catálogo (D2) y ensayo de sensibilidad (D6) | Cada QA tiene al menos una mutación detectada; el catálogo se valida solo | Media | Sonnet |
| F4 | Registro de evidencia (D3 a D5) | Una ejecución genera el resumen versionado y el registro completo, con saltos declarados y sin rutas de la máquina | Media | Sonnet |
| F5 | Cierre: informe de la puerta de salida de F1, tabla de HU frente a QA, actas y contexto | Todos los QA en verde o con salvedad declarada; evidencia archivada | Baja-media | Sonnet |

Cada fase cierra con una inspección de lo desarrollado contra la documentación y el caso real.
