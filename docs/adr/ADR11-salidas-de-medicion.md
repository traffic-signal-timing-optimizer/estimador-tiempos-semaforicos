# ADR11: Salidas de medición de las corridas preparadas (FCD en la zona y viajes no iniciados)

- **Estado:** Aceptada (2026-11-02), por delegación del Product Owner («analiza y toma la mejor decisión»)
- **Tipo:** P (decisión de este equipo; amplía lo que produce una corrida de DEV06/DEV07)
- **Fecha de registro:** 2026-11-02
- **Fuente:** `documentacion/documentos/03_Pruebas_y_operacion.md`, «Protocolo de medición y control del sesgo» y «Viajes inconclusos y demanda no insertada»; `02_Requisitos_y_plan.md`, DEV19
- **Relacionado con:** `docs/actas/2026-11-02-dev19-f0-decisiones.md`

## Decisión

Las corridas que se lanzan desde una carpeta de entradas de DEV06 (`run_inputs`) piden a SUMO, además de lo de DEV07:

1. `--tripinfo-output.write-undeparted true`: un registro por vehículo cargado que nunca entró a la red (`depart="-1"`, con su `departDelay` acumulado).
2. `--fcd-output outputs/fcd.xml` limitado a las calles de aproximación del caso (`--fcd-output.filter-edges.input-file inputs/zona_fcd.txt`) y a los atributos `id`, `lane` y `speed`, sin omitir pasos vacíos.

La carpeta de entradas nueva lleva `zona_fcd.txt` (una línea `edge:<id>` por calle de aproximación del caso, en orden) y su manifiesto la declara en `files`, en `required_outputs` y en `measurement_edges` (versión 1.1.0 del manifiesto de entradas, que no es uno de los nueve contratos). Las carpetas 1.0.0 siguen ejecutándose como antes; sus métricas de cola y detenciones quedan «no disponibles», con motivo.

El corredor genérico de DEV00 (réplica de la simulación del equipo) no cambia: sus argumentos por omisión son los mismos.

## Motivo

1. **El protocolo pide una definición exacta:** cola = vehículos a ≤ 0.1 m/s en los carriles de la zona, en cada tick; detención = paso de > 0.1 a ≤ 0.1 m/s. Solo una salida con la velocidad de cada vehículo en cada paso permite calcularla tal cual. La FCD lo hace.
2. **Cabe holgadamente en los topes.** Medido con el caso real (ESC-SINT-001, 1780 vehículos, 2100 s): 3,7 MB de FCD y 7,1 s de corrida, contra un tope de 512 MiB de salidas.
3. **El protocolo pide registrar los no iniciados «si la versión lo soporta».** SUMO 1.27.1 lo soporta (`sumo --help` y una corrida con `--max-num-vehicles 5`: 577 registros con `depart="-1"`).
4. **No toca la evidencia anterior.** Solo cambian las corridas desde carpetas de entradas nuevas.

## Alternativas descartadas

- **Detectores de carril (e2).** Su «atasco» usa su propio umbral y la cercanía entre vehículos; cuenta por detector, y dos detectores que se solapan cuentan dos veces. No es la definición del protocolo.
- **`queue-output`.** Da la longitud de la cola en metros por carril con su propio criterio de detención; tampoco es la definición.
- **`waitingTime` y `waitingCount` del `tripinfo`.** Son de todo el viaje, no de la zona; el documento 03 dice que no equivalen a la demora de control.
- **FCD de toda la red.** Más grande sin necesidad; la zona es la aproximación al cruce.

## Impacto

- `simulacion/prepare.py`: archivo `zona_fcd.txt`, `measurement_edges` y salidas requeridas nuevas.
- `simulacion/runner.py`: opción de medición para `run_simulation`; la coherencia cuenta aparte los viajes no iniciados.
- `simulacion/reconcile.py`: un viaje con `depart="-1"` es `not_inserted`, no `unfinished`.
- `evaluacion/`: lee `outputs/fcd.xml` (DEV19 F3).
- **Límite:** la zona es la calle de aproximación declarada en el caso. Si la cola se extiende a la calle anterior, esa parte no se ve. La zona definitiva depende de DEC04.

## Enmienda del 2026-11-02 (DEV19 F5): la zona es la aproximación modelada

La inspección con el caso real mostró que varias calles de entrada del caso-001 son tramos minúsculos de OpenStreetMap. La entrada de Javier Prado desde el este (`279893869#6`) mide 3.85 m; `282567283#5` mide 0.20 m y `563085958` mide 0.13 m. Con la zona limitada a esas calles, la cola de esos accesos no se veía: 14 vehículos en promedio en toda la zona y 0.2 detenciones por vehículo, aun en corridas con 240 s de demora media.

**Cambio:** la zona de una carpeta de entradas (manifiesto **1.2.0**) es, para cada movimiento, la lista de calles de su ruta desde el inicio hasta la de sus carriles de entrada, inclusive. Sin ruta, es solo esa calle. Cada calle queda con el acceso de su movimiento (`measurement_access`), y una calle que resulte de dos accesos se rechaza. La evaluación usa ese mapa para el desglose por acceso.

- **Largo de la zona:** el del área que modelan las rutas del equipo. No se inventó ninguna distancia. La zona definitiva sigue dependiendo de DEC04.
- **Con el caso-001:** 21 calles y 58 carriles. La FCD ocupa hasta 27 MB por corrida, contra un tope de 512 MiB.
- **Carpetas anteriores:** las 1.1.0 siguen siendo válidas, con la zona de las calles de entrada.

## Prueba de aceptación

- Una corrida con SUMO real desde una carpeta 1.1.0 produce `outputs/fcd.xml` solo con las calles de la zona y un paso por tick, y el `tripinfo` incluye los no iniciados.
- Una carpeta 1.0.0 se sigue ejecutando igual que antes.
- La conciliación deja como `not_inserted` a un vehículo con `depart="-1"`.
