# Acta 2026-10-20: DEV00 · F9 (recepción de R0 de punta a punta)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F9 («ejecuta F9»).
- **Código y pruebas:** F9 ejecuta las herramientas de F2 a F8 con la simulación real de R0. La revisión posterior corrigió el código en `dcf4b77` y `46eb6ba` (ver «Revisión posterior»).
- **Recepción que revisa el Product Owner (QA23 y QA24):** `20261020T215129Z_be52433f`, generada con las planillas corregidas. (El Product Owner completó la planilla de la primera recepción, que es equivalente: ver «Dónde se guardan las planillas completadas» en el acta de F8.)
- **Siguiente fase:** F10 (recepción oficial R1, después de los cambios del Product Owner), a la espera de su aviso «SUMO listo» y de su autorización expresa. **Actualización (2026-10-29):** F10 hecha; ver el acta `2026-10-29-dev00-f10-recepcion-de-r1.md`.

## Qué se hizo

```powershell
python -m semaforo case receive --source datos/originales/sumo/R0-provisional --config frutales_solo.sumocfg --case-id frutales-r0
python -m semaforo case publish-report --reception-id 20261020T210623Z_be52433f
```

| Dato | Valor |
|---|---|
| Recepción | `20261020T210623Z_be52433f` |
| Copia (`snapshot_id`) | `be52433f…` (la misma que calculó F2; la copia se reutilizó) |
| Estado propuesto | `with_findings` (con observaciones; es una propuesta que valida el Product Owner) |
| Corrida base | `20261020T210623Z_simulation_eafaac8e`, `succeeded` |
| Código de salida | 0 |
| Duración | unos 5 s |
| Informe público | `docs/recepcion/20261020T210623Z_be52433f.md` |

Según ADR09, el detalle de los hallazgos (red, semáforos, rutas, demanda y resultados) queda en `datos/derivados/recepcion/20261020T210623Z_be52433f/hallazgos.md`, ignorado por git. Las planillas `revision_qa23.csv` y `revision_qa24.csv` están en la misma carpeta, listas para la primera pasada del Product Owner.

## Pruebas de aceptación con datos reales

| Prueba | Qué se comprobó | Resultado |
|---|---|---|
| QA07 | La corrida base queda `succeeded` solo si el proceso y las salidas son válidos; los originales quedan intactos | Cumplida. Los 21 archivos de `R0-provisional` coinciden con los hashes del acta de F0. La recepción, el manifiesto y la corrida quedan en solo lectura. |
| QA07 (modo `smoke`) | Corrida corta de verificación | Cumplida (código 0). |
| QA08 | Una ruta con una arista inexistente, sobre una copia temporal de R0 | Cumplida. SUMO falla; la corrida queda `failed` con `SIM_FAILED`, el código de salida es 4, la recepción queda `failed` y **no se publica ningún resumen de métricas**. |
| QA09 | Dos recepciones con los mismos insumos y la misma semilla (2026) | Cumplida. Las huellas de las entradas son iguales y el resumen es idéntico. `tripinfo.xml` es idéntico una vez quitado el comentario inicial (fecha y rutas del equipo), y `statistics.xml` también una vez quitada la línea de rendimiento (tiempo de reloj). |
| ADR09, F8 | El informe público no contiene rutas del equipo | Cumplida; `publish-report` lo verifica antes de copiar. |

La réplica de QA09 y la falla de QA08 se hicieron en espacios temporales fuera del repositorio y se borraron. Así `datos/` conserva una sola recepción de R0, la que revisará el Product Owner.

## Pendientes de F0 que se cierran

- **Comportamiento de `--end`:** la configuración no fija `end`. El runner pasa el límite de D4 (7200 s) por línea de comandos y la corrida termina exactamente en ese tiempo; el `.sumocfg` original no se modifica.
- **Programa activo con varios programas:** no aplica a R0, cuya red tiene un solo programa. Queda resuelto por la medición de F3, que ejecuta SUMO y está fijada en `tests/integration/test_inventory_sumo.py`.

## Observaciones de la corrida, para la revisión del Product Owner

No son errores del código. Son rasgos de la simulación recibida que afectan lo que se podrá medir después. El detalle está en `hallazgos.md`.

- **Demanda no atendida:** una parte de los vehículos declarados nunca entra a la red en las 2 h simuladas, por saturación de las entradas. Esa demora no se debe al semáforo y debe quedar fuera de las métricas de DEV03 en adelante.
- **Semáforo actuado sin detectores:** el programa actuado no tiene detectores que lo controlen, de modo que no hay colas medibles con ellos (DEC06).
- **Duración menor que `minDur`:** tres fases declaran una duración menor que su mínimo.
- **Frenado de emergencia:** SUMO avisa de un frenado de emergencia dentro del cruce.
- **Movimientos sin clase usable:** 25 de 53 movimientos semafóricos llevan a vías que ningún vehículo de la demanda puede usar (QA23).

## Verificación

- Pruebas al cerrar la ejecución de la fase: 439 pasan y 1 se salta de forma declarada. Después de la revisión posterior: 450 pasan.
- Sin cambios en la documentación fuente (`documentacion/`).
- La carpeta original de la simulación no se tocó en toda la fase.

## Revisión posterior (2026-10-20)

A pedido del Product Owner, antes de su revisión QA23 y QA24 se revisó todo lo hecho hasta F9. Se contrastaron las planillas con la red mediante un cálculo independiente del código del proyecto: coinciden los 53 enlaces (aristas, carriles, giro y clases) y las 12 fases (duraciones, `minDur`, `maxDur`, verdes y amarillos). Se encontraron y corrigieron cuatro problemas:

| Problema | Cómo se detectó | Corrección |
|---|---|---|
| Excel convertía en número las aristas de ID numérico: `-1185174556` se veía como `-1.185E+09` y no se podía buscar en netedit | Se abrió una copia de la planilla de R0 con Excel 16 y se leyó lo que muestra cada celda | Los identificadores de semáforo, programa y aristas van como fórmula de texto (`="…"`). Se verificó con Excel que se ven exactos (también los que parecen fechas o fórmulas) y que, al guardar, Excel escribe el valor limpio. `dcf4b77` y `46eb6ba` |
| La huella del manifiesto de la corrida base se guardaba y se publicaba, pero ningún código la comprobaba | Lectura del código de `read_reception` | `read_reception` (y con él `publish-report` y `compare`) verifica la corrida base archivo por archivo y la huella de su manifiesto. `dcf4b77` |
| QA08 pide una salida XML truncada y no había prueba para ella | Revisión de las pruebas frente a `03_Pruebas_y_operacion.md` | Prueba nueva. El código ya la rechazaba con `OUTPUT_INVALID`. `dcf4b77` |
| Esta acta afirmaba que el programa activo «se reconfirma con la corrida real», sin haberlo comprobado | Revisión del acta | Texto corregido (ver «Pendientes de F0 que se cierran») |

Las pruebas nuevas fallaron antes de la corrección, salvo la de QA08, que pasó porque el código ya cubría el caso. Las 10 mutaciones del código nuevo fueron detectadas. Quedan 450 pruebas que pasan y 1 que se salta de forma declarada.

**Nueva recepción de R0.** Las recepciones no se sobrescriben. Por eso se hizo una nueva, `20261020T215129Z_be52433f`, con las planillas corregidas, y su informe está en `docs/recepcion/`. Es la que revisa el Product Owner. La primera (`20261020T210623Z_be52433f`) se conserva como registro. `case compare` entre las dos da 0 cambios: misma copia y mismo resultado de la corrida, lo que vuelve a confirmar QA09 con datos reales. Ambas pasan la verificación nueva y R0 sigue intacta (21/21). La protección del `programID` (`46eb6ba`) se añadió después de generar esta recepción; en R0 no cambia nada visible, porque el programa es `0`.

## Limitaciones conocidas

- QA23 y QA24 requieren al Product Owner: las planillas se generan, pero marcarlas es una decisión humana. La firma final corresponde a R1.
- En un editor de texto, los identificadores de las planillas se ven como `="…"`. Están pensadas para Excel.
- R0 es provisional: nada de esta fase es la recepción oficial.
- Los 25 movimientos sin clase usable y el frenado de emergencia pueden venir de cómo se construyó la red, no de los tiempos semafóricos. Se resuelven, si el Product Owner lo decide, en los cambios previos a R1.
