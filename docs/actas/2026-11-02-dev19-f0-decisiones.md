# Acta 2026-11-02: DEV19 · F0 (decisiones)

- **Tipo:** fase F0 de DEV19 (HU12; HU13; P0, tamaño L). Dependencias: DEV07 y DEV13, cerradas.
- **Autorización:** el Product Owner pidió ejecutar todas las fases seguidas y delegó las decisiones pendientes del plan («analiza y toma la mejor decisión»). Paro solo si hace falta su confirmación, si hay errores que bloqueen o si cambia el alcance.
- **Modelo:** Opus.
- **Datos:** sintéticos. Se copió a la carpeta temporal la carpeta de entradas real `datos/derivados/entradas/ESC-SINT-001/20261031T163018Z_ea425f32` para medir las salidas de SUMO; el original no se tocó.

## Hallazgos que cambian el plan

1. **Ya existe un contrato publicado para estos parámetros: `protocol`.** Define el umbral de cola (`queue_speed_threshold_mps`), el de detención (`stop_speed_threshold_mps`), los carriles de la zona (`zone_lane_ids`), el muestreo (`queue_sampling_s`), la población (`cohort_policy`), la censura (`censoring_policy`) y la tolerancia numérica. Pero no hay un modelo en `src` que lo lea. DEV19 lo crea (`dominio/protocol.py`) **sin cambiar el contrato**: siguen siendo nueve. No se inventan parámetros nuevos.
2. **El MAE sí está definido, en I5:** «MAE del ciclo y cada verde, segundos; comparar con mediana; reportar denominadores y faltantes». En el plan recomendé otra cosa (volúmenes, que son I2 y de DEV23). Manda la documentación: el MAE de DEV19 es el de I5.
3. **SUMO 1.27.1 puede registrar los no iniciados** (`--tripinfo-output.write-undeparted`). El protocolo pide usarlo si la versión lo soporta. Comprobado con `sumo --help` y con una corrida limitada a 5 vehículos en la red: 577 registros con `depart="-1"` y su espera acumulada (`departDelay`).
4. **La conciliación de DEV06 se equivocaría con esos registros:** hoy un viaje con llegada `-1` es «inconcluso», y un no iniciado también tiene llegada `-1`. Hay que corregirlo junto con la salida nueva.

## Medición de la salida nueva (caso real, solo en la copia temporal)

| Qué | Resultado |
|---|---|
| Corrida | 1780 vehículos, 2100 s, semilla 100, código 0, 7,1 s |
| FCD limitada a las 7 calles de aproximación del caso, con `id`, `lane` y `speed` | **3,7 MB**, 37 862 registros, 2100 pasos (uno por tick, también los vacíos) |
| Tope de salidas de una corrida | 512 MiB: margen de más de 100 veces |
| `tripinfo` con no iniciados | 1780 registros (ninguno sin entrar en esta demanda) |

La FCD de la zona incluye también los carriles internos del cruce (los que empiezan con `:`). No se cuentan: la zona son los carriles del protocolo.

## Decisiones

| # | Decisión | Por qué |
|---|---|---|
| D1 | **Cola y detenciones salen de la FCD de SUMO,** limitada a las calles de aproximación del caso y a `id`, `lane` y `speed` (ADR11, aceptado por delegación) | Es la única salida con la velocidad de cada vehículo en cada tick: permite aplicar la definición del protocolo tal cual. Detectores y `queue-output` usan otros umbrales |
| D2 | **Se registran los no iniciados** (`write-undeparted`). La coherencia de la corrida cuenta aparte los viajes con `depart="-1"` y la conciliación los deja como `not_inserted` | Lo pide el protocolo; sin él, la espera de los que nunca entraron se pierde |
| D3 | Las salidas nuevas **solo para corridas desde carpetas de entradas** (`run_inputs`). El corredor de DEV00 no cambia por omisión | No altera la réplica ni la evidencia anterior |
| D4 | La carpeta de entradas nueva (manifiesto 1.1.0) lleva `zona_fcd.txt` y declara `measurement_edges`. Las carpetas 1.0.0 se siguen ejecutando; su cola queda «no disponible» con motivo | Nada se sobrescribe; lo viejo no se rompe |
| D5 | **Modelo del contrato `protocol`** en `dominio/protocol.py`, idéntico al publicado y probado contra su esquema y el modelo de referencia. Se admiten la población `requested_depart_in_measurement_window` y la censura `complete_cohort_or_no_label`; otra se rechaza con motivo (no se inventa su regla). Un protocolo `draft` sirve para desarrollo; el resultado dice el estado | Congelar el protocolo es de DEC06 y DEV24, no de DEV19 |
| D6 | **Demora por vehículo = `timeLoss` + `departDelay`**, con las dos partes por separado. La media completa = suma / N solicitados, **solo si los N terminaron** | Protocolo, «Definición propuesta» |
| D7 | **Cohorte incompleta = censurada:** no hay media completa. Se informa la **cota inferior** = suma de lo acumulado / N: el inconcluso aporta lo que llevaba; el no iniciado, su espera registrada por SUMO o, si no hay registro (carpeta 1.0.0), fin de la simulación menos su salida programada | Protocolo: «tiempos acumulados como límites inferiores, nunca como resultado completo» |
| D8 | **Población:** la cohorte (`en_cohorte = sí`). El calentamiento se cuenta aparte, no entra en las medias | Protocolo, «Población y horizontes» |
| D9 | **Cola:** en cada tick de muestreo dentro del intervalo de medición [inicio, fin) de la cohorte, vehículos (todos, también los de calentamiento) en los carriles de la zona con velocidad ≤ umbral. Media en el tiempo, máximo, total y por acceso. **Cobertura** = ticks presentes / ticks esperados; si falta alguno, la cola queda «incompleta», sin valores. El muestreo debe ser múltiplo del paso | Es un estado de la vía, no de la cohorte. Los ticks vacíos cuentan como 0 (QA27: «ceros incluidos»), pero un tick que falta no se rellena |
| D10 | **Detenciones:** de los vehículos de la cohorte, en toda la corrida y dentro de la zona: paso de > umbral a ≤ umbral entre dos ticks seguidos. **Regla de estado inicial:** un vehículo que aparece en la zona ya detenido (sin registro en el tick anterior) cuenta una detención. Total, por vehículo solicitado y por acceso; si la cohorte está censurada, es cota inferior | El protocolo pide fijar la regla del estado inicial; la red empieza vacía, así que aparecer detenido es entrar a una cola |
| D11 | **Acceso** = calle de aproximación del movimiento (`approach_id`). El caso se comprueba contra la huella del manifiesto | Desglose por acceso de HU13 e I6 |
| D12 | **Comparar (QA26):** solo con la misma cohorte (mismo escenario y mismos N). Dos completas: diferencia, con la tolerancia del protocolo. Una completa y otra censurada: solo se declara menor a la completa si su media es menor que la cota inferior de la otra; si no, «indeterminado». Dos censuradas: «indeterminado». **Nunca** se usa la media de los que terminaron | QA26: no declarar mejor por la media sesgada de completados |
| D13 | **MAE (I5):** del ciclo y del verde de cada grupo, en segundos, entre el plan estimado y el de referencia, reconstruidos con DEV13 (sin doble conteo). Denominadores: pares, evaluados, sin predicción y sin referencia | Hallazgo 2 |
| D14 | **Costos (I7) e intervalos de confianza (QA28) quedan en DEV20,** como dice la matriz | El protocolo ya trae `confidence_level` y `bootstrap_repetitions` para DEV20 |
| D15 | **Sin comando ni artefacto publicado nuevo.** `evaluate_run` devuelve las métricas de una corrida publicada (modelo JSON) para DEV14 y DEV20 | El diseño pone `evaluate(run_set, protocol)` en DEV20; DEV19 es su núcleo |
| D16 | **Lectura segura de la FCD:** en flujo, sin DTD ni entidades, con tope de bytes (también `.gz`) y raíz `fcd-export`; la memoria crece con los vehículos, no con el archivo | Mismo criterio que el `tripinfo` de DEV07 |
| D17 | **Archivos:** `evaluacion/cohort.py` (demora y censura), `evaluacion/metrics.py` (cola, detenciones, comparación, MAE), `evaluacion/fcd.py` (lectura) y `evaluacion/run_metrics.py` (`evaluate_run`). `simulacion/cohort.py` genera la cohorte; `evaluacion/cohort.py` la mide | Matriz más la separación de responsabilidades |
| D18 | **Datos:** sintéticos. En F5 se preparan entradas nuevas del caso-001 y se corre SUMO; no se borra ni se sobrescribe nada de `datos/` | Reglas del proyecto |

## Fases (ajustadas)

| Fase | Qué |
|---|---|
| F1 | Salidas de medición (ADR11): `prepare`, `runner`, `run_inputs`, `tripinfo` ampliado (`timeLoss`, `departDelay`, `waitingTime`, `waitingCount`) y conciliación de los no iniciados |
| F2 | Protocolo (`dominio/protocol.py`) y cohorte con censura (`evaluacion/cohort.py`). QA25 |
| F3 | FCD, cola y detenciones (`evaluacion/fcd.py`, `metrics.py`). QA27 |
| F4 | Comparación (QA26), MAE (I5) y `evaluate_run` |
| F5 | Corrida real del caso-001, inspección, mutaciones, cierre |

## Límites

- La zona es la calle de aproximación declarada en el caso: la cola que llega a la calle anterior no se ve. Depende de DEC04.
- El protocolo de caso-001 será un borrador (`draft`) del equipo, no un protocolo congelado.
- La definición de cola (0.1 m/s) es del protocolo; su equivalencia con la medición manual se comprueba en campo.
