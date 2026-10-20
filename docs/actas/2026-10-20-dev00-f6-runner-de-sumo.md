# Acta 2026-10-20: DEV00 · F6 (runner mínimo de SUMO)

- **Tipo:** registro de fase del plan de DEV00 (HU04). Adelanta el núcleo de DEV07 (decisión D3).
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F6 («ejecuta F6»).
- **Código y pruebas:** commit `5d9c1f5`.
- **Siguiente fase:** F7 (servicio de recepción y CLI `python -m semaforo case receive`), a la espera de la autorización expresa del Product Owner.

## Qué se implementó

| Módulo | Responsabilidad |
|---|---|
| `simulacion/runner.py` | `run_simulation`: ejecuta una simulación sobre una copia y publica la corrida (F5); `find_sumo`, `sumo_version` y `summarize_outputs` |
| `simulacion/summary.py` | `SimulationSummary`: estado final de los vehículos, incidencias y demanda atendida |

## Cómo funciona una corrida

1. **Antes de ejecutar nada** se rechaza un `.sumocfg` inexistente, fuera de la carpeta o con rutas absolutas (QA10: SUMO escribiría fuera de la corrida), y se exige que `SUMO_HOME` apunte a SUMO.
2. Las entradas se copian a una carpeta de ejecución de F5. SUMO se lanza con `subprocess`, lista de argumentos y sin shell (ADR04), y se le pasan por línea de comandos:
   - el final, `--end`: 7200 s en modo base y 60 s en modo smoke (D4, provisionales);
   - las salidas, `tripinfo` con los viajes no terminados y `statistics`, dirigidas a `outputs/`;
   - el registro, `outputs/sumo.log`;
   - un valor vacío para las opciones de archivo de `<gui_only>`.
   Ningún archivo se modifica. El tiempo real máximo es de 900 s (provisional).
3. **Éxito (QA07):** código de salida 0 y salidas coherentes. Debe haber un `tripinfo` por vehículo insertado, los viajes no terminados deben ser los vehículos que siguen en la red y no puede haber más insertados que cargados. Es la regla que exigía el acta de F1.
4. **Fallo (QA08):** si SUMO termina con error (`SIM_FAILED`), se pasa del tiempo (`SIM_TIMEOUT`) o sus salidas no son coherentes (`OUTPUT_INVALID`), la corrida se publica como `failed` con su motivo y **sin métricas**. Sus registros quedan como evidencia.
5. **Resumen** (`outputs/summary.json`, solo si hay éxito): vehículos cargados, insertados, en la red y esperando para entrar; viajes terminados y no terminados; teletransportes por causa; colisiones; demora media de salida y avisos de SUMO.
6. **Demanda no atendida** (cambio de alcance aprobado en F4): con los vehículos declarados de la auditoría, el resumen marca `demand_unmet` si SUMO no cargó toda la demanda, quedaron vehículos esperando para entrar o seguían vehículos en la red al terminar.
7. **Trazabilidad:** el manifiesto registra la versión de SUMO, Python y el sistema operativo, y un comando con rutas relativas, sin las del equipo.

## Hallazgos con la simulación real

La puerta de salida falló la primera vez con la simulación de R0, aunque el fixture funcionaba. La causa fueron dos problemas reales, ya corregidos:

1. **SUMO exige que exista el archivo de vista aunque no haya interfaz.** El `.sumocfg` declara un `gui-settings-file`, y la copia de F2 contiene solo los archivos de identidad (ADR09), sin las vistas. **Corrección:** el runner anula por línea de comandos las opciones de archivo de `<gui_only>`, que no influyen en una corrida sin interfaz. La identidad de F2 no cambia.
2. **SUMO 1.27.1 no abre rutas de más de 257 caracteres en Windows.** Se midió: funciona con 257 y falla con 258, con el mensaje «Could not access configuration». La carpeta temporal de F5 (`.tmp-<run_id>-…`) gastaba unos 52 caracteres. **Corrección:** la carpeta temporal pasa a `.tmp-<8 caracteres>`, y el runner falla con un motivo claro (`PATH_NOT_ALLOWED`) antes de ejecutar SUMO si alguna ruta supera el límite.

## Evidencia de la puerta de salida (copia inmutable de R0)

Corridas en una carpeta temporal fuera del repositorio; la corrida base oficial es de F9. Según ADR09, el detalle de los resultados no se publica aquí.

| Comprobación | Resultado |
|---|---|
| Corrida smoke | `succeeded`; resumen con demanda no atendida, como corresponde a 60 s |
| Corrida base (7200 s simulados) | `succeeded` en menos de 5 s reales: el límite de 900 s sobra con margen |
| Demanda no atendida en la corrida base | marcada: quedaron vehículos esperando para entrar y en la red. Coincide con lo que mostraba la corrida previa del Product Owner |
| Avisos de SUMO | registrados en `outputs/sumo.log` y contados en el resumen; incluyen avisos sobre detectores del programa actuado |
| Manifiesto | sin rutas del equipo; lectura verificada igual al publicado |
| Copia de F2 | hash y fecha sin cambios |

## Verificación

- Pruebas: 374 pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios). F6 añade 35, de ellas 15 con SUMO real: corrida base y smoke del fixture, las dos variantes defectuosas, tiempo agotado, rutas absolutas, salidas declaradas por el `.sumocfg`, vista ausente, ruta demasiado larga y salidas incoherentes.
- QA09 parcial: dos corridas con la misma semilla producen el mismo `tripinfo.xml` (sin el comentario inicial) y el mismo resumen.
- Las pruebas fallaron antes del código. Las correcciones de los hallazgos también se probaron primero en rojo.
- Veintidós mutaciones del código fueron detectadas. Cuatro sobrevivieron al principio y se cerraron así: con pruebas de un viaje que llega en el segundo 0, de salidas incoherentes con código 0 y de una unión en el origen; la cuarta era código muerto y se eliminó (`pathlib` ya quita la barra final de `SUMO_HOME`).
- `ruff`, formato y `pyright` estricto sin errores; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- **Las salidas de SUMO llevan rutas del equipo.** SUMO escribe al inicio de cada salida un comentario con la configuración completa y sus rutas absolutas, incluido el nombre de usuario. Quedan en `datos/` (ignorado por git), y el informe público de F8 no debe copiar nada de esos archivos sin quitarlo.
- La coherencia se comprueba con `statistics.xml` y `tripinfo.xml`. Otras salidas que declare el `.sumocfg` se conservan, pero no se validan.
- Los límites (7200 s, 60 s, 900 s y 257 caracteres) son provisionales o propios de SUMO 1.27.1 en Windows; se revisan en el piloto o si cambia la versión.
- El runner no interpreta los avisos de SUMO, solo los cuenta. Revisarlos es parte de QA24.
