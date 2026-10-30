# Acta 2026-10-29: DEV02 · F2 (reglas de consistencia, QA01 y QA02)

- **Tipo:** registro de fase del plan de DEV02 (HU01)
- **Autorización:** el Product Owner autorizó F2 («ejecuta f2»).
- **Siguiente fase:** F3 (`CaseReport`, `case_sha256`, reglas de red CASE-N01 y N02 y prueba del contrato), a la espera de su autorización.

## Qué se hizo

`src/semaforo/dominio/case_rules.py` implementa las 13 reglas de consistencia que fijó el acta de F0. Son puras (sin archivos ni procesos, ADR01). Cada regla revisa el caso entero y devuelve todos sus problemas con campo y motivo en español. Se evalúan siempre en el mismo orden (`RULES`).

| Regla | Título | Gravedad | Qué comprueba |
|---|---|---|---|
| CASE-C01 | Identificadores únicos | error | clases de vehículo, movimientos, slots y grupos; indica dónde estaba el primero |
| CASE-C02 | Rangos con mínimo no mayor que máximo | error | ciclo y dominio de flujo de cada movimiento |
| CASE-C03 | Límites de cada slot | error | mínimo ≤ máximo; en un slot fijo, mínimo = máximo |
| CASE-C04 | Al menos un slot variable | error | sin slots variables no habría nada que estimar |
| CASE-C05 | Límites alineados con el tick | error | límites de slots, del ciclo y de los grupos son múltiplos de `tick_s` |
| CASE-C06 | Un estado por semáforo en cada slot | error | ni uno de menos ni uno repetido; el largo de cada estado es el de la primera aparición |
| CASE-C07 | Slots seguidos con estados distintos | **aviso** | dos slots consecutivos, o el último con el primero, con los mismos estados |
| CASE-C08 | Semáforo e índices de enlace de los movimientos | error | el semáforo existe en los slots; índices ≥ 0, sin repetir y dentro del largo del estado |
| CASE-C09 | Slots y ventana de cada grupo de verde | error | los slots existen y no se repiten; mínimo ≤ máximo; la ventana se alcanza con las duraciones de sus slots |
| CASE-C10 | Ciclo factible | error | el rango del ciclo se cruza con lo que suman los slots |
| CASE-C11 | Verde en los slots de cada grupo | error | cada slot del grupo muestra `g` o `G` en algún enlace |
| CASE-C12 | Evidencia de los grupos peatonales | error | si hay grupos peatonales, `restrictions_evidence` tiene al menos un texto no vacío |
| CASE-C13 | Origen y estado coherentes | error | un caso de campo declara su red y no es `synthetic_fixture`; uno sintético no es `calibrated` ni `validated` |

Funciones públicas:
- `evaluate_rules(case)`: el resultado de cada regla (`passed`, `warning` o `failed`) con sus problemas. F3 la usa para el reporte.
- `accept_case(data)`: valida la estructura (CASE-S01 a S03) y luego la consistencia. Lanza `CaseInvalidError` con todos los problemas de las reglas de error, hasta 100. Un aviso no rechaza el caso.
- `cycle_window(case)` y `group_window(case, i)`: el ciclo factible y el verde alcanzable de un grupo. Cada slot cuenta una sola vez, así que los grupos que se solapan no inflan el ciclo. F3 las usa para los límites efectivos del reporte.

Cambios en lo que ya existía:
- `read_case` (F1) ahora aplica también las reglas de consistencia, no solo la estructura.
- Los problemas recortados usan `cap_issues`, compartido por estructura y consistencia. El último problema lleva la regla del primero omitido y concuerda en singular («y 1 problema más») y plural.

## Decisiones que tomé (no estaban en el acta de F0)

| Tema | Decisión | Cómo relajarla |
|---|---|---|
| Causa única, un solo problema | Una regla no se apoya en datos que otra ya declaró rotos: C09 se omite si el grupo usa un slot inexistente, repetido o con límites invertidos (C03), o si su propia ventana está invertida; C10 se omite si el rango del ciclo (C02) o algún slot (C03) está invertido | quitar la guarda en `_group_slots` o `_feasible_cycle` |
| Ids de slot repetidos | Las demás reglas usan el primer slot con ese ID, así que un ID repetido da un solo problema (C01) y no una cascada | — |
| C08 | Dos movimientos no pueden compartir el mismo enlace de un semáforo. El acta decía «no se repiten» sin precisar; elegí la lectura más estricta | borrar la rama `elif key in owner` |
| C11 | «Muestra verde» significa `g` o `G` en cualquier enlace del slot, porque el contrato no enlaza los grupos con movimientos concretos | — |
| Tolerancias | 1e-9 s para comparar duraciones y 1e-8 ticks (relativo, para valores grandes) para la alineación con el tick, como el código de referencia | constantes `EPSILON` y `TICK_EPSILON` |
| C07 con dos slots | Se informa una sola vez; el cierre del ciclo solo se compara con tres slots o más | — |

**Límite de lo probado:** las reglas se probaron con el caso de ejemplo y con casos generados. Todavía no existe un archivo de caso de Los Frutales (se crea desde DEV03), así que las decisiones C08 y C11 podrían necesitar ajuste con datos reales.

## QA01 y QA02

| Pedido del catálogo | Cómo se cubre |
|---|---|
| QA01: caso válido aceptado | el caso de ejemplo pasa las 13 reglas y `accept_case` lo acepta; un caso mínimo armado por las pruebas también |
| QA01: copias con ID repetido rechazadas con campo y motivo | cuatro pruebas, una por sección (clases, movimientos, slots, grupos): campo `slots[2].id` y motivo «ya está en `slots[0].id`» |
| QA01: copias con referencia inexistente rechazadas | grupo que usa un slot inexistente → CASE-C09, campo `green_groups[0].slot_ids[0]`; movimiento con un semáforo ausente → CASE-C08 |
| QA02: límites y tick con casos frontera | múltiplos del tick con ruido de coma flotante (seis ticks, hasta 400 pasos, con `hypothesis`); medio tick desalineado; cada límite alineado por separado; valor enorme con tick fino; slot fijo con límites iguales, con 1e-12 de diferencia y distintos |
| QA02: ciclo incoherente | ciclo [10, 20] contra slots que suman 28 a 108; fronteras exactas 28, 27, 108 y 109; ciclo invertido, que solo informa C02 |
| QA02: solapes sin doble conteo | tres grupos que comparten slots con ciclo [15, 30]: la ventana del ciclo sale 15 a 30, no la suma de los grupos; un ciclo de 30 a 80 sobre dos slots que suman 10 a 20 se rechaza, aunque dos grupos que comparten esos slots sumarían hasta 40 si se contaran dos veces; un slot repetido en un grupo cuenta una vez |
| QA02: inválidos nunca aceptados | propiedades con `hypothesis`: el ciclo es factible si y solo si los rangos se cruzan, y un grupo es alcanzable si y solo si se cruzan; en ambos, `accept_case` acepta o rechaza según corresponde |

**Alcance de QA02 en DEV02:** el catálogo dice «reconstruir». Reconstruir el ciclo y los verdes a partir de las duraciones de un plan es la reconstrucción de DEV13 (reglas temporales). En DEV02 se comprueban los límites del caso y se deja el cálculo de ventanas que DEV13 reutilizará.

## Pruebas

- `tests/unit/test_case_rules.py`: 100 pruebas (cada una de las 13 reglas, QA01, QA02, ejemplos de frontera, un caso de 1 500 slots, 20 000 ID repetidos y las propiedades).
- `tests/unit/test_case_file.py`: 1 prueba más (el archivo con la consistencia aplicada).
- **Mutaciones:** 47 errores introducidos a propósito en `case_rules.py` y `case.py` (tolerancias, comparaciones, ramas quitadas, campos cambiados, el orden de las reglas, el recorte de problemas). Las pruebas detectaron los 47. En la primera ronda sobrevivió uno, el de la tolerancia relativa del tick: no había una prueba que lo necesitara, y se agregó la de 428 038 701,2 con tick 0,1, que se desvía 4,8e-7 de un entero por coma flotante.
- Mientras se escribían las pruebas aparecieron dos cascadas que producían problemas de más con una sola causa (un ID de slot repetido y un slot con límites invertidos). Se resolvieron con las decisiones de la tabla de arriba.

## Verificación

- `scripts/check.ps1` pasa: ruff, formato, pyright estricto, 843 pruebas pasan y 2 se saltan de forma declarada (enlaces simbólicos sin privilegios), contratos de referencia (43 comprobaciones), ningún código ignorado por git y ruff alineado.
- ADR01 se cumple (`tests/unit/test_arquitectura.py`): `dominio` no importa ningún otro módulo.
- `schemas/case.schema.json` y `tools/contracts/` no se tocaron.
- Sin cambios en el paquete de documentación del investigador (`documentacion/`).

## Pendiente

- **F3:** `CaseReport` con `case_sha256`, estado y límites efectivos (con `cycle_window` y `group_window`), reglas de red CASE-N01 y N02 (solo si el caso declara su red) y la prueba de que el modelo sigue `case.schema.json`.
- **F4:** cierre de DEV02.
- **Aviso al Product Owner:** el repositorio privado del escenario SUMO sigue sin crearse y no hace falta todavía. Se necesitará antes de DEV03.
