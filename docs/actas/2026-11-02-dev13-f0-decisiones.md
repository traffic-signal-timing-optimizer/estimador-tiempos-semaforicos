# Acta 2026-11-02: DEV13 · F0 (decisiones, sin código)

- **Tipo:** fase F0 de DEV13 (HU11; P0, tamaño L). Dependencia: DEV02, cerrada.
- **Autorización:** el Product Owner aprobó el plan (`2026-11-02-plan-dev13.md`), incluida la aclaración del verificador previo al entrenamiento, y pidió avanzar **fase por fase** por la complejidad alta: solo F0 ahora. Para el ajuste del ciclo (D6) dio sus criterios de tránsito y pidió analizarlos y decidir; la decisión está en D6 y D18.
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
| 20 000 planes al azar, con los tres repartos de D6 (secuencia, por turnos y prioridad) | 0 rechazados; corregir dos veces da siempre lo mismo |
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
| D6 | **Ajuste del ciclo: uno tras otro, en un orden de prioridad propio de cada caso** (decidido con los criterios del Product Owner; ver «Análisis del ajuste del ciclo»). Si el ciclo se pasa del máximo, se quita tiempo al primer tramo del orden hasta su mínimo, luego al segundo, y así. Si queda corto, se da tiempo en el orden inverso, sin pasar máximos. En caso-001 el orden de quitar es **t7, t5, t3, t1**, y el de dar, t1, t3, t5, t7. |
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
| D18 | **Dónde se guarda el orden de ajuste.** En un archivo propio de cada caso, junto al caso (JSON con `case_id`, `case_version` y la lista de slots variables en el orden en que pierden tiempo), validado con su motivo: cada slot variable exactamente una vez, ninguno fijo ni desconocido, caso y versión iguales. No cambia el contrato `case` ni el archivo de caso-001, y no es un contrato publicado (siguen nueve). Su contenido entra en la versión de reglas (D14), así que cambiar el orden cambia la versión. Sin archivo se usa el orden de la secuencia (la lectura literal del diseño) y el registro dice que es el orden por defecto. El código no conoce Frutales: el orden es un dato del caso. El de caso-001 se crea en F3, anotado como criterio del Product Owner. |

## Análisis del ajuste del ciclo (D6 y D18)

**Pregunta:** si el modelo propone verdes que, sumados, pasan del ciclo máximo, ¿a quién se le quita el tiempo?

**Criterio del Product Owner (2026-11-02):** primero a Los Frutales sur→norte (menos flujo), después a Los Frutales norte→sur. Javier Prado depende de la hora: en la punta de la mañana (6:30 a 9:00) la más cargada es este→oeste, y en la de la tarde (17:00 a 20:00), oeste→este.

**Qué tramo sirve a cada ruta** (comprobado con los estados de cada enlace en `case.json`):

| Tramo | Rutas en verde | Verde de cada ruta |
|---|---|---|
| t1 | Javier Prado, los dos sentidos | este→oeste = t1 |
| t3 | Javier Prado oeste→este (recto y flecha) | oeste→este = t1 + t2 + t3; flecha = t3 |
| t5 | Los Frutales, los dos sentidos | sur→norte = t5 |
| t7 | Los Frutales norte→sur, solo | norte→sur = t5 + t6 + t7 |

**Razonamiento:**

1. **No hay un tramo solo para Frutales sur→norte.** Quitarle 1 s a t5 le quita 1 s a sur→norte **y** 1 s a norte→sur. Quitárselo a t7 le quita 1 s solo a norte→sur. Para el ciclo da lo mismo, y norte→sur pierde igual en los dos casos. Entonces **t7 primero es mejor para todos**: sur→norte no pierde nada mientras t7 tenga margen. Después t5.
2. **Javier Prado: t3 antes que t1, en cualquier hora.** Quitarle 1 s a t1 le quita 1 s a este→oeste y 1 s a oeste→este. Quitárselo a t3 le quita 1 s a oeste→este (recto y flecha) y nada a este→oeste.
   - En la tarde (oeste→este más cargada), oeste→este pierde lo mismo con t1 o con t3, y con t3 este→oeste no pierde nada.
   - En la mañana (este→oeste más cargada), t3 no toca la ruta más cargada.

   El orden sale igual en las dos puntas, así que **no hace falta que el corrector conozca la hora**.
3. **Por qué el corrector no debe mirar la hora.** HU11 y la matriz piden una corrección «idéntica en todos los flujos» (ADR06). Darle más verde a este→oeste en la mañana y a oeste→este en la tarde es justamente lo que el **modelo** aprende de las etiquetas (DEV14 busca el mejor plan por familia: punta de la mañana, punta de la tarde). El corrector es una red de seguridad que solo actúa cuando la propuesta se sale de los límites; no debe tomar decisiones de tránsito por su cuenta.
4. **Para dar tiempo** (ciclo bajo 120 s) se usa el orden inverso: primero t1, que sirve a los dos sentidos de Javier Prado; luego t3, t5 y t7.

**Comparación** (segundos de verde que ve cada ruta; las tres opciones cumplen todos los límites):

| Propuesta del modelo | Reparto | JP E→O | JP O→E | Flecha | Frutales N→S | Frutales S→N |
|---|---|---|---|---|---|---|
| Todo al máximo (sobran 54 s) | Orden de la secuencia | **56** | 121 | 60 | 105 | 70 |
| | Por turnos | 96 | 147 | 46 | 79 | 57 |
| | **Prioridad (decidida)** | **110** | **175** | 60 | 51 | 41 |
| t1 100, t3 58, t5 68, t7 29 (sobran 39 s) | Orden de la secuencia | 61 | 124 | 58 | 102 | 68 |
| | Por turnos | 90 | 143 | 48 | 83 | 58 |
| | **Prioridad (decidida)** | **100** | **163** | 58 | 63 | 53 |
| Todo al mínimo (faltan 21 s) | **Prioridad (decidida)** | 51 | 71 | 15 | 35 | 25 |

Con la prioridad, Javier Prado conserva lo que propuso el modelo y el ajuste lo absorbe Los Frutales, empezando por el tramo que solo afecta a una ruta. En 20 000 planes al azar con caso-001 no hubo rechazos, y corregir dos veces dio siempre lo mismo.

**Lo que hay que vigilar:** cuando el modelo se pase del ciclo, Los Frutales puede quedar en sus mínimos (25 s sur→norte y 35 s norte→sur). Los mínimos se fijaron en DEV03 justamente para que la cola alcance a salir. F4 medirá cuántas propuestas se corrigen y cuánto.

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
| F3 | Corrector (D5 a D11), con el orden de ajuste de cada caso (D6 y D18) y el archivo de orden de caso-001 | Opus |
| F4 | QA22, cobertura, concordancia con el compilador, caso-001 y seguridad | Sonnet alcanza |
| F5 | Cierre | Sonnet alcanza |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
