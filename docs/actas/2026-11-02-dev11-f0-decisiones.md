# Acta 2026-11-02: DEV11 · F0 (decisiones, sin código)

- **Tipo:** fase F0 de DEV11 (HU06; P0, tamaño M). Dependencias: DEV02, DEV07 y DEV08, cerradas.
- **Autorización:** el Product Owner aprobó el plan (`2026-11-01-planes-dev09-dev11-dev12.md`) y pidió ejecutar todas las fases de DEV11 y después las de DEV12, una tras otra. Los dos cambios de la matriz que pedía el plan (quitar QA25 de DEV11 y poner el comando `scenarios generate` en F4) se aplican como se propuso.
- **Datos:** sintéticos. Ninguna salida se presenta como observada en Lima.
- **Modelo:** Sonnet alcanza (complejidad media, riesgo bajo).

## Qué pide la documentación

«Rangos explícitos, semillas, grupos, origen; materializar llegadas por movimiento y clase sin cambios entre comparadores». Archivo propuesto `datos/scenarios.py`. Verificación QA13 (generar dos veces, rango inválido, familia preservada; evidencia: hashes y reporte). HU06: origen y grupo por escenario, rangos trazables, composición coherente, fronteras fijas, perturbaciones de la familia original. Diseño: `scenarios generate --case --spec --seed`.

## Qué ya existe y se reutiliza

| Pieza | Dónde | Uso |
|---|---|---|
| Modelo de escenario (contrato `scenario` v1.0) y reglas SCEN-S01..S03, SCEN-C01..C06 | `dominio/scenario.py` | Cada escenario generado se valida con `scenario_issues` |
| Cohorte con N exacto y semilla por movimiento | `simulacion/cohort.py` | Las llegadas de cada escenario |
| Publicación atómica, lectura verificada, huellas | `trazabilidad/fs.py`, `verify.py`, `hashing.py`, `ids.py` | Conjunto publicado |
| Revisión del espacio de trabajo | `app/integrity.py` | Se agrega la familia de conjuntos |

`demand_artifact` está en el contrato pero nada lo usa todavía.

## Hallazgos de F0

1. **`datos/escenarios/caso-001/` ya tiene archivos escritos a mano** (`ESC-SINT-001.json`, `rutas.json`, `tipos.json`). Si los conjuntos publicados fueran a `datos/escenarios/<caso>/<fecha>_<huella>/`, `runs verify` marcaría esos archivos como «desconocidos». Por eso los conjuntos van a `derivados/escenarios/` (igual que `derivados/calidad` y `derivados/replicas`).
2. **El esquema de la especificación no puede ser un contrato publicado:** `tests/unit/test_schemas.py` fija exactamente nueve contratos y la documentación los nombra. Sumar un décimo cambia contratos y exige un ADR. Se trata como `rutas.json` y `tipos.json`: un archivo de entrada con `schema_version`, validado por un modelo en el código, sin esquema publicado.
3. **La matriz dice un solo archivo (`datos/scenarios.py`).** Se parte en cuatro por responsabilidad y tamaño (ver D2).

## Decisiones

| # | Decisión |
|---|---|
| D1 | **Alcance como en el plan.** QA25 sale de DEV11 (es de HU12/HU13 y ya se verificó en DEV06 F3); queda solo QA13. El comando `scenarios generate` entra en F4. Cambia la matriz y se anota aquí. |
| D2 | **Dónde vive el código.** `dominio/scenario_spec.py` (modelo y reglas de la especificación, sin leer archivos); `datos/scenarios.py` (generación pura); `datos/scenario_set.py` (conjunto publicado: manifiesto, publicar, leer verificado); `app/scenario_commands.py` (caso de uso); y el grupo `scenarios` en `cli/main.py`. Respeta ADR01: `cli` solo importa `app`; `datos` puede usar `simulacion` y `trazabilidad`. |
| D3 | **Especificación = archivo JSON de entrada** (`schema_version` 1.0.0, campos desconocidos prohibidos, sin NaN). No es contrato publicado (hallazgo 2). |
| D4 | **Contenido de la especificación:** `spec_id`, `case_id`, `case_version`, `origin` (`synthetic` o `field_derived`), `source_ids`, ventana de observación (inicio y fin con zona horaria), `warmup_s`, `measure_s`, `drain_max_s` y una lista de **familias**. Cada familia: `family_id`, `variants` (cuántas perturbaciones), `seeds` (cuántas semillas por perturbación) y una fila por movimiento con el rango `flow_vph {min, max}` y la composición por clase (fija dentro de la familia). Los identificadores propios de la especificación (`spec_id`, `family_id`) solo llevan letras, números, guion bajo y guion (máximo 32), porque dan nombre a archivos. |
| D5 | **Qué es una familia.** Un patrón de demanda (por ejemplo, una hora punta): sus rangos de flujo y su composición. Sus **perturbaciones** son vectores de flujo distintos dentro de esos rangos; sus **semillas** repiten el mismo vector con otras llegadas. Todos los escenarios de la familia llevan `group_id = family_id`. Esto es lo que DEV12 tendrá que mantener junto. |
| D6 | **Generación repetible.** Con la semilla maestra `S` (argumento `--seed`): el flujo de cada movimiento en cada perturbación sale de un generador derivado con SHA-256 de `S|flujo|familia|perturbación|movimiento`; se redondea a 0.1 veh/h y se deja dentro del rango. La `demand_seed` de cada escenario sale de `S|semilla|familia|perturbación|repetición` (31 bits). Nombres: `<familia>-V<nn>-S<nn>`. Misma especificación y misma semilla dan los mismos escenarios, byte a byte. Agregar una familia no cambia los escenarios de las demás. |
| D7 | **Reglas de la especificación** (todas se informan juntas, con regla, campo y motivo, como en el caso): SPEC-S01 contrato y tipos; SPEC-S02 identificadores seguros y sin repetir; SPEC-C01 mismo caso y versión; SPEC-C02 una fila por cada movimiento del caso en cada familia, sin repetidos ni desconocidos (una fila ausente no es un cero); SPEC-C03 rango con `min ≤ max` y dentro del dominio de flujos del movimiento; SPEC-C04 composición con clases del caso, proporciones entre 0 y 1 y suma 1 (solo puede faltar si el rango es 0 a 0); SPEC-C05 cantidades dentro de los máximos (200 perturbaciones, 100 semillas, 2000 escenarios en total). Además, **cada escenario generado se valida con las reglas SCEN-C01..C06** (ventana, múltiplos del tick, frontera del caso). Un rango inválido se rechaza y no se publica nada. |
| D8 | **Mismas llegadas para todos los comparadores.** Cada escenario lleva su archivo de llegadas `demanda/<escenario>.csv` (la cohorte de DEV06 en texto fijo: vehículo, movimiento, clase, salida, si es de la cohorte) y `demand_artifact` apunta a él con su huella. Quien lo lea ve siempre la misma lista; un cambio se detecta por la huella. No se modifica `simulacion/cohort.py`. |
| D9 | **Conjunto publicado** en `derivados/escenarios/<caso>/<fecha>_<huella8>/` con `spec.json` (copia fiel), `escenarios/<id>.json`, `demanda/<id>.csv` y `manifiesto.json`. Se publica con `publish_files` (carpeta temporal y renombrado, nunca sobrescribe). La `<huella8>` es el comienzo de la huella de contenido (todos los archivos menos el manifiesto), así que **dos generaciones iguales tienen la misma huella aunque sus carpetas lleven fecha distinta**. |
| D10 | **Manifiesto del conjunto:** versión, caso, versión y huella del caso, `spec_id` y huella de la especificación, semilla maestra, origen, fecha, huella de contenido, resumen por familia (rangos, perturbaciones, semillas) y, por escenario, familia, perturbación, repetición, `demand_seed` y los flujos usados (rangos trazables). Lista de archivos con huella. |
| D11 | **Lectura verificada** (`read_scenario_set`): carpeta con exactamente los archivos del manifiesto, huellas correctas, cada escenario cumple su contrato, coincide con su entrada del manifiesto y su archivo de llegadas coincide con su `demand_artifact`. `runs verify` agrega la familia «escenarios» (por caso). |
| D12 | **Comando** `scenarios generate --case --spec --seed [--workspace] [--debug]`. Códigos: 0 publicado; 2 especificación o caso inválido o ilegible (no se publica nada); 5 enlace, huella distinta o carpeta ya existente; 1 interno. La salida estándar lleva solo el JSON (rutas relativas); la persona ve en la salida de error todos los problemas. |
| D13 | **Límites que se declaran:** la composición no varía dentro de una familia (varía entre familias); los flujos de los movimientos se sortean por separado (sin correlación entre ellos); `field_derived` no se enlaza con datos reales (todavía no hay); un escenario con más de 200 000 vehículos se rechaza (límite de la cohorte). |
| D14 | **Pruebas:** unitarias de cada regla y de la generación (incluida la repetibilidad y la independencia entre familias), del conjunto publicado (alteraciones, enlaces, sobrantes), de la CLI y de un recorrido completo; de seguridad con especificaciones hostiles; y ensayo de mutaciones en cada fase. |
| D15 | **Modelo:** Sonnet. Sin cambios de modelo previstos. |

## Fases (sin cambios respecto del plan)

| Fase | Qué se hace |
|---|---|
| F1 | `dominio/scenario_spec.py`: modelo, reglas SPEC y rangos inválidos rechazados |
| F2 | `datos/scenarios.py`: generación repetible, perturbaciones dentro de la familia, origen y grupo |
| F3 | Archivos de llegadas iguales para todos (reutiliza la cohorte) |
| F4 | `datos/scenario_set.py`, comando, `runs verify`, README |
| F5 | Cierre: acta, inspección contra la documentación y el caso real, bitácora |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
