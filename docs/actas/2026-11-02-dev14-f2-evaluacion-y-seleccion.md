Escrito para: el Product Owner (qué se hizo y qué se encontró) y el equipo técnico (reglas y verificación).

# DEV14 F2: probar los planes con SUMO y elegir la referencia

- **Fecha:** 2026-11-02
- **Plan y decisiones:** `2026-11-02-plan-dev14.md`, `2026-11-02-dev14-f0-decisiones.md` y `2026-11-02-dev14-f1-candidatos.md`
- **Historia y pruebas:** HU08; QA16 y QA18
- **Datos:** sintéticos en las pruebas (red de demostración). El caso-001 real se usó solo para leer; las corridas de la prueba corta se escribieron en una carpeta temporal, no en `datos/`.

## Qué se hizo, en simple

La herramienta ya puede **probar en SUMO cada plan de la lista y elegir el mejor**:

1. Convierte cada plan en un programa de semáforo, lo simula con las semillas de búsqueda (dos o tres «días» distintos con la misma demanda) y mide la demora de los vehículos.
2. Un plan **no puede ganar** si en alguna semilla la corrida falló, quedaron vehículos sin terminar, SUMO teletransportó vehículos, hubo choques o no se pudo medir la cola completa. Queda anotado por qué.
3. Ordena los planes que sí pueden ganar por su demora media. Si dos están a menos de epsilon, gana el de menos cola, después el de menos detenciones y por último el de vector menor.
4. Los mejores (los finalistas) se **repiten con otras semillas** reservadas, y gana el mejor de esa repetición. Así un plan no gana por suerte en sus primeras semillas.
5. Si ningún plan puede ganar, el resultado es «sin referencia», con el motivo.
6. Todo queda anotado en una **bitácora**. Si el computador se apaga o se suspende, la búsqueda sigue donde quedó, sin repetir corridas.
7. Corre varias simulaciones a la vez y, antes de lanzar cada una, revisa que quede memoria libre.

Todavía no se guarda la etiqueta publicada: eso es F3.

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/selection.py` | Reglas puras: `seed_outcome`, `failed_seed`, `score_candidate`, `rank`, `choose_finalists`, `select` y `SELECTION_RULE` |
| `src/semaforo/referencias/evaluation.py` | `run_search` con SUMO, `SearchSetup`, `SearchOutcome`, la bitácora, `search_identity` y `free_memory_gate` |
| `src/semaforo/trazabilidad/fs.py` y `store.py` | `replace_patiently`: reintento corto del renombrado al publicar (hallazgo 2) |
| `tests/unit/test_search_selection.py` | 55 pruebas de las reglas |
| `tests/unit/test_search_journal.py` | 35 pruebas de la bitácora y de las entradas, todas antes de correr SUMO |
| `tests/integration/test_search_sumo.py` | 13 pruebas con SUMO real sobre la red de demostración |
| `tests/unit/test_fs.py` y `test_run_store.py` | 6 pruebas del reintento |
| `tests/search_tools.py` | Ayudas compartidas de las pruebas |

## Reglas fijadas en esta fase

1. **Puntuación:** es la media, con igual peso por semilla, de la demora media de la cohorte (timeLoss + departDelay, s/veh). Todas las semillas tienen la misma cohorte pedida (DEV06), así que pesar por semilla o por vehículo da lo mismo. La cola (veh) y las detenciones por vehículo se promedian igual y solo sirven para desempatar.
2. **Elegibilidad:** el candidato tiene todas las semillas de la etapa y ninguna con problemas. Los problemas son: `run_failed`, `evaluation_failed`, `cohort_incomplete`, `teleports`, `collisions` y `zone_incomplete` (cola o detenciones sin medir completas). La regla está escrita en `SELECTION_RULE`, que va en la bitácora y luego en la etiqueta.
3. **Empate:** epsilon es la distancia a la mejor puntuación de los que quedan, con el límite incluido. Del grupo empatado sale el de menos cola, luego menos detenciones y luego el vector menor; se repite con los demás. El orden no depende del orden de entrada.
4. **Finalistas:** son los `finalist_count` primeros del orden de la búsqueda. Se reevalúan solo con `seeds.finalists`, y la referencia es el primero del orden con esas semillas; las de búsqueda no se mezclan. Si ningún finalista es elegible al reevaluarlo, no hay referencia (`no_eligible_finalist`). No se pasa a los siguientes candidatos: eso gastaría más presupuesto que el declarado.
5. **Semillas finales:** `seeds.final` nunca se usan en DEV14, y no entran en la identidad de la búsqueda.
6. **Coherencia con el protocolo:** los candidatos deben ser del escenario de la búsqueda y haberse generado con `search_budget`, `sampling_attempt_limit` y la primera semilla de búsqueda del protocolo. Si no, se rechazan antes de correr nada. La censura debe ser `complete_cohort_or_no_label`.
7. **Bitácora** (`journal_path`, una línea JSON por registro):
   - La primera línea es la identidad: caso, versión, escenario, versión de reglas, protocolo, presupuesto, epsilon, semillas de búsqueda y de finalistas, opciones de SUMO y huella de los candidatos.
   - Después se anotan los programas publicados, las carpetas de entradas apenas se crean y cada resultado por semilla.
   - Una bitácora de otra búsqueda, dañada, con rutas fuera de su carpeta, con registros repetidos o de más de 64 MiB se rechaza antes de correr.
   - Una última línea cortada se quita.
8. **Fallos:** una corrida que no termina bien o que no se puede medir es un resultado: la semilla queda descartada y se anota. Un error al preparar las entradas o el programa detiene la búsqueda, porque no es culpa del candidato.
9. **Paralelo y cancelación:**
   - Se usan hilos: cada corrida es un proceso de SUMO aparte.
   - `can_start` se consulta antes de cada corrida; `free_memory_gate` deja pasar con la memoria libre mínima y no bloquea si no se puede medir.
   - Con `cancel`, las corridas en marcha se cancelan, nada de eso se anota y el resultado sale `interrupted`, sin selección.

## Hallazgos

1. **Al seguir una búsqueda en el mismo segundo, la carpeta de entradas ya existía.** El nombre de la carpeta lleva la hora (en segundos) y la huella del contenido. Una búsqueda cancelada y retomada en el mismo segundo intentaba crear la misma carpeta y fallaba con `RUN_EXISTS`. **Arreglo:** cada carpeta de entradas se anota en la bitácora apenas se publica y se reusa al seguir. Además, ya no se crean carpetas repetidas.
2. **En Windows, con corridas en paralelo, publicar una corrida falló a veces con «acceso denegado».**
   - Pasó en 3 de 9 rondas de las pruebas de integración.
   - Un diagnóstico con reintentos medidos encontró 1 renombrado negado de 116, y se liberó en menos de 50 ms. No es un archivo heredado por la otra corrida, que habría durado toda esa corrida. Es un bloqueo pasajero, propio de otro programa (por ejemplo, el antivirus) que revisa los archivos recién escritos.
   - **Arreglo:** `replace_patiently` reintenta el renombrado hasta 40 veces, cada 50 ms (unos 2 s), solo por `PermissionError` y solo si el destino no existe. Se usa al publicar corridas y carpetas.
   - Después del arreglo, 5 de 5 rondas pasaron. Toca código de DEV00 y DEV08, con sus pruebas.
3. **Prueba corta con el caso-001 real** (B=2 más el plan vigente, 2 semillas de búsqueda, 2 finalistas con 2 semillas y 4 corridas a la vez): 8 corridas en 46 s.
   - **Plan vigente** (82/45/45/10): 10 teletransportes con la semilla 1001; con la 1002, limpio con 110,9 s.
   - **Plan 56/26/30/7** (ciclo de 143 s): limpio en las dos semillas, con 93,4 s de media. Fue el único elegible.
   - **Plan 56/30/70/30**: cohorte incompleta, 11 teletransportes y un choque.
   - **Al repetir el finalista** con las semillas 2001 y 2002: limpio con 93,9 s en una, y 2 teletransportes en la otra.
   - **Resultado:** «sin referencia» (`no_eligible_finalist`).

   **Lectura:** la herramienta hace lo que se pidió, pero la regla estricta de F0 (ni un teletransporte en ninguna semilla) **casi asegura «sin referencia» con 13 semillas de finalistas** en la demanda sintética actual. El piloto de F4 medirá cuánto pasa con 20 candidatos. Si se confirma, hay que decidir antes de DEV24 (DEC06) entre:
   - aceptar unos pocos teletransportes, con un tope por vehículo;
   - bajar la demanda sintética;
   - revisar la red, porque los atascos nacen en el borde corto de Javier Prado (ver DEC04).
4. **Mutación equivalente por Python 3.12:** desde Python 3.12, `sum()` de números con decimales ya suma con compensación y da lo mismo que `math.fsum`. Cambiar uno por otro no se detecta. Se dejó `fsum` porque no depende de la versión de Python.

## Verificación

- **Pruebas:** 109 nuevas: 55 de reglas, 35 de bitácora, 13 de integración con SUMO y 6 del reintento.
  - QA16 de integración: la búsqueda completa evalúa a todos y elige referencia; con la misma bitácora no corre nada y da lo mismo; desde cero da la misma referencia; un escenario saturado da `no_eligible_candidate`.
  - Fallos: una corrida fallida queda como `run_failed` y una que no se puede medir, como `evaluation_failed`. Las dos quedan anotadas y su candidato no gana.
  - QA18: cada etapa usa solo sus semillas, las finales nunca se corren y el protocolo rechaza semillas compartidas.
  - Cancelar y seguir da lo mismo que sin cortes. También se prueban la espera por permiso, la línea cortada y las bitácoras ajenas o dañadas.
- **Puerta completa:** `scripts/check.ps1`: ruff, formato y pyright estricto sin observaciones; 4902 pruebas pasan y 1 se salta (4903 en total); contratos 43/43; ningún archivo oculto.
- **Mutaciones:** 71 en total.
  - **Reglas** (`selection.py`): de 39, 32 se detectaron a la primera y 7 sobrevivieron.
    - 5 eran huecos reales, cerrados con pruebas: censura con media, cola incompleta con media, media de una semilla, cola antes que detenciones y revisión de etapa.
    - 1 era código de más: contar problemas solo de los no elegibles, cuando los elegibles nunca tienen. Se simplificó.
    - 1 era equivalente: `sum` frente a `fsum` (hallazgo 4).
    - Resultado final: 37 de 37 detectadas.
    - Una pasada intermedia se descartó porque una prueba fallaba sin mutación. Ese resultado no valía: se corrigió la prueba y se repitió con todo en verde.
  - **Ejecución y bitácora** (`evaluation.py`, `fs.py`): de 31, 30 se detectaron a la primera.
    - La sobreviviente (tratar una corrida fallida como medida) se cerró con 2 pruebas de integración.
    - Una mutación más, no atrapar el error de medición, también se detectó.
    - Resultado final: 32 de 32.
- **Caso real:** la prueba corta del hallazgo 3. Sus corridas (196 MB) se borraron de la carpeta temporal al terminar.

## Siguiente

F3: publicar las etiquetas en el contrato `label` v1.0, con su traza, su manifiesto y el informe de cobertura, de solo lectura en `datos/derivados/referencias/`. Complejidad media, esfuerzo medio, riesgo medio, con Opus.
