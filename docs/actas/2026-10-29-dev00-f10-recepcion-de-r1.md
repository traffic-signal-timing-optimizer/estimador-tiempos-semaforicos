# Acta 2026-10-29: DEV00 · F10 (recepción oficial de R1)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha de ejecución:** 2026-10-27, 22:10 hora de Lima (2026-10-28 03:10 UTC). **Fecha del acta:** 2026-10-29.
- **Autorización:** el Product Owner copió a su carpeta de SUMO los tres archivos de la candidata («Ya copie los archivos»), avisó «SUMO Listo» y autorizó la recepción («Ejecuta la recepción»).
- **Código:** F10 no cambia código. Usa las herramientas de F2 a F8, igual que F9.
- **Revisión del Product Owner (QA23 y QA24):** hecha el 2026-10-29 sobre esta recepción.
- **Siguiente paso:** cierre de DEV00 (acta `2026-10-29-dev00-cierre.md`).

## Qué se hizo

```powershell
python -m semaforo case receive --source <carpeta de SUMO del Product Owner> --config frutales_solo.sumocfg --case-id frutales-r1
python -m semaforo case publish-report --reception-id 20261028T031008Z_15e51d6c
python -m semaforo case compare --before 20261020T215129Z_be52433f --after 20261028T031008Z_15e51d6c
```

| Dato | Valor |
|---|---|
| Recepción | `20261028T031008Z_15e51d6c` |
| Copia (`snapshot_id`) | `15e51d6c…` (copia nueva) |
| Versión de SUMO | 1.27.1 |
| Estado propuesto | `with_findings` |
| Corrida base | `20261028T031009Z_simulation_f7bdbd72`, `succeeded`, código de salida 0 |
| Informe público | `docs/recepcion/20261028T031008Z_15e51d6c.md` |

Los archivos de entrada recibidos son los de la candidata `datos/propuestas/2026-10-25-clases-y-red-qa23/`, cuyos cambios y decisiones están en el acta `2026-10-25-propuesta-clases-vehiculares.md`. Según ADR09, el detalle de los hallazgos queda en `datos/derivados/recepcion/20261028T031008Z_15e51d6c/hallazgos.md`, ignorado por git.

## Resultado de la corrida base (semilla 2026, 7200 s)

| Dato | R0 (`20261020T215129Z_be52433f`) | R1 |
|---|---|---|
| Movimientos del semáforo | 53 | 23 (+3 señales de espera de los giros a la izquierda) |
| Vehículos declarados | 2520 | 2523 |
| Vehículos que entran a la red | 2254 | 2523 |
| Vehículos que no llegan a entrar | 266 | 0 |
| Viajes terminados | 2245 | 2523 |
| Demora media de entrada | 195,94 s | 96,36 s |
| Teletransportes | 0 | 7, todos por atasco |
| Colisiones | 0 | 0 |
| Avisos de SUMO | 3 | 16 |

`case compare` encuentra 105 cambios entre R0 y R1: 3 en los archivos de entrada, 21 en el inventario, 72 en la auditoría (demanda por tipo de vehículo, rutas y tipos nuevos) y 9 en la corrida.

**Hallazgos de la recepción.**
- **Teletransportes (7):** vienen de la moto que se detiene en el giro a la izquierda de Javier Prado de oeste a este y de los atascos que provoca. Investigado el 2026-10-29 y aceptado como limitación (ver «Limitaciones aceptadas para R1»).
- **Avisos de SUMO (16):** 14 son los teletransportes (inicio y fin). Los otros 2 son del programa del semáforo:
  - el enlace 9 (M10, entrada menor sin vehículos de la demanda) nunca tiene verde;
  - la señal de espera 23 (M14-espera) pasa de verde a rojo sin amarillo al entrar a la fase 4.
- **`NO_END_TIME`:** el `.sumocfg` no fija `end`. El runner pasa el límite de 7200 s, igual que en R0.

## Pruebas de aceptación

| Prueba | Qué se comprobó | Resultado |
|---|---|---|
| QA07 | Corrida base `succeeded` con salidas válidas; originales intactos | Cumplida. Los tres archivos de entrada de la carpeta del Product Owner tienen los mismos SHA-256 que el informe público (verificado de nuevo el 2026-10-29). |
| QA09 (con datos reales) | La corrida base se puede reproducir | Cumplida. Otra corrida de SUMO, hecha fuera del repositorio con los mismos tres archivos de entrada (mismos SHA-256) y la semilla 2026, produce los mismos 2523 viajes en `tripinfo.xml`, sin contar el comentario inicial. |
| ADR09 | El informe público no contiene rutas del equipo | Cumplida; `publish-report` lo verifica antes de copiar. |
| QA23 | Revisión de los 23 movimientos por el Product Owner | 23 «Correcto». |
| QA24 | Revisión de las 9 fases y de los elementos del cruce por el Product Owner | 9 fases «Correcto»; frontera con semáforos vecinos (DEC04) y puntos de espera «Correcto»; pasos peatonales (DEC03) «Discrepancia». |

Las planillas llenas, con «Revisado por: Christian Rojas» y «Fecha: 29/10/2026», están en `datos/revisiones/20261028T031008Z_15e51d6c/`, que git ignora.

## Limitaciones aceptadas para R1

El Product Owner aceptó estas limitaciones:

| Limitación | Fecha | Detalle |
|---|---|---|
| Salida norte de Los Frutales: el carril derecho solo lleva a la calle de servicio | 2026-10-27 | `LEEME.md` de la candidata, «Limitaciones aceptadas para R1» |
| Moto detenida en el giro a la izquierda de Javier Prado de oeste a este | 2026-10-27 | Ídem |
| Atascos de otros vehículos causados por esa moto: 13 de 26 corridas, con aumento de la pérdida de tiempo de varios flujos | 2026-10-29 | Acta `2026-10-25-propuesta-clases-vehiculares.md`, «Atascos causados por la moto detenida» |
| Pasos peatonales semaforizados del cruce real no modelados (QA24, DEC03). Nota del Product Owner: «Por ahora no contemplemos los pasos peatonales» | 2026-10-29 | Planilla QA24 |

## Verificación

- Puerta de calidad el 2026-10-29: ver «Verificación» en el acta de cierre de DEV00.
- Sin cambios en el paquete de documentación del investigador (`documentacion/`).
- La carpeta de SUMO del Product Owner no se modificó.
- Las investigaciones de la candidata se hicieron en espacios temporales fuera del repositorio.
