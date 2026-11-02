# Acta 2026-11-02: DEV13 · F4 (QA22, cobertura, compilador y seguridad)

- **Tipo:** fase F4 de DEV13 (HU11; QA22). Ejecutada sola, por pedido del Product Owner (fase por fase).
- **Decisiones que aplica:** D15 y D17 de `2026-11-02-dev13-f0-decisiones.md`.
- **Modelo:** Sonnet, como estaba previsto para esta fase.
- **Datos:** sintéticos. El caso-001 real y su red solo se leyeron.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/dominio/feasibility.py` (ampliado) | `summarize(correcciones)` y `Coverage`: cuenta aceptadas, corregidas, rechazadas y de entrada inválida; calcula la cobertura; arma el reporte de restricciones |
| `src/semaforo/dominio/timing.py`, `adjust_order.py` | `shown` (el acortador de textos) pasa a ser público y los mensajes del orden de ajuste y de TIME-02 lo usan (hallazgo 1) |
| `tests/unit/test_correction_coverage.py` | 31 pruebas de QA22 y de la cobertura |
| `tests/unit/test_correction_compiler.py` | 13 pruebas de concordancia con el compilador de SUMO de DEV03 |
| `tests/security/test_dev13.py` | 77 pruebas de seguridad |

No hay comandos de línea ni archivos publicados, y el contrato no cambia (siguen nueve).

## La cobertura

`cobertura = (aceptadas + corregidas) / (aceptadas + corregidas + rechazadas)`.

- **Las rechazadas cuentan** en el denominador: son propuestas admisibles que la corrección no logró arreglar.
- **Las de entrada inválida no cuentan:** no son propuestas admisibles (un dato roto no es una predicción). Se informan aparte.
- **Sin propuestas evaluadas la cobertura es `None`**, no 100 %.
- **Reporte de restricciones** (la evidencia que pide QA22): cuántas rechazadas violan cada regla, en cuántas propuestas corregidas cambió cada verde y cuál fue el mayor cambio de cada uno.
- **No se mezclan reglas distintas:** si las correcciones traen versiones de reglas diferentes, `summarize` falla. La admisibilidad no se redefine después de ver las predicciones (diseño técnico).
- Se lee el conjunto una sola vez y se guarda un volumen constante de datos, aunque sean millones de correcciones.

Ejemplo de las pruebas (grupo «recto» exigido entre 100 y 150 s, más estricto que sus tramos): 10 propuestas dan 2 aceptadas, 3 corregidas, 3 rechazadas y 2 inválidas. Cobertura 5/8 = 62.5 %; no 5/5 ni 5/10.

## QA22 punto por punto

| QA22 pide | Cómo se cumple |
|---|---|
| Predicciones fuera de límites | Se recortan; 10 propuestas del ejemplo, cada una con su estado esperado |
| NaN | `invalid_input` con el motivo; no se corrige |
| Casos irreparables | `rejected` con la regla (PLAN-05) y el grupo; el plan intentado queda registrado pero `plan` es `None` |
| Corregir dos veces con la misma entrada | El registro es idéntico, y el resumen también |
| Determinista y acotado | Cada verde queda en sus límites y en segundos enteros; el ciclo en su ventana (400 propuestas generadas, F3) |
| Los aceptados cumplen todo | Todo plan admisible vuelve a pasar `check_plan` con las 6 reglas cumplidas |
| Los rechazados cuentan en la cobertura | Ver arriba |
| Reporte de restricciones | `Coverage.rejected_by_rule`, `corrected_by_slot` y `largest_change_s` |

## Concordancia con el compilador de SUMO de DEV03

Con la red de demostración y su caso (14 × 14 planes, con valores fuera de límite, medio tick, ruido mínimo y 1e6):

- Un plan es **factible exactamente cuando el compilador lo acepta** (más de 10 de cada clase).
- Un tramo fijo alterado lo rechazan los dos; los límites del ciclo coinciden en el borde.
- Un valor que no es número finito lo rechazan los dos sin romperse.
- Todo plan corregido compila, y el programa compilado tiene las mismas duraciones que el plan corregido, en segundos enteros y con el ciclo dentro del rango.

## Seguridad

Entradas no confiables: la propuesta de duraciones, el caso y el archivo del orden de ajuste.

| Qué se prueba | Resultado |
|---|---|
| 14 valores hostiles en un verde (diccionario o lista anidados 50 000 niveles, texto o bytes de 5 MB, entero de 100 000 cifras, NaN, infinito, booleano, nulo, objeto, complejo…) | `invalid_input` con el motivo, en menos de 5 s, mensajes de menos de 400 caracteres; en un plan completo, TIME-01 |
| Propuesta que no es un objeto (nulo, número, texto, bytes, lista, tupla, conjunto, objeto) | `invalid_input` en `durations` |
| 1 000 000 de claves de más | Menos de 10 s; 100 problemas y un último «y 999904 problemas más sin mostrar» |
| Claves de 1 MB, con tuplas gigantes, control, números o nulo | Todas informadas sin repetirse enteras |
| Caso y versión de 1 MB | Mensajes acotados (ver hallazgo 1) |
| 2 000 propuestas al azar con basura de 18 tipos | Nunca lanza; el estado siempre es uno de los cuatro; todo lo admisible vuelve a validar |
| Valores finitos extremos (5e-324, 1e308, el máximo del `float`) | `corrected`, no entrada inválida |
| Caso de 5 000 tramos: preparar y 5 correcciones; plan de 20 000 tramos | Menos de 15 s y 10 s; medido, alrededor de 1 s y 0.5 s |
| Archivo de orden: enlace, carpeta, vacío, nulo, lista, claves repetidas, NaN, bytes no UTF-8, 20 000 corchetes, 50 MB | Error de dominio con código INPUT_SCHEMA (PATH_NOT_ALLOWED para el enlace); los 50 MB se rechazan en menos de 5 s sin leerlos enteros |
| Orden con 900 nombres desconocidos, repetidos o fijos | 100 problemas y el conteo de los demás; mensajes acotados |
| Nombres con salto de línea, espacios en los extremos, nulo, ancho cero o vacíos | Rechazados por la estructura (ORDER-S02) |
| Nombres de 60 000 caracteres (desconocido, repetido, fijo, versión, caso) | Mensajes acotados con «…» |
| Resumen de 20 000 correcciones | Datos constantes (a lo sumo un renglón por verde) |

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | **121** (31 + 13 + 77). Suite completa: **4403 pasan, 1 se salta** (la que solo corre fuera de Windows; antes 4282). Formato, lint, tipos estrictos, contratos y reglas de capas sin observaciones. Sin dependencias nuevas; `schemas/` y `pyproject.toml` sin cambios |
| Mutaciones | 30 cambios a propósito, uno por vez: 19 en la cobertura y 11 en los mensajes acotados. **28 detectados a la primera.** Sobrevivieron 2, y eran huecos reales (no había prueba de un nombre enorme repetido en el orden ni de un tramo fijo con nombre enorme); se agregaron y las 2 quedaron detectadas |
| Mutación equivalente | El orden alfabético de `rejected_by_rule` no se puede distinguir: después de corregir solo puede quedar violada una regla (PLAN-05), así que tiene una sola clave. Se mantiene el orden para que el resultado sea determinista si algún día hay más |

## Inspección contra el caso real (solo lectura)

20 000 propuestas con caso-001 y su orden de ajuste (una cuarta parte con NaN en la mitad de los verdes):

| Resultado | Cifra |
|---|---|
| Aceptadas | 4 520 |
| Corregidas | 10 724 |
| Rechazadas | **0** |
| Entrada inválida (NaN) | 4 756 |
| Cobertura | **100 %** (15 244 de 15 244) |
| Cuántas veces cambió cada verde | t1 10 335, t3 10 314, t5 10 434, t7 10 695 (de 10 724 corregidas) |
| Mayor cambio por verde | t1 189.9 s, t3 240.0 s, t5 258.9 s, t7 295.0 s |
| Velocidad | Unas 2 600 correcciones por segundo |

| Comprobación con la red real (`osm.net.xml.gz`) | Resultado |
|---|---|
| Mapa de la red frente al caso | Completo |
| Planes admisibles que compilan a un programa de SUMO | **3 000 de 3 000** |
| 500 planes completos al azar: validador contra compilador | **0 discrepancias** |
| `datos/` real | Sin cambios: 10 íntegras, 0 alteradas, 3 desconocidas (las mismas de antes) |

**Esta cobertura del 100 % se debe a cómo están escritos los límites, no a la fuerza del algoritmo.** En caso-001 el límite de cada grupo de verde es exactamente la suma de los límites de sus tramos (hallazgo 1 de F0), así que, después de recortar cada tramo, ningún grupo puede quedar afuera y la corrección no puede fallar. Los rechazos solo se ven con límites de grupo más estrictos que sus tramos, y eso se probó con casos sintéticos (3 rechazadas de 8 evaluadas, 37.5 %, en el ejemplo de arriba). Si el especialista de tránsito endurece algún límite de grupo, hay que volver a medir esta cobertura con el mismo comando.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Los mensajes de TIME-02 y del orden de ajuste repetían enteros los textos del usuario (caso, versión, nombre de tramo): una versión de 1 MB daba un mensaje de 1 MB, multiplicado por hasta 100 problemas | Se usa el acortador de F1 (`shown`, ahora público): máximo 40 caracteres y «…» |
| 2 | Cuatro expectativas de mis pruebas estaban mal: un diccionario anidado es un objeto (no «no es un objeto»); la cuenta de omitidos con un millón de claves es 999 904; los nombres con salto de línea ya los rechaza la estructura; y los cambios se miden contra lo propuesto, no contra la línea base | Corregidas con la cuenta a la vista |
| 3 | Dos mutaciones sobrevivieron | Cerradas con pruebas |
| 4 | Una edición con una barra invertida dentro de una cadena se aplicó mal (la herramienta la convierte en salto de línea) | Usé el editor de archivos y `chr()`, como indica la nota guardada |
| 5 | Una lista de identificadores de prueba de 100 000 corchetes se pasó del límite de 64 KiB del archivo del orden | Se bajó a 30 000 (sigue probando la anidación) |

## Límites

- La cobertura se calcula sobre las propuestas que se le entreguen. DEV25 la usará con las predicciones del modelo sobre el desarrollo, antes de congelarlo; no se puede conocer la cobertura real hasta que exista el modelo.
- La concordancia con el compilador usa la red de demostración en las pruebas automáticas y la red real en la inspección; las pruebas no dependen de `datos/`.
- No se ejecutó SUMO: el compilador solo genera el archivo del programa. La corrida real con un plan corregido es de DEV14 y posteriores.

## Fase que sigue

F5: cierre de DEV13. Acta de cierre con HU11, QA02 y QA22 punto por punto, inspección final contra la documentación y el caso real, verificación de que no quedó nada pendiente y bitácora. Complejidad baja, esfuerzo pequeño, riesgo bajo, Sonnet alcanza.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
