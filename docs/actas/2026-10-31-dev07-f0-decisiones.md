# Acta 2026-10-31: DEV07 · F0 (decisiones de la ejecución de SUMO)

- **Tipo:** fase F0 de DEV07 (HU04; P0, tamaño M). Dependencias: DEV06, cerrada en local.
- **Autorización:** el Product Owner pidió analizar DEV07 y generar sus fases, y luego ejecutar F0 («ejecuta F0»).
- **Alcance de F0:** solo decisiones por escrito. No hay código ni archivos de datos. DEV07 no toca código del modelo: el primer código del modelo es DEV16.

## Qué pide la documentación

- `02_Requisitos_y_plan.md`, DEV07: «Lanzar subprocess sin shell, timeout/cancelación, exit code, XML y conciliación de archivos antes de publicar». Archivo propuesto: `simulacion/runner.py`. Resultado: «RunResult con estado verificable». Verificación: QA08, QA10 y QA31.
- `01_Diseno_tecnico.md`: SUMO se configura por ruta absoluta validada; `shell=False`, argumentos construidos por el adaptador y timeout. «Cancelar termina el proceso hijo y conserva logs.» La unidad de publicación es el directorio de ejecución: «ante caída, el directorio queda failed o incompleto, nunca succeeded», con un lock exclusivo por destino. Códigos de salida: 4 = fallo de proceso o tiempo agotado; 5 = integridad o ruta no permitida.
- `03_Pruebas_y_operacion.md`, «Operación de lotes»: estados `queued`, `running`, `succeeded`, `failed`, `cancelled`; cada corrida conserva duración, código de salida, stdout/stderr, huellas, semilla y estado de integridad; reintentar crea un `run_id` nuevo con `retry_of` sin sobrescribir; «un proceso interrumpido se marca incompleto al reinicio»; límite de tamaño de logs y de espacio. «SUMO timeout: mantener salidas parciales y reintentar con nuevo ID.»
- QA08: red inválida y salida XML truncada dan `failed` con motivo y sin métricas. QA10: rutas, XML y nombres peligrosos bloqueados, sin shell ni comando inyectado. QA31: un lote cancelado o una corrida incompleta nunca es `succeeded`.

## Qué existe ya (DEV00 F6, DEV06) y qué falta

| Pedido | Estado | Dónde |
|---|---|---|
| Sin shell, lista de argumentos, rutas relativas | Existe | `run_simulation` |
| Código de salida, XML seguro y coherente, resumen | Existe | `summarize_outputs`; salidas con DTD, truncadas o incoherentes fallan |
| Fallo sin métricas (`failed` + motivo) | Existe | Códigos `SIM_FAILED`, `SIM_TIMEOUT`, `OUTPUT_INVALID` |
| Publicación atómica, lock por destino, sin sobrescribir | Existe | `RunWriter` |
| Tiempo límite de 900 s | Existe | `subprocess.run(timeout=…)` |
| Rutas absolutas y rutas demasiado largas bloqueadas | Existe | `run_simulation` |
| Conciliar la cohorte por ID | Existe, suelta | `reconcile_run` (DEV06 F3): hoy se llama después de la corrida |
| Fin de simulación desde el manifiesto de entradas | **Falta** | El corredor usa 7200 s o lo que le pase quien llama |
| Cancelación | **Falta** | No existe; `subprocess.run` no se puede cancelar |
| Tope de tamaño de los registros | **Falta** | `capture_output=True` guarda todo en memoria |
| Duración de la corrida | **Falta** | El manifiesto solo tiene la hora de inicio |
| Marcar corridas interrumpidas | **Falta** | `case receive` solo las lista (carpetas `.tmp-`); no distingue una corrida viva de una caída |
| Reintentos | **Falta** | `retry_of` existe en el manifiesto, nada lo valida |
| Conciliación y tabla de cohorte antes de publicar | **Falta** | La tabla no se guarda en la corrida |
| Comando para ejecutar | **Falta** | El diseño menciona `simulate run`; ninguna tarea lo tiene |

**Medido el 2026-10-31** con el caso real (1780 vehículos, 2100 s simulados): una corrida tarda entre 7,5 y 10,8 s reales. Las salidas pesan 0,85 MB (el `tripinfo` es casi todo: unos 470 bytes por vehículo) y las entradas 0,6 MB. Con el máximo de 200 000 vehículos de DEV06, el `tripinfo` sería de unos 100 MB.

## Decisiones

| # | Tema | Decisión | Por qué |
|---|---|---|---|
| D1 | Qué se amplía | `run_simulation` (DEV00) se amplía, no se reemplaza. Sus pruebas de DEV00 deben seguir pasando. El `RunResult` del diseño es el `SimulationResult` existente (no se renombra). Una función nueva de nivel superior, `run_inputs`, en un módulo nuevo (`simulacion/run_inputs.py`), ejecuta una carpeta de entradas de DEV06 | `runner.py` sigue sin saber de cohortes ni de manifiestos de entradas. `case receive` sigue funcionando igual |
| D2 | Qué se ejecuta y qué se comprueba antes | Solo una carpeta de entradas publicada por DEV06. Antes de lanzar SUMO: el manifiesto es válido; la huella de cada archivo de la carpeta coincide con la del manifiesto, y no sobran ni faltan archivos; el fin, el paso y la semilla del `.sumocfg` coinciden con los del manifiesto. Una carpeta alterada no se ejecuta (HASH_MISMATCH, código 5) | `manifiesto.json` no puede llevar su propia huella; la comparación con el `.sumocfg` cierra ese hueco. Es la misma comprobación de `reconcile_run`, hecha antes y no después |
| D3 | Fin y semilla | El fin de la simulación (`--end`), la semilla, el escenario y la versión del caso salen del manifiesto de entradas. Los 7200 s por defecto quedan solo para `case receive`. Los vehículos declarados son el total del manifiesto | Cierra el pendiente de D2 de DEV06 |
| D4 | Tiempo real límite | Se mantienen los 900 s por defecto, configurables. Medido: unos 8 s para 2100 s simulados, más de 100 veces de margen. Al agotarse: SUMO se termina, las salidas parciales y los registros se conservan, y la corrida queda `failed` con `SIM_TIMEOUT` | La documentación pide mantener salidas parciales |
| D5 | Cancelación | Se puede cancelar de dos formas: con Ctrl+C desde el comando y con una señal desde código (un evento de Python que se revisa cada 0,25 s). Se cambia `subprocess.run` por `Popen` con un ciclo que vigila: fin del proceso, tiempo, cancelación y tope de salidas. Al cancelar: se pide terminar a SUMO, a los 5 s se fuerza, se conservan registros y salidas parciales y la corrida se publica `cancelled` sin resultados. En Windows se prueba si hace falta un grupo de procesos propio para que Ctrl+C no llegue directo a SUMO | El diseño: «cancelar termina el proceso hijo y conserva logs» |
| D6 | Topes de salida | `stdout` y `stderr` se escriben directo a archivos (no a memoria). Durante la corrida se vigila el tamaño de `outputs/`: tope provisional de 512 MiB en total (el mismo que ya se usa para leer un XML) y 16 MiB por registro. Si se pasa, SUMO se termina y la corrida queda `failed` con `SIM_FAILED` y el motivo. Antes de empezar se exige espacio libre igual al tope más el doble del tamaño de las entradas; si no hay, no se crea la corrida (código 4) | «Limitar tamaño de logs y espacio». El tope de 512 MiB cubre el máximo de DEV06 con holgura (unos 100 MB) |
| D7 | Duración y tiempos | **No se cambia el contrato `run_manifest`** (viene de la documentación; agregar un campo cambiaría el esquema publicado). En toda corrida terminal se escribe `outputs/tiempos.json` con hora de inicio y de fin (UTC), duración real, tiempo límite, fin simulado y causa de término (`completed`, `timeout`, `cancelled`, `output_budget`, `sumo_error`). Es un archivo de salida con su huella; no entra en comparaciones científicas (QA09) | La documentación prevalece. Cumple «conserva duración» sin tocar el contrato |
| D8 | Corridas interrumpidas | El lock pasa a ser un bloqueo del sistema operativo que se mantiene mientras la corrida vive (`msvcrt` en Windows, `fcntl` en los demás) y que el sistema libera si el proceso muere. Antes de cada corrida, `recover_interrupted` revisa las carpetas `.tmp-*`: si su lock no se puede tomar, la corrida sigue viva y no se toca; si se puede, está caída y su carpeta se mueve a `<ejecuciones>/.incompletas/<run_id>/` con un `INCOMPLETA.json` (causa, fecha de detección). **Nunca se publica como corrida**: `read_run` de ese `run_id` no existe. No se borra nada | Hoy no se distingue una corrida viva de una caída. Mover sin publicar cumple «incompleto, nunca succeeded» sin inventar un estado nuevo en el contrato |
| D9 | Reintentos | `retry_of` apunta a una corrida anterior del mismo caso, versión y escenario que esté `failed`, `cancelled` o interrumpida (en `.incompletas`). No se permite reintentar una `succeeded` ni una que no existe (INPUT_SCHEMA). El reintento siempre es una corrida nueva con `run_id` nuevo; nunca sobrescribe. Puede usar las mismas entradas u otras; el manifiesto registra las que usó | «Reintentar crea un nuevo run_id con retry_of; no sobrescribe la evidencia anterior» |
| D10 | Conciliación antes de publicar | Si SUMO termina bien, antes de publicar se concilia la cohorte (`reconcile`) y se agregan a `outputs/` la tabla de cohorte (`cohorte_conciliada.csv`) y un `conciliacion.json` con los conteos por movimiento y clase. Si la conciliación falla (viaje repetido, vehículo desconocido, planilla alterada), la corrida queda `failed` con `OUTPUT_INVALID` y sin métricas. Vehículos sin terminar o que no entraron **no** hacen fallar la corrida: se cuentan | QA25: ningún caso se excluye sin registro. Cierra la desviación de D20 de DEV06 (la tabla no se guardaba). Implementación: `run_simulation` recibe un paso opcional previo a la publicación |
| D11 | Estados | `queued` y `running` solo existen en el manifiesto provisional. DEV07 publica `succeeded`, `failed` y `cancelled`. No hay cola ni corridas en paralelo: una a la vez por destino, protegida por el lock | Los lotes y el paralelismo son de tareas posteriores del plan (escenarios y búsqueda) |
| D12 | Comando | `python -m semaforo simulate run --inputs <carpeta> [--workspace] [--sumo-bin] [--wall-timeout] [--retry-of]`, a través de la capa `app` (ADR01). Salida JSON con `status`, `run_id` y motivo. Códigos: 0 `succeeded`; 2 entradas inválidas; 3 SUMO ausente; 4 `failed`, tiempo agotado o `cancelled`; 5 integridad o ruta no permitida. El que lee debe mirar `status`, no solo el código | El diseño: «los consumidores deben leer status del JSON». **Opcional**: el Product Owner decide si entra (F4) |
| D13 | Seguridad | Se mantiene todo lo de DEV00: sin shell, argumentos como lista, rutas relativas a la corrida, XML sin DTD, enlaces rechazados, rutas absolutas rechazadas. Las carpetas de entradas con enlaces se rechazan. No se agregan dependencias | QA10 |
| D14 | Fuera de DEV07 | Corridas en paralelo y lotes (tareas posteriores de escenarios y búsqueda), respaldo y restauración (el resto de QA31), métricas (DEV19), réplica formal con comparación de huellas (QA09, DEV08) y cualquier cambio del contrato `run_manifest` | Cada una tiene su tarea en el plan |
| D15 | Pruebas con SUMO real | Una corrida larga para probar cancelación y tiempo agotado se obtiene con un fin de simulación muy grande sobre la red de demostración. Salida truncada y red inválida: se prueban con las variantes defectuosas que ya existen | No depende del caso real, que está en `datos/` (fuera del repositorio) |
| D16 | Riesgos que se miden en F2 | Que SUMO no deje procesos hijos al terminarlo; que Ctrl+C en Windows no llegue directo a SUMO; que el ciclo de vigilancia no encarezca la corrida. Si algo de esto falla, la decisión D5 se corrige con el Product Owner antes de seguir | Manejo de procesos en Windows: lo más delicado de la tarea |

## Fases siguientes

| Fase | Qué se hace | Criterio de cierre | Complejidad | Modelo sugerido |
|---|---|---|---|---|
| F1 | Ejecutar desde la carpeta de entradas: comprobaciones previas (D2), fin y semilla del manifiesto (D3), conciliación y tabla antes de publicar (D10); `run_inputs` | Una corrida del ejemplo y del caso real se publica con su tabla; una carpeta alterada no se ejecuta; una conciliación fallida deja la corrida `failed` | Media | Sonnet |
| F2 | Proceso controlado: `Popen` con ciclo de vigilancia, tiempo agotado, cancelación, topes de salida y espacio, `tiempos.json` (D4 a D7, D16) | Pruebas con SUMO real de tiempo agotado, cancelación, error de SUMO, salida truncada y tope de salidas: todas sin métricas y con registros conservados (QA08). Pruebas de DEV00 intactas | Media-alta | Opus |
| F3 | Interrumpidas y reintentos: lock del sistema, `recover_interrupted`, `.incompletas` y reglas de `retry_of` (D8, D9) | Una corrida interrumpida de verdad (proceso terminado a la fuerza) nunca aparece como `succeeded` ni se pierde; el reintento no borra nada (parte de QA31) | Media | Sonnet |
| F4 | Comando `simulate run` por la capa `app` (D12) — **opcional** | Se ejecuta una corrida con un solo comando y los códigos de salida del diseño | Baja | Sonnet |
| F5 | Verificación con el caso real, mutaciones, inspección y cierre con la tabla de HU04 | HU04 completo en lo que toca a DEV07; QA08, QA10 y QA31 verificados; actas y CONTEXTO al día | Baja-media | Sonnet |

Cada fase cierra, como en DEV06, con una inspección de lo desarrollado contra la documentación y el caso real.

## Qué queda para el Product Owner

1. **Incluir o no el comando `simulate run` (F4).** Se recomienda incluirlo: sin él, ejecutar una corrida depende de scripts.
2. **Confirmar los límites provisionales:** 900 s de tiempo real, 512 MiB de salidas, 16 MiB por registro y el espacio libre exigido (D4 y D6). Se pueden ajustar sin cambiar el código.
3. **Confirmar que una corrida cancelada sale con código 4** y se distingue por `status` en el JSON (D12), ya que el diseño no le asigna un código propio.
4. **Aceptar que la duración vaya en `outputs/tiempos.json`** y no en el contrato `run_manifest` (D7), porque ese contrato viene de la documentación.

## Estado

- Sin código, sin archivos de datos y sin commits de código en esta fase. Este acta es el único cambio.
