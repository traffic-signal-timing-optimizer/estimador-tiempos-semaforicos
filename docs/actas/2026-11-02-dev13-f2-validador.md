# Acta 2026-11-02: DEV13 · F2 (validador de factibilidad)

- **Tipo:** fase F2 de DEV13 (HU11; QA02 con casos de frontera). Ejecutada sola, por pedido del Product Owner (fase por fase).
- **Decisiones que aplica:** D2, D3, D4, D13, D15 y D16 de `2026-11-02-dev13-f0-decisiones.md`, y F1-1 de `2026-11-02-dev13-f1-reconstruir.md`.
- **Modelo:** Sonnet, como estaba previsto para esta fase.
- **Datos:** sintéticos. El caso-001 real y el programa real de DEV03 solo se leyeron.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/dominio/feasibility.py` | `prepare(caso)`: comprueba el caso una sola vez (CASE-C01 a C13) y lo deja listo. `check_plan(caso_preparado, duraciones)`: valida un plan completo regla por regla. Puro: no lee archivos ni lanza procesos |
| `src/semaforo/dominio/case_rules.py` | Se extrajo `require_consistent(caso)` de `accept_case` para reutilizarla sin repetir código. `accept_case` se comporta igual |
| `src/semaforo/dominio/case_plan.py` | PLAN-01 ahora rechaza booleanos, textos, listas y enteros enormes (ver hallazgo 2) |
| `tests/unit/test_feasibility.py` | 370 pruebas |
| `tests/unit/test_case_plan.py` | 2 pruebas nuevas |

No hay comandos de línea ni archivos publicados, y el contrato no cambia (siguen nueve).

## Cómo funciona

`check_plan` devuelve, por cada regla, si quedó **cumplida**, **violada** u **omitida**, con todos sus problemas, y el ciclo y los verdes del plan cuando la entrada es numérica (aunque se pase de los límites, para mostrar cuánto).

| Regla | Qué revisa |
|---|---|
| TIME-02 | El plan dice ser del caso y de la versión que se está usando. Solo se evalúa si se indica de qué caso y versión dice ser; si no coincide, no se evalúa nada más |
| TIME-01 | Un número finito y no negativo por slot, y ninguna clave de más (F1) |
| PLAN-01 | Una duración finita por slot |
| PLAN-02 | Dentro de los límites de su slot. Los slots fijos tienen mínimo igual al máximo, así que cambiar un ámbar o el todo rojo incumple esta regla |
| PLAN-03 | Múltiplo del tick |
| PLAN-04 | Ciclo dentro del rango del caso (cada slot cuenta una vez) |
| PLAN-05 | Verde de cada grupo dentro de sus límites (sin doble conteo de solapes) |

- **Omitidas:** PLAN-04 y PLAN-05 se omiten si falla PLAN-02 o PLAN-03, porque sumar duraciones inválidas da mensajes sin sentido. Todo lo que sigue a TIME-01 o TIME-02 se omite si ellas fallan. Una regla omitida **no cuenta como cumplida**: el plan es factible solo si todas las reglas evaluadas quedaron cumplidas.
- **Caso preparado:** `prepare` exige que el caso pase todas las reglas de error. Así la secuencia, los estados y el ciclo alcanzable quedan garantizados y un plan solo trae duraciones. Los avisos (CASE-C07) no lo rechazan y quedan en `warnings`.
- **Entrada hostil:** nunca lanza; NaN, tipos raros, claves de más o de menos y sumas que no caben salen como TIME-01.

## Decisiones tomadas en esta fase (afinan F0, no la cambian)

| # | Decisión |
|---|---|
| F2-1 | **TIME-02 va primero y corta.** Si el plan es de otro caso o versión, los límites del caso no significan nada para él; no se evalúa lo demás. |
| F2-2 | **TIME-02 aparece solo si se indicó.** Sin caso ni versión indicados no está en el resultado (en vez de aparecer como «cumplida» sin haberse evaluado). Si se indica solo uno, se evalúa solo ese. |
| F2-3 | **PLAN-01 a PLAN-05 no se reescriben.** Se llama a `plan_issues` de DEV03 y se reparten sus problemas por regla, en las mismas etapas. Una prueba con 300 planes generados comprueba que el resultado coincide con DEV03 en todos. |
| F2-4 | **Orden de los problemas:** agrupados por regla (primero todos los PLAN-02 y luego los PLAN-03), no slot por slot como en DEV03. Solo cambia el orden. |
| F2-5 | **PLAN-01 de DEV03 se endurece** (cumple la promesa de D13): rechaza booleanos, textos, listas y enteros enormes. Antes, `True` pasaba como 1 s y un texto o una lista tumbaban la comprobación con un error interno. El compilador de SUMO queda igual de estricto o más. |

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | 372 (370 del validador y 2 de PLAN-01). Casos de frontera de QA02: cada límite de slot justo adentro y a un segundo afuera; ruido de 1e-10 aceptado y de 1e-6 no; medio tick; ciclo en 120 y 240 y a un segundo de cada lado; verde de grupo en su mínimo y máximo y a un segundo afuera; un slot compartido por dos grupos; ámbar alterado; ciclo incoherente y grupo inalcanzable (el caso no se prepara); caso o versión distintos; booleanos, texto, listas, NaN, infinito, entero enorme, claves de más y de menos, entrada que no es un objeto, suma que desborda |
| Concordancia con DEV03 | 300 planes generados con semilla (fuera de límites, fuera del tick, extremos, válidos) dan los mismos problemas que `plan_issues`, y «factible» equivale a «sin problemas». Se comprobó además que cubren PLAN-02, PLAN-03, ambos juntos y PLAN-04 |
| Suite completa | **3759 pasan, 1 se salta** (la que solo corre fuera de Windows; antes 3387). Formato, lint, tipos estrictos, contratos y reglas de capas sin observaciones. Sin dependencias nuevas; `schemas/` y `pyproject.toml` sin cambios |
| Mutaciones | 44 cambios a propósito, uno por vez: 38 en el validador y en `require_consistent`, y 6 en PLAN-01. **43 detectados a la primera y 1 equivalente**: agregar el resultado de TIME-02 cuando nadie lo pidió no cambia nada, porque la lista final lo descarta. Ningún hueco real de pruebas |

## Inspección contra el caso real (solo lectura)

| Comprobación | Resultado |
|---|---|
| `prepare` con `datos/casos/caso-001/case.json` | Pasa; slots t1 a t9, variables t1, t3, t5, t7; sin avisos |
| Programa real publicado por DEV03 (`tramos.json`), con caso y versión indicados | Factible: las 7 reglas cumplidas |
| t1 = 120 | PLAN-02, «120 s está fuera de los límites del slot (30 a 110 s)» |
| t3 = 45.5 | PLAN-03, «no es múltiplo del tick de 1 s» |
| Todos los verdes al máximo (ciclo 294) y al mínimo (ciclo 99) | PLAN-04, «el ciclo de 294 s está fuera del rango del caso (120 a 240 s)» |
| t2 (ámbar) = 6 | PLAN-02, «6 s está fuera de los límites del slot (5 a 5 s)» |
| NaN en t5; plan de la versión 2.0.0 | TIME-01; TIME-02 |
| 20 000 planes al azar | 254 factibles; **0 discrepancias** con `plan_issues` de DEV03 |
| Velocidad | Unos 5 300 planes por segundo (3.8 s los 20 000). Alcanza para DEV14; si la búsqueda necesitara más, se puede agregar una vía rápida sin cambiar los resultados |
| `datos/` real | Sin cambios: 10 íntegras, 0 alteradas, 3 desconocidas (las mismas de antes) |

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Mi prueba de «un grupo que repite un slot» suponía que se cuenta una vez, pero el caso ya lo rechaza (CASE-C09) | La prueba ahora afirma que ese caso no se prepara |
| 2 | `plan_issues` de DEV03 trataba `True` como 1 s y se caía (`TypeError`) con un texto o una lista | PLAN-01 endurecido y con pruebas (ver F2-5) |
| 3 | `prepare` deduplicaba los IDs de slot, pero el caso ya garantiza que son únicos: código que ninguna prueba podía distinguir | Se quitó |
| 4 | Una línea de documentación quedó demasiado larga y la puerta de calidad la atrapó | Corregida; la puerta volvió a pasar |
| 5 | Una afirmación de prueba tenía un `or True` que la dejaba vacía | La reescribí para que afirme lo que dice |

## Límites

- El validador solo mira lo que el caso define. «Factible» significa conforme al caso representado, no seguro para operar un cruce.
- El caso no define límites por ventana, solo por grupo (D12); no se inventan.
- Una vía rápida para validar millones de planes no está hecha porque no hace falta todavía.

## Fase que sigue

F3: el corrector, con el orden de ajuste de cada caso (D6 y D18), el archivo de orden de caso-001, aritmética exacta en ticks, el registro original y final, y los cuatro estados. Es la fase más delicada de la tarea: complejidad alta, esfuerzo grande, riesgo medio-alto, modelo sugerido **Opus**.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
