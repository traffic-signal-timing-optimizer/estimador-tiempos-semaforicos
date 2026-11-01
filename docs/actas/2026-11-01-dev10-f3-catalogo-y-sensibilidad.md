# Acta 2026-11-01: DEV10 · F3 (catálogo ejecutable y ensayo de sensibilidad)

Written for: el Product Owner y el equipo, para revisar cómo se demuestra que las pruebas de QA01 a QA10 de verdad protegen las reglas que dicen proteger.

- **Tipo:** fase F3 de DEV10 (HU01–HU04 y HU14). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D2 (mapa de pruebas) y D6 (ensayo de sensibilidad) de F0.
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `tests/qa_catalog.py` | El catálogo: para cada QA, su tipo, la tarea de origen, un resumen del resultado esperado y las **pruebas clave** que lo demuestran (por archivo o por prefijo de nombre). `resolve` convierte cada entrada en los identificadores de pytest |
| `tests/unit/test_qa_catalog.py` | Vigila el catálogo: están QA01 a QA10 y nada más, el tipo de cada uno es el de `matrices/pruebas.csv`, ninguna entrada se repite y **toda entrada corresponde a al menos una prueba que existe** (si alguien renombra o borra una prueba clave, esta prueba falla) |
| `scripts/sensibilidad.py` | El ensayo: rompe a propósito una regla a la vez, corre solo las pruebas clave de ese QA y dice si el cambio se **detectó** o **sobrevivió**. Restaura el código siempre; se niega a correr si el código a modificar tiene cambios sin guardar |

## El ensayo de sensibilidad

32 cambios a propósito, de 2 a 6 por QA, sobre las reglas que cada caso protege. Primera pasada, con el catálogo recién armado:

| QA | Cambios | Detectados | Sobrevivieron |
|---|---|---|---|
| QA01 | 3 | 2 | 1 (tramo repetido en un grupo) |
| QA02 | 2 | 2 | — |
| QA03 | 3 | 3 | — |
| QA04 | 4 | 4 | — |
| QA05 | 2 | 2 | — |
| QA06 | 4 | 4 | — |
| QA07 | 2 | 0 | 2 (error de SUMO tomado por éxito; viajes que no coinciden con los insertados) |
| QA08 | 3 | 1 | 2 (insertados mayores que cargados; sin terminar distinto de en la red) |
| QA09 | 3 | 2 | 1 (estructura XML distinta tomada por igual) |
| QA10 | 6 | 5 | 1 (la red admite DTD) |
| **Total** | **32** | **25** | **7** |

**Los 7 que sobrevivieron no eran huecos del producto, sino de la elección de pruebas clave:** las pruebas que los detectan ya existían, pero no estaban en el catálogo del QA. Por ejemplo, «QA07: éxito solo si el proceso y las salidas son válidos» tenía como pruebas clave solo las del caso exitoso, y las que prueban que un error de SUMO o una salida incoherente fallan estaban bajo QA08. Se agregaron al catálogo 10 pruebas clave:

| QA | Pruebas agregadas |
|---|---|
| QA01 | Grupo con un tramo repetido |
| QA07 | Caso inválido que falla con motivo; salidas incoherentes inválidas |
| QA08 | Salidas incoherentes inválidas |
| QA09 | Estructura distinta; salida que solo tiene una corrida; entradas o semilla distintas |
| QA10 | DTD y entidades en la red, las rutas y la configuración (3 archivos de prueba) |

**Repetido para los cinco QA con sobrevivientes: 17 de 17 detectados.** En total, los 32 cambios quedan detectados por las pruebas clave de su QA: ninguna regla ensayada está sin protección.

## Verificación

**Pruebas.** 25 nuevas (todas del catálogo). Suite completa: **1898 pasan, 12 saltadas**. Formato, lint, tipos y contratos sin observaciones.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | **Ningún hueco de producto** salió del ensayo: las 7 supervivencias eran pruebas que existían pero no estaban en el catálogo | Catálogo ampliado y ensayo repetido |
| 2 | Un nombre de función del catálogo (`list_tests`) coincidía con el prefijo que pytest usa para encontrar pruebas | Se renombró para que pytest no lo tome por una prueba |
| 3 | El catálogo declara las pruebas que **se saltan en este equipo** (enlaces simbólicos): siguen listadas como clave de QA10, pero la evidencia las contará como «no ejecutadas» (F4) | Declarado |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
