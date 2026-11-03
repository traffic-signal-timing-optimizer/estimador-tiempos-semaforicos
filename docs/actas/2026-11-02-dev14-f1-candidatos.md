Escrito para: el Product Owner (qué se hizo) y el equipo técnico (reglas y verificación).

# DEV14 F1: lista de planes candidatos

- **Fecha:** 2026-11-02
- **Plan y decisiones:** `2026-11-02-plan-dev14.md` y `2026-11-02-dev14-f0-decisiones.md`
- **Historia y prueba:** HU08; QA16, en la parte que no necesita SUMO
- **Datos:** sintéticos en las pruebas. El caso-001 real se usó solo para leer, sin escribir nada en `datos/`.

## Qué se hizo, en simple

La herramienta ya puede **armar la lista de planes de semáforo a probar** en un escenario:

- Cada plan dice cuántos segundos de verde tiene cada tramo variable: t1, t3, t5 y t7 en Frutales.
- Cada plan pasa por las reglas de DEV13: ciclo de 120 a 240 s, cada tramo dentro de sus límites y cada grupo de verde dentro de los suyos. Un plan que no cumple no entra en la lista y se cuenta por la primera regla que rompe.
- Si todos los planes posibles caben en el presupuesto, se prueban todos (grilla). Si no, se toma una muestra al azar repetible: con la misma semilla sale siempre la misma lista.
- Un plan repetido no se vuelve a probar.
- El plan vigente entra primero y no gasta presupuesto. Si no cumple las reglas, queda fuera con el motivo anotado.
- Se guarda una traza con todos los candidatos y los conteos: intentos, repetidos, inviables por regla y si se agotaron los intentos.

Todavía no se simula nada. Eso es F2.

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/search.py` | `generate_candidates`, `CandidateSet` (con `trace()`), `Candidate`, `SEARCH_VERSION` y `GRID_SCAN_LIMIT` |
| `src/semaforo/referencias/errors.py` | `ReferenciasError` |
| `tests/unit/test_search_candidates.py` | 39 pruebas |

## Reglas fijadas en esta fase

1. **Plan = vector de ticks** de los slots variables. Los fijos llevan su valor. El identificador `cand-<huella>` sale del vector: el mismo plan tiene el mismo identificador venga de donde venga. Eso sirve en F2 para retomar una búsqueda cortada.
2. **Grilla:** si la caja de ticks tiene como mucho 20 000 vectores, se recorre entera. Si sus factibles nuevos caben en B, son los candidatos. Si no caben, o la caja es mayor, se muestrea.
3. **Muestra:** para cada slot, un valor uniforme entre su mínimo y su máximo. El azar sale de SHA-256 de la semilla, el escenario, el intento y el slot, así que no depende de la versión de Python. Se quitó la versión de reglas de esa huella: un caso con los mismos límites da la misma muestra, y así dos versiones del caso se pueden comparar.
4. **B cuenta candidatos únicos y factibles de la búsqueda.** El plan vigente es auxiliar y no consume B. Lo pide el diseño técnico: «registrar si el presupuesto corresponde a candidatos únicos» y si los auxiliares «consumen B». Las dos cosas quedan en la traza.
5. **Intentos:** se cumple siempre que intentos = aceptados + repetidos + inviables. Si se agotan antes de llenar B, queda `exhausted`.
6. **Entradas inválidas:** B o el límite de intentos que no sean enteros mayores que cero, una semilla que no sea entera (un booleano no cuenta) o un escenario sin identificador se rechazan con `ReferenciasError`, el campo y un mensaje corto.

## Verificación

- **Pruebas:** 39 nuevas.
  - QA16 sin SUMO: un espacio pequeño contado a mano se enumera entero; la misma búsqueda dos veces da lo mismo; B se respeta.
  - Muestras repetibles y distintas al cambiar de semilla o de escenario.
  - Todos los candidatos son factibles, únicos y dentro de sus límites.
  - Conteos por la primera regla rota, plan vigente con ruido tolerado, tick de 0,5 s, traza en JSON y entradas inválidas.
- **Puerta completa:** `scripts/check.ps1` (ruff, formato, pyright estricto, 4793 pruebas pasan y 1 se salta, contratos 43/43, ningún archivo oculto).
- **Mutaciones:** 36 preparadas.
  - En la primera pasada se aplicaron 31: 26 se detectaron y 5 sobrevivieron. Las otras 5 no se pudieron aplicar por el fin de línea (ver hallazgos).
  - 4 de las 5 sobrevivientes mostraron huecos reales, cerrados con 4 pruebas: la primera regla rota frente a la última, el redondeo del plan vigente, la traza cuando se agotan los intentos y la traza del plan vigente excluido.
  - La quinta, que dependía de la versión de reglas, llevó a simplificar el código (regla 3) y salió de la lista.
  - Segunda pasada con las 35 restantes: 34 detectadas y 1 sobreviviente (quitar la deduplicación en el muestreo), cerrada con una prueba en el espacio pequeño. Resultado final: 35 de 35 detectadas.
- **Caso-001 real (solo lectura):** caso y orden de ajuste de `datos/casos/caso-001/`, plan vigente de `datos/derivados/programas/caso-001/…/tramos.json`.
  - El espacio tiene 4 456 296 planes, demasiados para la grilla, así que se muestrea.
  - Con B=20, semilla 1001 y 2000 intentos: 23 intentos, 3 inviables por el ciclo (PLAN-04), 0 repetidos, sin agotar.
  - Resultado: 21 candidatos (20 más el vigente, de 206 s), todos factibles, con ciclos de 129 a 240 s. Tomó 0,02 s, y repetir la búsqueda dio lo mismo.

## Inspección contra la documentación

| Exigencia | Estado |
|---|---|
| Grilla de ticks factibles si cabe en B | Cumplido (regla 2) |
| Muestreo uniforme reproducible, rechazo de inviables, deduplicación por vector, máximo de intentos declarado | Cumplido |
| Registrar si B es de candidatos únicos y si los auxiliares lo consumen | Cumplido en la traza |
| Plan vigente solo si es factible | Cumplido; si no, queda `excluded` con sus reglas |
| Webster | Fuera de DEV14 (F0-5): es de DEV15 y necesita DEC08 |
| No garantizar el óptimo global | Lo dice el módulo; la etiqueta lo dirá en F3 |
| Sin contratos nuevos ni dependencias nuevas | Cumplido: `schemas/` sin cambios |

## Hallazgos

1. Al reescribir dos archivos con un guion de Python en Windows, quedaron con fin de línea CRLF, y el repositorio pide LF (`.gitattributes`). Por eso 5 mutaciones no se pudieron aplicar en la primera pasada. Se corrigió antes del commit. Para los próximos guiones: escribir bytes, no texto.

## Siguiente

F2: simular cada candidato con `evaluate_run`, decidir quién puede ganar (cohorte completa, sin teletransportes ni choques), desempatar, reevaluar a los finalistas, correr 4 a la vez y retomar si se corta. Es la fase más delicada. Complejidad alta, esfuerzo medio, riesgo alto, con Opus.
