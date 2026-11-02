# Acta 2026-11-02: DEV13 · F1 (reconstruir ciclo, verdes y ventanas)

- **Tipo:** fase F1 de DEV13 (HU11; QA02 en lo que toca a «reconstruir»). Ejecutada sola, por pedido del Product Owner (fase por fase).
- **Decisiones que aplica:** D2, D4, D8, D12, D13 y D16 de `2026-11-02-dev13-f0-decisiones.md`.
- **Modelo:** Sonnet, como estaba previsto para esta fase.
- **Datos:** sintéticos. El caso-001 real solo se leyó.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/dominio/timing.py` | `reconstruct(caso, duraciones)`: ciclo, inicio y fin de cada slot, y verde de cada grupo con sus ventanas. `duration_issues(esperados, duraciones)`: revisa que la entrada tenga sentido. `TimingInputError`. Puro: no lee archivos ni lanza procesos |
| `tests/unit/test_timing.py` | 379 pruebas |

No hay comandos de línea ni archivos publicados en esta fase, y el contrato no cambia.

## Cómo se cuenta

- **Ciclo:** suma cada slot una vez. En el programa actual de caso-001 da 206 s. Los verdes de los grupos suman 364 s, porque los grupos comparten slots; por eso nunca se suman grupos para obtener el ciclo (QA02: sin doble conteo de solapes).
- **Verde de un grupo:** suma de sus slots, cada uno una vez aunque el grupo lo nombre dos veces. Un slot que no existe se ignora.
- **Ventanas:** una ventana es una racha de slots seguidos del grupo. Si el grupo usa el último slot y el primero, son una sola ventana que cruza el fin del ciclo (`wraps`). Si las rachas están separadas, cada una queda con su inicio y duración, y el total del grupo no incluye el hueco. Las ventanas van ordenadas por su inicio en el ciclo.
- **Exactitud:** cada número se lee como decimal tal como se escribió (0.1 + 0.2 + 0.4 da 0.7, no 0.7000000000000001) y se pasa a `float` al final.
- **Orden de las claves:** no importa; siempre se recorre la secuencia del caso.

## Qué rechaza (regla TIME-01)

`reconstruct` no mira límites; solo rechaza lo que no tiene sentido como duración:

| Entrada | Motivo |
|---|---|
| Falta un slot, sobra una clave, o la entrada no es un objeto | «falta la duración del slot», «no es un slot esperado», «debe ser un objeto…» |
| Texto, nulo, lista, objeto, complejo, `Fraction`, `Decimal`, bytes | «debe ser un número» |
| Verdadero o falso | «debe ser un número» (un booleano no es una duración) |
| NaN, infinito | «debe ser un número finito» |
| Negativo, incluso −1e−300 | «no puede ser negativa» |
| Entero de 400 cifras | «es demasiado grande para ser una duración» |
| Duraciones cuya suma no cabe en un número (1.7e308 + 1.7e308) | Error con `durations`: «suman más de lo que cabe en un número» |

El cero y −0.0 se aceptan: reconstruir no es juzgar (que 0 s esté fuera de los límites del slot lo dice F2). Se informan todos los problemas juntos, hasta 100, y el último dice cuántos faltan por mostrar. Los nombres muy largos se acortan a 40 caracteres en los mensajes.

## Decisiones tomadas en esta fase (afinan F0, no la cambian)

| # | Decisión |
|---|---|
| F1-1 | **TIME-01 sirve a las dos entradas.** `duration_issues(esperados, duraciones)` recibe los IDs esperados: en F2 el validador la usará con todos los slots (plan completo) y en F3 el corrector con los slots variables. Si TIME-01 falla, el validador informará TIME-01 y omitirá PLAN-01 a PLAN-05 (no cuentan como cumplidas). PLAN-01 sigue existiendo para el compilador de DEV03. |
| F1-2 | **Sin tope arbitrario de segundos.** Una duración de 1e300 se reconstruye; solo se rechaza cuando la suma ya no cabe. |
| F1-3 | **Casos incoherentes no rompen.** Un ID de slot repetido en el caso usa el primero y un grupo con un slot inexistente lo ignora, igual que en `case_rules`. En el uso normal el caso ya pasó `accept_case`. |
| F1-4 | **Tipo de resultado:** clases de datos inmutables (`Timing`, `SlotTiming`, `GroupTiming`, `GreenWindow`), como `Window` y `CaseIssue`. El registro completo de F3 (D14) se arma sobre ellas. |

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | 379, entre ellas 300 casos generados con semilla (1 a 9 slots, hasta 6 grupos) que comprueban: ciclo exacto; slots sin huecos ni solapes que llegan al final del ciclo; total de cada grupo exacto; ventanas que reparten los slots del grupo sin faltar ni repetir; cada ventana consecutiva en la secuencia circular; inicio correcto; `wraps` correcto; ventanas ordenadas. Otra prueba confirma que esos casos incluyen ventanas que cruzan y ventanas separadas |
| Suite completa | **3387 pasan, 1 se salta** (la que solo corre fuera de Windows; antes 3008). Formato, lint, tipos estrictos, contratos y reglas de capas sin observaciones. Sin dependencias nuevas; `schemas/` y `pyproject.toml` sin cambios |
| Mutaciones | 56 cambios a propósito, uno por vez. 54 detectados a la primera; 2 sobrevivieron (el límite exacto de 40 caracteres al acortar un nombre y el recorte). Eran huecos reales de pruebas: se agregó una prueba (clave de 40 y de 41 caracteres) y las 4 variantes de esos dos puntos quedaron detectadas. Ninguna mutación equivalente |
| Tiempo | 20 000 slots y 10 000 ventanas en una sola llamada: 0.45 s medidos (la prueba permite hasta 10 s) |

## Inspección contra el caso real (solo lectura)

| Comprobación | Resultado |
|---|---|
| Programa actual con `datos/casos/caso-001/case.json` | Ciclo 206 s; verdes 82, 132, 45, 45 y 60 s, los de la tabla de DEV03 F0 |
| Ventanas | `jp_oeste_este_recto`: t1, t2, t3 desde 0 s durante 132 s. `frutales_norte`: t5, t6, t7 desde 137 s durante 60 s. Ninguna cruza el fin del ciclo |
| Programa derivado publicado en `datos/derivados/programas/caso-001/…/tramos.json` (fuente independiente) | Ciclo y los 5 verdes **idénticos** a los que reconstruye este código |
| 20 000 planes al azar dentro de límites | Diferencia máxima con la suma en punto flotante de DEV03: 0.0 |
| `datos/` real | Sin cambios |

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Mi ejemplo de exactitud decimal (0.1 + 0.2 + 0.7) no probaba nada: en binario sí da 1.0 | Se cambió a 0.1 + 0.2 + 0.4, que en binario da 0.7000000000000001, y la prueba afirma esa diferencia |
| 2 | El lint pidió marcar el generador de números al azar de las pruebas (S311) y evitar `Any` | Se usó la misma marca que las pruebas anteriores y el tipo exacto `GroupTiming` |
| 3 | Dos mutaciones sobrevivieron | Cerradas con una prueba (ver arriba) |

## Límites

- `reconstruct` supone un caso razonable; no reemplaza `accept_case`. F2 prepara el caso una sola vez y exige que pase las reglas CASE-C01 a C13.
- Las ventanas no tienen límites propios: el caso solo define límites por grupo (D12).
- Las duraciones aceptadas aquí pueden estar fuera de los límites del caso; eso lo dice el validador de F2.

## Fase que sigue

F2: `dominio/feasibility.py`, reglas preparadas por caso y validador (PLAN-01 a PLAN-05, TIME-01 y TIME-02, cumplida / violada / omitida), con los casos de frontera de QA02. Complejidad media, esfuerzo mediano, riesgo medio, Sonnet alcanza.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
