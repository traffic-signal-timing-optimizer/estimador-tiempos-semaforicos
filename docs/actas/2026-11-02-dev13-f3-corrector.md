# Acta 2026-11-02: DEV13 · F3 (corrector determinista)

- **Tipo:** fase F3 de DEV13 (HU11; ADR06). Ejecutada sola, por pedido del Product Owner (fase por fase).
- **Decisiones que aplica:** D4 a D11, D14, D16 y D18 de `2026-11-02-dev13-f0-decisiones.md` (con el orden de ajuste de D6 decidido con los criterios del Product Owner).
- **Modelo:** Opus, como recomendaba el plan.
- **Datos:** sintéticos. El caso-001 real solo se leyó; se le agregó el archivo de orden de ajuste (ver abajo).

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/dominio/feasibility.py` (ampliado) | `correct(caso_preparado, duraciones_variables, case_id=…, case_version=…)` y el registro `Correction`. `prepare(caso, orden)` ahora guarda el orden para quitar (`cut_order`), el orden para dar (`give_order`), de dónde sale (`order_source`) y la versión de reglas (`rules_version`) |
| `src/semaforo/dominio/adjust_order.py` | Modelo del orden de ajuste (`AdjustOrder`), sus reglas ORDER-S01 a S03 y ORDER-C01 a C03, y su error. Puro |
| `src/semaforo/caso/adjust_order_file.py` | `read_adjust_order(ruta)`: lee el archivo con los mismos controles que las demás entradas JSON (64 KiB como máximo, sin enlaces, UTF-8, sin claves repetidas ni NaN) |
| `src/semaforo/dominio/timing.py` | `duration_issues(..., allow_negative=True)` para el corrector (ver F3-1) |
| `datos/casos/caso-001/orden_de_ajuste.json` | El orden de caso-001 (contenido abajo) |
| `tests/timing_tools.py` | Réplica de caso-001 compartida por las pruebas de F2 y F3 |
| `tests/unit/test_correction.py`, `test_adjust_order.py` | Pruebas nuevas; `test_timing.py` y `test_feasibility.py` ampliadas |

No hay comandos de línea ni archivos publicados (la consulta es de DEV18), y el contrato no cambia (siguen nueve).

## Cómo corrige

1. **Entrada.** La propuesta trae una duración para cada verde variable (t1, t3, t5 y t7 en caso-001), del caso y la versión preparados. Si no es así (NaN, texto, un fijo de más, un verde que falta, otro caso o versión), el estado es `invalid_input` y no se corrige nada.
2. **Recorte.** Cada verde se lleva a los límites de su tramo. Un valor enorme o negativo se recorta sin desbordar.
3. **Segundos enteros.** Se pasa a ticks con aritmética exacta: al más cercano y, a medio tick, hacia arriba. Con decimales binarios, 82.35 s con tick de 0.1 daría 823.4999… y se redondearía mal; aquí da 82.4.
4. **Ciclo.** Si se pasa de 240 s, se quita tiempo uno tras otro en el orden del caso, cada tramo hasta su mínimo. Si queda bajo 120 s, se da en el orden inverso, cada tramo hasta su máximo. Son dos recorridos: el número de pasos tiene un tope fijo.
5. **Control final.** El plan final se valida de nuevo con todas las reglas. Si el original ya cumplía todo, el estado es `accepted`; si el final cumple todo, `corrected`; si alguna regla sigue fallando, `rejected`, sin plan admisible.

El registro guarda el estado, el original recibido, el plan final completo (también en un rechazo, para ver qué se intentó), el cambio de cada verde, las reglas cumplidas y violadas con el ciclo, los verdes y las ventanas, y la versión de reglas. **El corrector no recibe flujos:** su firma solo tiene el caso preparado, las duraciones, el caso y la versión.

## El orden de ajuste de caso-001

Archivo `datos/casos/caso-001/orden_de_ajuste.json`. La carpeta `datos/` no está en git, así que se copia aquí para que quede versionado:

```json
{
  "schema_version": "1.0.0",
  "case_id": "caso-001",
  "case_version": "1.0.0",
  "cut_order": ["t7", "t5", "t3", "t1"],
  "evidence": [
    "Criterio del Product Owner, 2026-11-02: si el ciclo se pasa, quitar tiempo primero a Los Frutales sur-norte (menos flujo), luego a Los Frutales norte-sur; Javier Prado al final (punta de la mañana: este-oeste más cargada; punta de la tarde: oeste-este)",
    "Análisis en docs/actas/2026-11-02-dev13-f0-decisiones.md (D6 y D18): t7 antes que t5 y t3 antes que t1, porque cada uno afecta a una sola ruta y el otro a dos; el orden sirve en las dos puntas sin mirar la hora",
    "Si falta ciclo se da tiempo en el orden inverso: t1, t3, t5, t7",
    "Pendiente de revisión con el especialista de tránsito, junto con los límites de DEV03"
  ]
}
```

Su versión de reglas es `e2ab7def22c7d6187298a0e2218ed7e789e79734f5fb1415dccd502e4d8d723f`.

## Decisiones tomadas en esta fase (afinan F0, no la cambian)

| # | Decisión |
|---|---|
| F3-1 | **Una predicción negativa no es un dato roto.** El diseño dice «recortar» (paso 2) y solo rechaza NaN, infinito, dimensión o versión. Con la regla de F1 tal cual, −3 s habría sido `invalid_input`; ahora el corrector la recibe y la recorta al mínimo. NaN, infinito, booleanos y textos siguen siendo `invalid_input`. |
| F3-2 | **Orden para dar.** Con orden declarado se da en el inverso del de quitar (D6: el último en perder es el primero en ganar). Sin archivo, se quita y se da en el orden de la secuencia, como dice el diseño al pie de la letra (D18). Al probar el corrector con el caso real noté que mi primera versión daba en orden inverso también sin archivo, contra D18; se corrigió antes de escribir las pruebas. |
| F3-3 | **Un solo camino para aceptar y corregir.** Todo pasa por los mismos pasos; si el original ya cumplía, el final es el mismo plan en ticks exactos (un ruido de 1e-10 s desaparece) y el estado es `accepted`. |
| F3-4 | **Versión de reglas.** Huella SHA-256 del tick, el ciclo, los slots, los grupos, los dos órdenes y la versión del algoritmo (`1.0.0`). No incluye el nombre del caso, la descripción, los movimientos ni los flujos: el nombre y la versión del caso van aparte en el registro. Un orden declarado igual a la secuencia da otra versión, porque da en orden inverso. |
| F3-5 | **Dónde vive el orden.** Junto al caso, en `orden_de_ajuste.json`. Si falta el archivo, se usa la secuencia y el registro lo dice (`order_source`: `sequence`). El código no conoce Frutales. |
| F3-6 | **Caso y versión obligatorios.** El corrector exige que la propuesta diga de qué caso y versión es; el validador de F2 los sigue teniendo opcionales. |

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | **523**. Los ejemplos del acta de F0 dan exactamente sus cifras; ciclo justo en 240 y 120; un tramo que llega a su mínimo y sigue el siguiente; el exceso que recorre los cuatro tramos; dar en orden inverso; sin archivo, el orden de la secuencia; medio tick con ticks de 1, 0.5 y 0.1 s; rechazos por un grupo más estricto que sus tramos y por un grupo que el ajuste del ciclo deja afuera; todas las entradas inválidas; otro caso o versión; 100 000 claves hostiles; registro inmutable; versión de reglas (qué la cambia y qué no); reglas ORDER y lector con archivos rotos |
| Propiedades | 200 propuestas generadas con semilla, cada una corregida con el orden del caso y sin archivo (400 correcciones). Antes del ajuste dan ciclos largos (45), cortos (44) y normales (111). En todas: cada verde dentro de sus límites y en segundos enteros; ciclo entre 120 y 240; el plan final pasa de nuevo la validación; corregir el resultado lo deja igual (aceptado); el cambio es exactamente final menos original; y el ajuste sigue el orden (un tramo pierde solo si los anteriores ya están en su mínimo, y gana solo si los anteriores ya están en su máximo) |
| Suite completa | **4282 pasan, 1 se salta** (la que solo corre fuera de Windows; antes 3759). Formato, lint, tipos estrictos, contratos y reglas de capas sin observaciones. Sin dependencias nuevas; `schemas/` y `pyproject.toml` sin cambios |
| Mutaciones | 59 cambios a propósito, uno por vez (redondeo, recortes, ajuste del ciclo, órdenes, estados, registro, versión de reglas, reglas ORDER, negativos y lector). **57 detectados a la primera.** Sobrevivieron 2, y los dos eran huecos reales: ninguna prueba comprobaba que la versión del algoritmo entre en la huella, y la prueba del tamaño máximo usaba la misma constante que debía probar (si la constante cambiaba, la prueba se ajustaba sola). Se cerraron, y sus 3 variantes quedaron detectadas. Ninguna mutación equivalente |

## Inspección contra el caso real (solo lectura del caso)

Con `datos/casos/caso-001/case.json` y su `orden_de_ajuste.json`, leídos con los lectores reales:

| Propuesta (t1 / t3 / t5 / t7) | Estado | Resultado | Ciclo |
|---|---|---|---|
| Línea base 82 / 45 / 45 / 10 | `accepted` | sin cambios | 206 s |
| Todo al máximo 110 / 60 / 70 / 30 | `corrected` | 110 / 60 / **41 / 5** | 240 s |
| 100 / 58 / 68 / 29 | `corrected` | 100 / 58 / **53 / 5** | 240 s |
| Todo al mínimo 30 / 15 / 25 / 5 | `corrected` | **51** / 15 / 25 / 5 | 120 s |
| 120 / 10 / 50.4 / 40 | `corrected` | 110 / 15 / 50 / 30 | 229 s |
| 82.5 / 45.5 / 44.5 / 10.49 | `corrected` | 83 / 46 / 45 / 10 | 208 s |
| 1e308 / −1e308 / 45 / 10 | `corrected` | 110 / 15 / 45 / 10 | 204 s |
| NaN en t1 | `invalid_input` | «debe ser un número finito» | — |

Son las cifras del análisis de F0. Javier Prado conserva lo propuesto y Los Frutales absorbe el ajuste, empezando por t7.

| Comprobación | Resultado |
|---|---|
| 20 000 propuestas al azar | 14 011 corregidas, 5 989 aceptadas, **0 rechazadas** (como se anticipó: en caso-001 los límites de los grupos son la suma de sus tramos) |
| Planes admisibles que no pasan la validación de nuevo | 0 |
| Corregir dos veces cambia algo | 0 |
| Tramo que más veces cambia en las corregidas | t7 (10 063), luego t5, t3 y t1: coherente con el orden |
| Velocidad | Unas 1 950 correcciones por segundo |
| `datos/` real | `case.json` sin cambios; se agregó solo `orden_de_ajuste.json`. `runs verify`: 10 íntegras, 0 alteradas, 3 desconocidas (las mismas de antes; `casos/` no entra en esa revisión) |

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Sin archivo de orden, mi primera versión daba tiempo en orden inverso, contra D18 (diseño al pie de la letra) | Corregido antes de las pruebas (F3-2), con pruebas que lo fijan |
| 2 | Con la regla de entrada de F1, una predicción negativa habría sido `invalid_input` | Opción `allow_negative` para el corrector (F3-1) |
| 3 | Dos mutaciones sobrevivieron (algoritmo en la huella; tamaño máximo del archivo) | Huecos reales cerrados con pruebas |
| 4 | Una prueba de cobertura mostró que las propuestas generadas casi no producían ciclos cortos (1 de 200), así que el reparto al dar estaba poco probado | Se agregó un tipo de propuesta cerca del mínimo: ahora 44 de 200 |
| 5 | Dos valores esperados que escribí estaban mal: un JSON anidado de 200 KB choca antes con el límite de 64 KiB, y la cuenta de omitidos era 404 y no 403 | Corregidos con la cuenta a la vista en la prueba |
| 6 | Una edición dejó el módulo sin el cierre de su documentación y un bloque de texto fue demasiado largo para la consola | Detectado por el formateador; corregido antes de seguir |
| 7 | `datos/` no está en git: el archivo de orden de caso-001 no queda versionado por sí solo | Su contenido completo está en esta acta |

## Límites

- El corrector no repara un verde de grupo con límites más estrictos que la suma de sus tramos (D11): lo rechaza con PLAN-05. En caso-001 eso no pasa; con otros cruces, F4 lo medirá en la cobertura.
- El orden de caso-001 es criterio del Product Owner, pendiente de revisión con el especialista de tránsito, igual que los límites de DEV03.
- Cuando el modelo se pase del ciclo, Los Frutales puede quedar en sus mínimos (25 s sur→norte y 35 s norte→sur): son los mínimos fijados en DEV03 para que la cola alcance a salir.

## Fase que sigue

F4: QA22 completo y cobertura (aceptados, corregidos y rechazados sobre un conjunto de propuestas, con los rechazados en el denominador), concordancia con el compilador de SUMO de DEV03 (todo plan admisible compila igual), caso-001 y pruebas de seguridad. Complejidad media-alta, esfuerzo mediano, riesgo medio, Sonnet alcanza.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
