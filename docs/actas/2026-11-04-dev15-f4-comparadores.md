Escrito para: el Product Owner (qué se guarda y qué cambió en la búsqueda) y el equipo técnico (contrato, reglas y verificación).

# DEV15 F4: publicar los comparadores y ofrecerlos a la búsqueda

- **Fecha:** 2026-11-04
- **Plan y decisiones:** `2026-11-03-plan-dev15.md` y `2026-11-03-dev15-f0-decisiones.md` (D8)
- **Historias:** HU08 y HU12. QA17 y QA16.
- **Datos:** pruebas con datos sintéticos; el caso-001 real solo se leyó. Las carpetas del caso real se publicaron en una carpeta temporal, no en `datos/`.

## Qué se hizo, en simple

1. **Los comparadores de un escenario se guardan en una carpeta que nadie puede modificar después**, igual que las etiquetas de DEV14. Ahí quedan el plan vigente (con su fuente) y el plan de Webster (con su aplicabilidad y, si no aplica, el motivo).
2. **Webster y el plan vigente pueden entrar a la búsqueda de DEV14** como planes adicionales que no gastan el presupuesto B. Un Webster que no aplica no entra.
3. **`runs verify` revisa esas carpetas**, como ya revisa las etiquetas.
4. **Se corrigió un error de Webster** que la auditoría encontró (A02): con un acceso sin flujo, el cálculo lanzaba un error técnico. Ahora da un plan o un «no aplicable» con su motivo.

## Qué se guarda y dónde

`datos/derivados/comparadores/<caso>/<AAAAMMDDTHHMMSSZ>_<huella8>/`, con tres archivos de solo lectura:

| Archivo | Contenido |
|---|---|
| `comparadores.json` | el plan vigente (duraciones, ciclo, fuente, confirmación, carpeta del programa y reglas del caso que incumpla); el plan de Webster (estado, plan propuesto, ciclo que da la fórmula, recorrido crítico y motivos) |
| `parametros.json` | los parámetros de Webster con los que se calculó, todavía provisionales |
| `manifiesto.json` | caso, versión, escenario, huellas de los dos archivos, estado de Webster y de qué red es |

Una carpeta por escenario. `read_comparators` revisa que la carpeta tenga exactamente esos archivos, que ninguno cambió y que el manifiesto coincida con el contenido y con los parámetros.

## Decisiones de F4

**F4-1. Un Webster que no cumple las reglas se publica igual, pero no entra a la búsqueda.** El plan que Webster propuso queda registrado con las reglas que incumple (HU12: «fallos no reemplazados»). A la búsqueda solo pasa un plan de Webster aplicable.

**F4-2. El plan vigente siempre entra a la búsqueda**, y la búsqueda lo excluye con sus reglas si las incumple, como ya hacía.

**F4-3. Orden y duplicados.** Los candidatos auxiliares van primero: vigente y luego Webster. Si el plan de Webster es igual al vigente, queda como «duplicado» y se evalúa una sola vez. Una copia muestreada de cualquiera de los dos también es un duplicado.

**F4-4. Lo ya publicado sigue valiendo.** La traza de candidatos incluye la clave `webster` solo si se dio un plan de Webster. Sin él es idéntica a la de antes. Se comprobó con el piloto de DEV14: la búsqueda sin Webster da la misma huella de candidatos que la etiqueta publicada. Con Webster, la identidad de la búsqueda cambia a propósito.

**F4-5. La cobertura de la etiqueta informa el estado de Webster** (`webster`: ausente, incluido, excluido o duplicado). Solo cambia en las etiquetas nuevas.

**F4-6. Un acceso sin flujo en el recorrido de Webster (arreglo de A02).** Si un carril del recorrido no tiene flujo, no pide verde: su tramo queda en su mínimo. El ciclo del plan puede pasar el que da la fórmula, y las reglas del caso lo revisan después. Ejemplo calculado a mano, con N 1 200 y E 0: Webster da 51 s, el plan da 43 s a N y 10 s a E (su mínimo), y el ciclo es de 61 s, dentro de los 40 a 100 s del caso. Si todos los accesos están en cero, sigue siendo «no aplicable: sin demanda».

## Resultado con el caso real (ESC-SINT-001, solo lectura)

| Saturación | Webster | Búsqueda con 20 de presupuesto |
|---|---|---|
| 1 800 (la elegida) | no aplicable: ciclo de 106,6 s por debajo del mínimo | 21 candidatos (el vigente y 20 de la muestra); Webster ausente |
| 1 500 | aplicable: 108 / 26 / 25 / 6, ciclo de 189 s | 22 candidatos (vigente, Webster y 20 de la muestra); presupuesto usado 20 |

Las carpetas de comparadores se publicaron en una carpeta temporal y se volvieron a leer con éxito.

## Auditoría del 2026-11-04 (Codex)

Hay un informe en `docs/auditorias/` que no es mío y no está en el repositorio. Esto es lo que se hizo con él en esta fase:

| Hallazgo | Estado |
|---|---|
| A02 Webster con un acceso en cero lanzaba `KeyError` | **Corregido** (F4-6), con 3 pruebas |
| A04 la puerta contradecía la exclusión de `docs/presentaciones/` | **Corregido**: la comprobación de `check.ps1` exceptúa solo esa carpeta; un archivo de código oculto sigue haciendo fallar la puerta |
| A05 direcciones invertidas y orden de DEV24 | **Corregido** en las actas, con una nota de enmienda en cada una. Las cifras no cambian |
| A01 la identidad de la búsqueda no cubre la demanda ni la medición (alta) | **Pendiente.** Es de DEV14 y necesita una fase propia |
| A03, A06, A07, A08 | Pendientes |

**A01 es la más importante.** Si se edita una demanda o la definición de medición y se reutiliza una bitácora, se pueden mezclar resultados viejos con uno nuevo. No afectó al piloto publicado: sus 102 manifiestos tienen los mismos insumos. Recomiendo corregirla antes de ampliar las búsquedas, con una fase propia y su autorización.

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/comparators.py` | modelo y archivos publicados, `compute_comparators`, `publish_comparators`, `read_comparators` |
| `src/semaforo/referencias/search.py` | `webster_plan` como candidato auxiliar; estados `absent`, `included`, `excluded` y `duplicate` |
| `src/semaforo/referencias/label.py` | la cobertura informa el estado de Webster |
| `src/semaforo/referencias/baselines.py` | arreglo de A02 |
| `src/semaforo/app/integrity.py` | familia `comparators` para `runs verify` |
| `scripts/check.ps1`, `.gitignore` | excepción para `docs/presentaciones/` |
| `tests/unit/test_comparators.py` | 37 pruebas |
| `tests/unit/test_search_candidates.py` | 9 pruebas nuevas |
| `tests/unit/test_baselines.py` | 3 pruebas nuevas (A02); las ayudas pasaron a `tests/baselines_tools.py` |

## Verificación

- **Pruebas:** 49 nuevas: 37 de comparadores, 9 de búsqueda y 3 del arreglo de A02.
- **Mutaciones:** 23 daños a propósito sobre el código nuevo.
  - En la primera pasada se detectaron 18 de 23.
  - Los 5 que sobrevivieron eran huecos reales y se cerraron con pruebas:
    - nunca se publicaba un plan vigente que incumpla reglas;
    - no se probaba el límite de tamaño de lectura;
    - dos comprobaciones del manifiesto (caso y versión) estaban tapadas por otra;
    - un manifiesto incompleto se rechazaba por otra causa.
  - Resultado final: 23 de 23.
- **Mutaciones de F3 de nuevo**, tras tocar `_split` por A02: 18 de 18 y 1 más del arreglo, todas detectadas.
- **Puerta completa:** ruff, formato y pyright estricto, sin observaciones. 5071 pruebas pasan y 1 se salta (solo corre fuera de Windows). Contratos 43/43; ningún archivo oculto.

## Siguiente

F5: caso real con los comparadores de ESC-SINT-001 y de un conjunto de escenarios sintéticos, tabla de sensibilidad a la saturación, control con SUMO del plan de Webster (con 1 500) con 3 semillas, pruebas de seguridad de los comparadores, mutaciones e inspección contra la documentación. Complejidad media, riesgo medio, con Opus.
