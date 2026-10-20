# Acta 2026-10-20: DEV00 · F9 (recepción de R0 de punta a punta)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F9 («ejecuta F9»).
- **Código y pruebas:** F9 no cambia el código. Ejecuta las herramientas de F2 a F8 con la simulación real de R0.
- **Siguiente fase:** F10 (recepción oficial R1, después de los cambios del Product Owner), a la espera de su aviso «SUMO listo» y de su autorización expresa.

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
- **Programa activo con varios programas:** se reconfirma con la corrida real (SUMO ejecuta el programa que F3 identificó).

## Observaciones de la corrida, para la revisión del Product Owner

No son errores del código. Son rasgos de la simulación recibida que afectan lo que se podrá medir después. El detalle está en `hallazgos.md`.

- **Demanda no atendida:** una parte de los vehículos declarados nunca entra a la red en las 2 h simuladas, por saturación de las entradas. Esa demora no se debe al semáforo y debe quedar fuera de las métricas de DEV03 en adelante.
- **Semáforo actuado sin detectores:** el programa actuado no tiene detectores que lo controlen, de modo que no hay colas medibles con ellos (DEC06).
- **Duración menor que `minDur`:** tres fases declaran una duración menor que su mínimo.
- **Frenado de emergencia:** SUMO avisa de un frenado de emergencia dentro del cruce.
- **Movimientos sin clase usable:** 25 de 53 movimientos semafóricos llevan a vías que ningún vehículo de la demanda puede usar (QA23).

## Verificación

- Pruebas: sin cambios, 439 pasan y 1 se salta de forma declarada.
- Sin cambios en el código ni en la documentación fuente.
- La carpeta original de la simulación no se tocó en toda la fase.

## Limitaciones conocidas

- QA23 y QA24 requieren al Product Owner: las planillas se generan, pero marcarlas es una decisión humana. La firma final corresponde a R1.
- R0 es provisional: nada de esta fase es la recepción oficial.
- Los 25 movimientos sin clase usable y el frenado de emergencia pueden venir de cómo se construyó la red, no de los tiempos semafóricos. Se resuelven, si el Product Owner lo decide, en los cambios previos a R1.
