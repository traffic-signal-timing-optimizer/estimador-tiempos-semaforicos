# Acta 2026-11-02: DEV19 · F2 (protocolo y demora de la cohorte con censura)

- **Tipo:** fase F2 de DEV19 (HU12; HU13; QA25). Seguida de F1, por pedido del Product Owner.
- **Decisiones que aplica:** D5 a D8 y D11 de `2026-11-02-dev19-f0-decisiones.md`.
- **Modelo:** Opus.
- **Datos:** sintéticos; las pruebas usan cifras calculadas a mano.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `dominio/protocol.py` | Modelo del contrato `protocol`, campo a campo: su esquema es **idéntico** al publicado (el contrato no cambia; siguen nueve). Agrega, sin tocar el esquema, que los carriles de la zona no se repitan |
| `evaluacion/errors.py` | `EvaluacionError`: no se pueden calcular las métricas; lleva código y motivo |
| `evaluacion/cohort.py` | Demora de cada vehículo de la cohorte (`timeLoss` + `departDelay`, con las dos partes) y su resumen total, por acceso y por movimiento, con censura |

## Cómo se mide la demora

| Estado del vehículo | Pérdida en ruta | Espera para entrar |
|---|---|---|
| Terminó | La de SUMO | La de SUMO |
| Sigue en la red al final | Lo acumulado (cota inferior) | La de SUMO |
| Nunca entró | 0 | La que registró SUMO o, sin registro, fin de la simulación menos su salida programada (cota inferior) |

- **Cohorte completa** (los N terminaron): media = suma / N, y sus dos partes.
- **Cohorte censurada:** **no hay media**. Solo la cota inferior (suma de lo acumulado / N, también dividida entre todos los pedidos) y los conteos de inconclusos y no insertados.
- **Cohorte vacía:** sin cifras (no se inventa un 0).
- Cada grupo (acceso o movimiento) tiene su propio estado: un acceso completo no queda censurado porque otro lo esté.
- El calentamiento se cuenta aparte y no entra en ningún denominador.
- **Nunca se calcula la media de los que terminaron.**
- Si la conciliación y los viajes no coinciden (un terminado sin viaje, un no insertado que sí salió), si falta un tiempo, si es negativo o si un movimiento no es del caso: `OUTPUT_INVALID`, sin cifras a medias.
- Esta versión mide solo la población `requested_depart_in_measurement_window` y la censura `complete_cohort_or_no_label`. Otra se rechaza con su motivo (`INPUT_SCHEMA`); no se inventa su regla.

## QA25 punto por punto

| QA25 pide | Cómo se cumple |
|---|---|
| Cohorte con terminado, inconcluso y no insertado | Prueba con los tres estados en dos movimientos, dos accesos y dos clases |
| Conciliar por identificador | Se parte de la conciliación por vehículo de DEV06, ya corregida en F1 para los no iniciados |
| N solicitado se conserva | Cada vehículo pedido está en la tabla una vez. Por acceso y por movimiento, los pedidos, terminados, inconclusos, no insertados y la suma de demoras dan el total |
| Ningún caso excluido sin registro | El calentamiento se informa con su conteo. La cohorte censurada sigue con todos sus vehículos y dividida entre los N |
| Evidencia: tabla de cohorte | `CohortDelay.vehicles`: identificador, movimiento, clase, acceso, estado, los dos tiempos y de dónde sale la espera |

La prueba con SUMO real (QA25 de integración) va en F4, junto con `evaluate_run`.

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | **65**: 39 del protocolo (esquema idéntico, ejemplo del contrato, 28 casos inválidos, al menos tan estricto como el de referencia) y 26 de la cohorte, entre ellas una propiedad con 300 grupos al azar |
| Suite completa | **4640 pasan, 1 se salta**. Formato, lint, tipos estrictos y reglas de capas sin observaciones |
| Mutaciones | **28**. 27 detectadas a la primera (3 se repitieron porque el formateador había cambiado el texto). Sobrevivió 1, y era un hueco real: no había prueba de un protocolo principal con solo un criterio de volumen. Se agregó y quedó detectada |

## Límites

- La media completa de una cohorte saturada no existe por diseño (censura). Es lo que pide el protocolo; DEC06 puede aprobar otra política antes de las etiquetas principales.
- La espera de un no insertado sin registro se calcula con el fin de la simulación; las carpetas nuevas (1.1.0) siempre tienen el registro de SUMO.
