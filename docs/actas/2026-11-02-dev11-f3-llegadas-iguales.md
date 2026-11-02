# Acta 2026-11-02: DEV11 · F3 (llegadas iguales para todos los comparadores)

- **Tipo:** fase F3 de DEV11 (HU06). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D8 de F0 (y D13, el límite de vehículos).
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/datos/scenario_demand.py` | Escribe y lee las llegadas de un escenario en un archivo de texto fijo (`render_demand`, `parse_demand`), genera la cohorte con la de DEV06 y enlaza el archivo en `demand_artifact` (`materialize_demand`, `materialize_all`), y las entrega a quien compare con la huella comprobada (`load_demand`) |
| `tests/unit/test_scenario_demand.py` | 62 pruebas |

No se modificó `simulacion/cohort.py`: la cohorte de DEV06 se reutiliza tal cual.

## El archivo de llegadas

`demanda/<escenario>.csv`, UTF-8, saltos `\n`, una fila por vehículo:

```
vehicle_id,movement_id,vehicle_class,depart_s,in_cohort
N_S.cal.bus.1,N_S,bus,0.5,false
N_S.car.1,N_S,car,12.25,true
```

Va en el orden de la cohorte (hora de salida y luego identificador). `in_cohort` es `false` para los del calentamiento (que se simulan, pero no son cohorte). El escenario enlaza el archivo con ruta, identificador (`<escenario>-demand`) y huella SHA-256.

## Qué se comprueba al leerlo

`parse_demand` rechaza, con su motivo y la línea: archivo de más de 32 MiB; que no sea UTF-8; marca BOM; retornos de carro; que no termine en salto de línea; encabezado distinto; fila que no tenga cinco campos; identificador de vehículo sin el formato `<movimiento>.<clase>.<n>` (o `<movimiento>.cal.<clase>.<n>`); movimiento o clase con caracteres fuera de letras, números, guion bajo y guion; hora que no sea un número finito mayor o igual que 0; `in_cohort` distinto de `true` o `false`; vehículos repetidos; filas fuera de orden; más de 200 000 vehículos.

`load_demand` (lo que usa cada comparador) comprueba primero la huella y después el formato, y además que cada vehículo sea de un movimiento del escenario y que su marca de cohorte corresponda a su hora (`in_cohort` equivale a salir en `warmup_s` o después). Un cambio de un solo byte o el archivo de otro escenario dan HASH_MISMATCH.

## Mismas llegadas para todos

- Dos comparadores que reciben el mismo escenario y los mismos bytes obtienen la misma lista de vehículos, igual a la cohorte generada de nuevo con DEV06 (probado en los 10 escenarios del ejemplo).
- Dos repeticiones de una misma perturbación comparten la demanda (mismos totales por movimiento y clase) pero no las horas de salida; dos perturbaciones tienen demandas distintas.
- Generar dos veces da exactamente los mismos bytes.

## Verificación

- **Pruebas:** 62 nuevas. Suite completa: **2504 pasan, 1 se salta** (una prueba que solo corre fuera de Windows). Formato, lint, tipos, contratos y reglas de capas sin observaciones.
- **Mutaciones:** 37 cambios a propósito (formato, límites, bordes, banderas invertidas, orden, huellas, conteos, mensajes). **31 se detectaron de inmediato, 5 no se aplicaron por un error mío al escribir las pruebas de ensayo (ver hallazgo 2) y 1 sobrevivió**: que el límite del conjunto contara solo los vehículos de la cohorte y no los del calentamiento. Se cerró con una prueba con calentamiento y las 37 quedan detectadas.
- **Tamaño real:** el conjunto más grande permitido (2000 escenarios) son 382 800 vehículos, 11 MiB de texto y 1.6 s para generarlo. El tope de 2 millones de vehículos por conjunto deja unos 60 MiB como máximo.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Al escribir el código, la herramienta convirtió el texto `﻿` en el carácter invisible real (el mismo problema de DEV09) | Se reemplazó por `\N{ZERO WIDTH NO-BREAK SPACE}` y se revisaron los siete archivos nuevos de DEV11: no queda ningún carácter de control ni invisible |
| 2 | La herramienta de Bash también colapsa las dobles barras invertidas de un comando; las mutaciones que buscaban `\r` o `\n` figuraban como «omitidas» | Se armaron con `chr(92)`; las cuatro se aplicaron y se detectaron. Se amplió la nota guardada en la memoria |
| 3 | Un error al generar la cohorte (más de 200 000 vehículos) no decía de qué escenario era | Se envuelve con el nombre del escenario como prefijo y como campo |
| 4 | El límite de 2 millones de vehículos por conjunto no estaba en F0 | Es un tope de memoria para publicar (los archivos se arman en memoria antes del renombrado). No cambia el alcance; queda en el código y en esta acta |
| 5 | Ninguna dependencia nueva; `schemas/` y `simulacion/` sin cambios | — |

## Límites

- El archivo de llegadas guarda lo que dice la cohorte (movimiento, clase y hora). La ruta de cada vehículo y su tipo de SUMO se agregan al preparar las entradas (DEV06), no aquí.
- `load_demand` no recalcula la cohorte; eso lo hace la lectura del conjunto completo en F4, que sí conoce el caso cuando se pide.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
