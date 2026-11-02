# Acta 2026-11-02: DEV13 · F0 (decisiones, sin código)

- **Tipo:** fase F0 de DEV13 (HU11; P0, tamaño L). Dependencia: DEV02, cerrada.
- **Autorización:** el Product Owner aprobó el plan (`2026-11-02-plan-dev13.md`), incluida la aclaración del verificador previo al entrenamiento, y pidió avanzar **fase por fase** por la complejidad alta: solo F0 ahora.
- **Modelo:** Opus, como recomendaba el plan.
- **Datos:** sintéticos. El caso-001 real solo se leyó.

## Qué pide la documentación

- **Matriz:** «Reconstruir ciclo y verdes desde slots; validar límites, solapes y ventanas; corrección acotada idéntica en todos los flujos». Archivos `dominio/timing.py` y `dominio/feasibility.py`. Resultado: validador y corrector deterministas. Verificación: QA02 y QA22 con casos de frontera.
- **HU11:** todo plan válido cumple las reglas; corrección determinista y acotada; registro del original y del final; los fallos admisibles cuentan en la cobertura.
- **Diseño:** las duraciones variables `d` las da el modelo; el ciclo es la suma de todos los slots, cada uno una vez; el verde de un grupo es la suma de sus slots; las ventanas discontinuas se conservan con su total. Restricciones: límites por slot, ciclo, verdes de grupo, fijos, secuencia y estados.
- **Corrección (ADR06, propuesta):** rechazar NaN, infinito, dimensión o versión incompatibles; recortar a los límites del slot; ajustar el ciclo «en orden canónico» sin pasar mínimos ni máximos; trabajar en ticks enteros; reconstruir y comprobar todo; si algo falla, `rejected` con códigos. No hay búsqueda ni simulación. Una corrección distinta exige un ADR.

## Qué ya existe y se reutiliza

| Pieza | Dónde | Uso en DEV13 |
|---|---|---|
| Modelo del caso | `dominio/case.py` | Slots, grupos, tick, rango del ciclo |
| Reglas CASE-C01 a C13, `cycle_window`, `group_window` | `dominio/case_rules.py` | El caso debe pasarlas antes de corregir; la ventana del ciclo da los límites del ajuste |
| Reglas PLAN-01 a PLAN-05 | `dominio/case_plan.py` (DEV03) | El validador las reutiliza; no se duplican |
| Estados y plan del contrato de respuesta | `schemas/response.schema.json` | Mismos nombres de estado y del plan (duraciones, ciclo, verdes); el contrato no cambia |

## Comprobación previa con el caso real (prototipo desechable, fuera del proyecto)

Con `datos/casos/caso-001/case.json` y un prototipo en la carpeta temporal (no forma parte del código):

| Comprobación | Resultado |
|---|---|
| Programa actual (línea base, ciclo 206 s) con PLAN-01 a PLAN-05 | Sin problemas: es un plan de referencia factible (sirve para el verificador previo al entrenamiento, D15) |
| Ventana del ciclo | 120 a 240 s; los 5 slots fijos suman 24 s |
| Plan fuera de límites (t1 120, t3 10, t5 50.4, t7 40) | Queda t1 110, t3 15, t5 50, t7 30; ciclo 229 s; cumple todo |
| Medio tick (t1 82.5, t3 45.5, t5 44.5, t7 10.49) | t1 83, t3 46, t5 45, t7 10 (a medio tick, hacia arriba) |
| Valores enormes (1e308 y −1e308) | Se recortan sin desbordar: t1 110, t3 15 |
| 20 000 planes al azar, con los dos repartos de D6 | 0 rechazados; corregir dos veces da siempre lo mismo |
| Límites de los grupos frente a la suma de sus slots | Iguales en los 5 grupos (ver hallazgo 1) |
| `0.35 / 0.1` con decimales binarios | 3.4999999999999996 en lugar de 3.5 (ver D8) |

## Decisiones

| # | Decisión |
|---|---|
| D1 | **Alcance como en el plan.** QA02 completo (incluida la parte de «reconstruir» que DEV02 dejó para aquí) y QA22 completo en lo que es puro; la parte de QA22 «con SUMO inaccesible» es de DEV18. Sin comandos de línea ni archivos publicados: el comando de consulta es de DEV18. |
| D2 | **Dónde vive el código** (puro, sin archivos ni procesos, ADR01). `dominio/timing.py` (F1): reconstruir ciclo, verdes y ventanas. `dominio/feasibility.py` (F2 y F3): reglas preparadas del caso, validador, corrector y cobertura. `dominio/case_plan.py` se mantiene y se reutiliza. |
| D3 | **Reglas preparadas del caso.** Antes de validar o corregir se preparan las reglas una vez por caso. El caso tiene que pasar todas las reglas de error CASE-C01 a C13; si no, `CaseInvalidError` y no se corrige nada. Los avisos (C07) no impiden. Así la secuencia y los estados (C06, C07, C11) quedan garantizados: un plan solo trae duraciones y no puede cambiarlos. Prepararlas una vez sirve también a DEV14, que corregirá miles de planes. |
| D4 | **Qué recibe cada función.** El corrector recibe solo las duraciones **variables** (por ID de slot, como `original_variable_durations_s` del contrato), con el caso y la versión a los que dicen pertenecer; los fijos salen del caso. El validador recibe un plan **completo** (todos los slots), porque los comparadores (plan observado, Webster) y la búsqueda dan planes completos: un fijo distinto de su valor es un incumplimiento. |
| D5 | **Estados** (los del contrato): `invalid_input` (entrada rota, nada se corrige); `accepted` (el original ya cumple todo); `corrected` (se cambió y el resultado cumple todo); `rejected` (después de corregir alguna regla sigue fallando; se registra con sus reglas y no hay plan admisible). `out_of_domain` y `failed` los decide la consulta (DEV18). |
| D6 | **Ajuste del ciclo: pendiente de la elección del Product Owner** (ver la sección siguiente). Las dos lecturas cumplen el diseño, son deterministas y acotadas; cambia a quién se le quita o se le da el tiempo. |
| D7 | **Orden de los pasos.** (1) Entrada: exactamente los slots variables, números finitos (no booleanos ni textos), caso y versión iguales; si no, `invalid_input`. (2) Recortar cada duración a los límites de su slot, en segundos (así 1e308 no desborda). (3) Pasar a ticks enteros: al más cercano; a medio tick, hacia arriba. (4) Ajustar el ciclo en ticks enteros a la ventana del ciclo (rango del caso cruzado con lo que pueden sumar los slots). (5) Reconstruir y comprobar todas las reglas. Recortar y redondear en cualquier orden da lo mismo porque los límites ya son múltiplos del tick (CASE-C05); el ajuste del diseño se hace una sola vez, en ticks. |
| D8 | **Aritmética exacta.** Duraciones y tick se convierten a fracciones exactas de lo escrito (como en DEV12) y se trabaja en ticks enteros. Con decimales binarios, 0.35 s con tick de 0.1 daría 3.4999… ticks y se redondearía mal. Los segundos finales salen de `ticks × tick` exacto. |
| D9 | **«Acotada».** Cada duración final queda dentro de los límites de su slot, el ciclo dentro de su ventana y el número de pasos tiene un tope fijo. Se registra cuánto cambió cada slot para que DEV25 revise las correcciones. No se agrega un tope de cambio que el diseño no tiene: eso sería redefinir la admisibilidad. |
| D10 | **«Idéntica en todos los flujos».** El corrector no recibe flujos: la corrección depende solo del plan y del caso. Se prueba con la misma entrada y flujos distintos, y con escenarios de dos familias. |
| D11 | **Qué no se arregla.** Si después de recortar y ajustar el ciclo el verde de un grupo sigue fuera de sus límites (restricciones cruzadas), el plan es `rejected` con PLAN-05. No se busca otra solución (ADR06). Esa limitación se muestra con casos sintéticos y en la cobertura. |
| D12 | **Ventanas.** Una ventana es una racha de slots seguidos del grupo en el orden de la secuencia. Si el grupo tiene el último y el primer slot, es una sola ventana que cruza el fin del ciclo. Cada ventana lleva sus slots, su inicio en el ciclo y su duración. El total del grupo cuenta cada slot una vez y es lo que se compara con sus límites; el caso no define límites por ventana y no se inventan. Los grupos peatonales siguen las mismas reglas (caso-001 no tiene, DEC03). |
| D13 | **Validador.** Devuelve cada regla como cumplida, violada u omitida, con todos sus problemas: PLAN-01 a PLAN-05 y dos reglas nuevas del corrector, TIME-01 (entrada completa y numérica) y TIME-02 (caso y versión). PLAN-04 y PLAN-05 se omiten si fallan las anteriores, como en DEV03; una regla omitida no cuenta como cumplida. PLAN-01 pasará a rechazar valores booleanos (hoy `True` pasaría como 1 s); el compilador de DEV03 queda igual de estricto o más. |
| D14 | **Registro y versión de reglas.** Cada corrección guarda estado, duraciones originales y finales, cambio por slot, ciclo, verde por grupo con sus ventanas, reglas cumplidas y violadas, y la versión de las reglas. Esa versión es una huella SHA-256 de la parte temporal del caso (tick, ciclo, slots y grupos) más la versión del algoritmo: cambia si cambian los límites o el algoritmo, no si cambian la descripción o los flujos. Es un modelo del dominio, no un contrato nuevo (siguen nueve). |
| D15 | **Cobertura y verificador previo.** Una función cuenta `accepted`, `corrected`, `rejected` e `invalid_input` sobre un conjunto de entradas. Cobertura = (aceptados + corregidos) / (aceptados + corregidos + rechazados): los rechazados cuentan; las entradas rotas se informan aparte porque no son admisibles. El validador sirve para comprobar el plan de referencia del caso; la verificación del caso antes de generar etiquetas se hace en DEV14 (aclaración aprobada). |
| D16 | **Tolerancias** iguales a DEV02 y DEV03: 1e-9 s y 1e-8 ticks relativo. Un original dentro de la tolerancia cuenta como `accepted`, y su final es el valor exacto en ticks. |
| D17 | **Pruebas.** Unitarias de cada regla con casos de frontera (justo en el límite, un tick afuera, medio tick, ventanas solapadas y que cruzan el fin del ciclo, ciclo incoherente); propiedades con miles de planes generados con semilla (todo aceptado o corregido cumple todo; corregir dos veces da lo mismo; nunca se acepta un inválido); concordancia con el compilador de DEV03; caso-001; entradas hostiles; y mutaciones en cada fase. |

## Punto que requiere su OK: ¿a quién se le quita el tiempo cuando el ciclo se pasa? (D6)

Ejemplo: el modelo propone todos los verdes al máximo (t1 110, t3 60, t5 70, t7 30). Con los fijos el ciclo sería 294 s, y el máximo es 240 s: sobran 54 s.

| Opción | Cómo reparte | Resultado (t1 / t3 / t5 / t7) | Ciclo 120 s, todo al mínimo |
|---|---|---|---|
| **A. Uno tras otro** (lectura literal) | Se le quita todo lo posible al primer verde (Javier Prado), luego al segundo, y así | **56** / 60 / 70 / 30 | Se le dan los 21 s faltantes a Javier Prado: 51 / 15 / 25 / 5 |
| **B. Por turnos** (recomendada) | Se quita 1 s a cada verde, en el mismo orden, y se repite hasta agotar el exceso | 96 / 46 / 57 / 17 | 36 / 20 / 30 / 10 |

**Recomiendo B.** Con A, Javier Prado (la vía con más tráfico) siempre pierde primero y puede quedar con la mitad de su verde, solo por estar primero en la lista. B reparte parejo y sigue respetando el texto del diseño («en orden canónico»). Las dos son deterministas, nunca bajan de un mínimo ni pasan un máximo, y en caso-001 ninguna rechaza.

Su elección se anota en D6 y en el acta de F3. El especialista de tránsito puede revisarla junto con los límites de DEV03.

## Hallazgos

| # | Hallazgo | Consecuencia |
|---|---|---|
| 1 | En caso-001, los límites de cada grupo de verde son exactamente la suma de los límites de sus slots | En este caso un verde de grupo nunca queda afuera después de recortar: la corrección nunca rechaza. Los rechazos (D11) se prueban con casos sintéticos con grupos más estrictos. La cobertura de caso-001 saldrá 100 % por cómo están escritos los límites, no por la fuerza del algoritmo; se dirá así en el cierre |
| 2 | Hoy `plan_issues` trata `True` como 1 s: solo lo rechaza si 1 s queda fuera de los límites del slot | Se corrige en F2 (D13) |
| 3 | Dividir decimales binarios da ticks como 3.4999… | Aritmética exacta (D8) |

## Fases que siguen (sin cambios respecto del plan)

| Fase | Qué se hace | Modelo |
|---|---|---|
| F1 | `dominio/timing.py`: reconstruir ciclo, verdes y ventanas; entrada hostil | Sonnet alcanza |
| F2 | `dominio/feasibility.py`: reglas preparadas y validador (PLAN-01 a 05, TIME-01 y 02); QA02 | Sonnet alcanza |
| F3 | Corrector (D5 a D11), con la opción de D6 que elija el Product Owner | Opus |
| F4 | QA22, cobertura, concordancia con el compilador, caso-001 y seguridad | Sonnet alcanza |
| F5 | Cierre | Sonnet alcanza |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
