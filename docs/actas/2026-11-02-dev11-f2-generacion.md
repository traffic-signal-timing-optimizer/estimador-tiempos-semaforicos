# Acta 2026-11-02: DEV11 · F2 (generación repetible)

- **Tipo:** fase F2 de DEV11 (HU06). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D5, D6 y D7 de F0.
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/datos/scenarios.py` | `generate_scenarios(spec, case, seed)`: función pura que devuelve los escenarios del conjunto (`GeneratedScenario`: el escenario, su familia, su perturbación, su repetición y los flujos usados). Incluye `flow_for`, `demand_seed_for` y `derivation_digest` |
| `tests/scenario_tools.py` | Ayudas de las pruebas de DEV11: caso, especificación y generación |
| `tests/unit/test_scenarios.py` | 45 pruebas |

## Cómo se genera

- **Perturbaciones.** El flujo de cada movimiento en cada perturbación sale de un generador derivado con SHA-256 de `<semilla>|flujo|<familia>|<perturbación>|<movimiento>`: un valor uniforme entre el mínimo y el máximo, redondeado a 0.1 veh/h y llevado al borde si el redondeo lo saca del rango. Un rango de un solo valor da ese valor.
- **Semillas.** Cada perturbación se repite `seeds` veces con las mismas cifras y otra `demand_seed` (31 bits de `<semilla>|semilla|<familia>|<perturbación>|<repetición>|<intento>`, con intento creciente hasta que no se repita dentro de la familia). Las repeticiones cambian las llegadas, no la demanda.
- **Familia = grupo.** Todos los escenarios de una familia llevan `group_id = family_id`, con el origen, la ventana, los tiempos y las fuentes de la especificación y la frontera del caso. Una especificación `field_derived` da solicitudes `field`.
- **Nombres.** `<familia>-V<nn>-S<nn>`, con al menos dos cifras (más si la cantidad lo pide). La solicitud de cada escenario se llama `<escenario>-REQ`.
- **Independencia.** Cada derivación usa solo el nombre de su familia: agregar, quitar o reordenar otras familias no cambia sus escenarios, ni cambiar los rangos o las perturbaciones de otra.
- **Validación.** Antes de generar se revisa la especificación (SpecInvalidError con todos los problemas) y la semilla maestra (entero de 0 a 2^63 − 1). Cada escenario generado pasa las reglas SCEN-C01 a SCEN-C06.

## Verificación

- **Pruebas:** 45 nuevas. Suite completa: **2442 pasan, 1 se salta** (una prueba que solo corre fuera de Windows). Formato, lint, tipos, contratos y reglas de capas sin observaciones.
- **QA13 en lo que toca a esta fase:** generar dos veces con la misma especificación y semilla da los mismos escenarios, byte a byte; una semilla distinta cambia flujos y semillas pero no los nombres; un rango inválido se rechaza antes de generar (probado en F1 y de nuevo aquí); la familia se conserva (grupo, rangos, composición y frontera).
- **Valores fijos** (regresión entre versiones): con la especificación de ejemplo y la semilla 7, `FAM_PUNTA-V01-S01` tiene `demand_seed` 603748014 y flujos N_S 516.0 y E_W 274.5; `FAM_VALLE-V01-S01` tiene 583759803, 156.5 y 0. Estas cifras salen de la primera ejecución de esta versión: si la derivación cambia, estas pruebas lo avisan, porque ya no se reproducirían conjuntos generados antes.
- **Derivación independiente:** una prueba rehace con `hashlib` y `random` la fórmula escrita arriba y la compara con el generador, así que el texto de las derivaciones queda fijado.
- **Rendimiento:** el conjunto más grande permitido (2000 escenarios) se genera en 0.15 s.
- **Mutaciones:** 37 cambios a propósito. **35 se detectaron en la primera pasada, 1 se colgó y 1 sobrevivió.** La colgada fue invertir la comprobación de semillas repetidas: el programa no termina, así que cuenta como detectada (hubo que detener la prueba a mano; la herramienta de ensayo ahora corta cada pasada a los 5 minutos). La que sobrevivió fue subir en uno el máximo de la semilla maestra (la prueba usaba la misma constante del código): se cerró con valores escritos a mano (9223372036854775807 sí, 9223372036854775808 no) y las dos variantes (de más y de menos) quedan detectadas.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Con 31 bits, dos escenarios de un conjunto de 2000 comparten semilla con probabilidad cercana a 0.1 % | La unicidad se garantiza dentro de cada familia (donde importa para que las repeticiones sean distintas) y no entre familias, para que una familia nunca dependa de las otras. Las semillas iguales entre familias distintas usan flujos y movimientos distintos |
| 2 | Las pruebas de DEV11 no podían importar sus ayudas con `tests.` al correr con `pytest.exe` (como lo hace `scripts/check.ps1`) | Se importan como las demás ayudas (`from scenario_tools import ...`) |
| 3 | La función de derivación estaba privada y la prueba de colisión la necesitaba | Pasó a ser pública (`derivation_digest`) y está documentada como base de todo el azar |
| 4 | Ninguna dependencia nueva; `schemas/` sin cambios | — |

## Límites

- Los movimientos se sortean por separado, sin correlación entre ellos (D13).
- Las llegadas por vehículo todavía no existen: son de F3. Aquí el escenario lleva `demand_artifact` en `null`.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
