# Acta 2026-11-02: DEV11 · F1 (especificación con rangos)

- **Tipo:** fase F1 de DEV11 (HU06). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D3, D4 y D7 de F0.
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/dominio/scenario_spec.py` | Modelo estricto de la especificación (`ScenarioSpec`, `Family`, `FamilyRow`, `FlowRange`), `parse_spec`, `accept_spec`, `spec_issues`, `scenario_count`, `SpecInvalidError` y los máximos |
| `src/semaforo/dominio/case.py` (una línea) | Registra la regla SPEC-S02 para los identificadores seguros, de modo que el mensaje salga en español |
| `tests/fixtures/scenario_spec.json` | Especificación de ejemplo para el caso de pruebas: dos familias, una con rango de 0 a 0 sin composición |
| `tests/unit/test_scenario_spec.py` | 133 pruebas |
| `tests/unit/test_fixtures.py` | El ejemplo nuevo se agrega a la lista de archivos permitidos |

## Reglas

| Regla | Qué comprueba |
|---|---|
| SPEC-S01 | Contrato v1.0 completo, sin campos desconocidos, tipos exactos, sin NaN ni infinito |
| SPEC-S02 | Identificadores sin espacios en los extremos ni caracteres de control o invisibles; `spec_id` y `family_id` solo con letras, números, guion bajo y guion (hasta 32, sin empezar por guion); familias sin repetir |
| SPEC-S03 | `case_version` con formato `MAYOR.MENOR.PARCHE` |
| SPEC-C01 | Mismo caso y versión |
| SPEC-C02 | Una fila por cada movimiento del caso en cada familia, sin repetidos ni desconocidos (una fila ausente no es un cero) |
| SPEC-C03 | `min <= max` y dentro del dominio de flujos del movimiento |
| SPEC-C04 | Composición con clases del caso, proporciones entre 0 y 1 que suman 1; solo puede faltar si el rango es 0 a 0 |
| SPEC-C05 | Máximos: 200 perturbaciones y 100 semillas por familia, 2000 escenarios en total |
| SCEN-C05 | Ventana de observación y múltiplos del tick: es la misma regla del escenario, armada con un escenario de prueba y filtrada |

Todos los problemas se informan juntos, cada uno con su regla, su campo y su motivo, en un orden fijo (caso, familias repetidas, cada familia, tamaños y tiempos). Se cortan en 100 con una nota de cuántos faltan. El error lleva código INPUT_SCHEMA (salida 2 en la CLI).

Ejemplo de rechazo: un rango de 600 a 400 dice «el mínimo 600 es mayor que el máximo 400»; uno de 400 a 1300 en un movimiento cuyo dominio llega a 1200 dice «el rango de 400 a 1300 veh/h sale del dominio del movimiento «N_S»: de 0 a 1200 veh/h».

## Verificación

- **Pruebas:** 133 nuevas. Suite completa: **2397 pasan, 1 se salta** (una prueba que solo corre fuera de Windows). Formato, lint, tipos, contratos y reglas de capas sin observaciones.
- **Mutaciones:** 36 cambios a propósito en el modelo y en las reglas (límites y bordes, tolerancias, banderas invertidas, prefijos, mensajes). **35 se detectaron en la primera pasada y 1 no**: que el máximo de perturbaciones (200) se acepte. Se cerró con una prueba y los 36 quedan detectados.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Los identificadores del caso admiten cualquier carácter visible; los de la especificación que dan nombre a archivos no | Regla SPEC-S02 más estricta solo para `spec_id` y `family_id` |
| 2 | Una proporción fuera de 0 a 1 casi siempre arrastra a la clase complementaria (la que falta para sumar 1) fuera de 0 a 1 | Se informan las dos, cada una con su campo; una prueba lo fija |
| 3 | La regla de tiempos del escenario (SCEN-C05) no era reutilizable sin construir un escenario | Se arma un escenario de prueba y se conserva solo SCEN-C05, sin copiar la regla ni tocar `dominio/scenario.py` |
| 4 | Una prueba existente (`test_fixture_files_exist`) lista los archivos de ejemplo permitidos | El ejemplo nuevo se agregó a su lista |
| 5 | Ninguna dependencia nueva; `schemas/` sin cambios (siguen nueve contratos) | — |

## Límites

- La composición de una familia no varía dentro de ella (D13).
- Los tiempos se validan aquí con la misma regla del escenario; que cada escenario generado sea válido se vuelve a comprobar en F2.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
