# Acta 2026-10-31: DEV07 · F2 (proceso controlado de SUMO)

Written for: el Product Owner y el equipo, para revisar cómo se vigila ahora una corrida y qué quedó probado.

- **Tipo:** fase F2 de DEV07 (HU04; P0, tamaño M). Dependencias: F0 y F1 de DEV07 y el corredor de DEV00.
- **Autorización:** el Product Owner aprobó F2 («ok ejecútalo»). La fase estaba planeada con Opus por ser la más delicada; se ejecutó con Sonnet, que era el modelo elegido, y se compensó con más verificación en vivo.
- **Decisiones que aplica:** D4 (tiempo límite), D5 (cancelación), D6 (topes de salidas y espacio), D7 (tiempos de la corrida), D16 (riesgos de Windows) y D19 (memoria) de F0.
- **Datos:** sintéticos. El caso real usa la carpeta que publicó DEV06 en F2.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `simulacion/process.py` | `run_controlled`: lanza un programa y lo vigila hasta que termina o hay que cortarlo |
| `simulacion/resources.py` | Memoria disponible del equipo, espacio libre en disco y memoria máxima de un proceso hijo. Sin dependencias nuevas (Windows con `ctypes`, Linux con `/proc`) |
| `simulacion/summary.py` | Modelo `RunTiming` (el contenido de `tiempos.json`) y las causas de término |
| `simulacion/runner.py` | `run_simulation` usa el proceso controlado, acepta `cancel`, exige espacio y memoria antes de empezar y escribe `tiempos.json` en toda corrida; `RunLimits` gana los topes nuevos |
| `simulacion/run_inputs.py` | `run_inputs` acepta `cancel` y lo pasa al corredor |

## Cómo se vigila una corrida

Un ciclo mira cada 0,25 s (o justo en el límite de tiempo, lo que llegue primero):

| Qué mira | Tope | Si se pasa | Estado de la corrida |
|---|---|---|---|
| Que el proceso haya terminado | — | Código 0: sigue a las comprobaciones. Otro código: `SIM_FAILED` | exitosa / `failed` |
| Si se pidió cancelar (evento o Ctrl+C) | — | Se termina SUMO | `cancelled`, sin error y sin código de salida |
| Tiempo real | 900 s | Se termina SUMO | `failed`, `SIM_TIMEOUT` |
| Tamaño de las salidas de la corrida | 512 MiB | Se termina SUMO | `failed`, `SIM_FAILED` |
| Tamaño de cada registro | 16 MiB | Se termina SUMO | `failed`, `SIM_FAILED` |
| Memoria máxima de SUMO | 4 GiB | Se termina SUMO | `failed`, `SIM_FAILED` |

- **Antes de crear la corrida** se exigen 1 GiB de memoria disponible y espacio libre igual al tope de salidas más el doble de las entradas. Si falta, no se crea la corrida y se informa cuánto falta (`SIM_FAILED`, código de salida 4).
- **Al cortar SUMO** se le pide terminar y a los 5 s se fuerza; se espera a que muera. Un cierre final garantiza que, aunque la vigilancia falle por un error inesperado, no queda ningún proceso vivo.
- **Las salidas y registros parciales se conservan** y quedan en la corrida publicada.
- **`stdout` y `stderr` van directo a archivos**, no a memoria.
- **Ctrl+C** cancela de forma ordenada. En Windows, SUMO nace en un grupo de procesos propio, para que la consola no le llegue directo.
- **Toda corrida terminal lleva `outputs/tiempos.json`:** hora de inicio y de fin, duración del proceso, tiempo límite, fin simulado, causa de término (`completed`, `sumo_error`, `timeout`, `cancelled`, `output_budget`, `memory_budget` o `not_started`), memoria máxima de SUMO y bytes escritos. No se tocó el contrato `run_manifest`.

## Verificación

**Pruebas.** 102 pruebas nuevas; 1 más se salta por enlaces simbólicos. La suite completa pasa: 1620 pruebas, 10 saltadas. Formato, lint y tipos sin observaciones.

| Grupo | Pruebas | Qué cubren |
|---|---|---|
| Proceso controlado (programas de Python simples) | 27 + 10 | Terminar bien y mal, tiempo, cancelación, Ctrl+C, procesos muertos después de cada corte, corte forzado, topes de salidas y de memoria (también en el valor exacto), cómo se lanza, errores inesperados |
| Recursos del equipo | 14 | Disco, memoria, lectura de `/proc` y qué pasa en otros sistemas |
| Límites y modelo de tiempos | 35 | Valores por defecto, rechazo de límites no positivos, todas las causas de término |
| Con SUMO real | 13 + 4 | `tiempos.json` en corridas exitosas, tiempo agotado, cancelación (antes de empezar, a los 2 s y con Ctrl+C), topes de salidas y de memoria, comprobaciones previas con los valores exactos, qué registros se vigilan |

**Mutaciones.** 59 cambios a propósito sobre el código nuevo. **45 detectadas en la primera pasada y 14 sobrevivieron.** Revisados uno por uno: 11 eran huecos reales (el valor exacto de los topes, el cierre ante errores inesperados, el grupo de procesos, la entrada vacía del proceso, los registros vigilados, el tamaño de referencia, el espacio y la memoria exactos). Se agregaron 14 pruebas y **las 11 pasaron a detectarse**. Quedan 3, justificadas:

| Sobrevive | Por qué se acepta |
|---|---|
| Terminar un proceso que ya terminó | Equivalente: el sistema lo ignora |
| Contar cualquier archivo de la carpeta, no solo los normales | Equivalente: los archivos raros no ocupan espacio medible |
| Seguir carpetas enlazadas al medir tamaño | La prueba existe, pero se salta en este equipo porque no permite crear enlaces simbólicos |

**Riesgos de Windows (D16), medidos en vivo con SUMO 1.27.1:**

| Riesgo | Resultado |
|---|---|
| SUMO deja procesos hijos | **No.** SUMO no crea procesos hijos |
| El proceso queda vivo después de cortarlo | **No.** `terminate()` lo corta en 0,01 s. Después de cada forma de cortar (tiempo, cancelación, tope, error) no queda ningún `sumo.exe`, con el número de proceso comprobado en cada prueba |
| El ciclo de vigilancia encarece la corrida | **No.** El caso real tarda lo mismo (7,3 a 11 s) |
| Ctrl+C llega directo a SUMO | **Cubierto por la documentación de Windows, no probado en vivo.** El grupo de procesos propio desactiva Ctrl+C para SUMO (bandera `CREATE_NEW_PROCESS_GROUP`, que una prueba comprueba). La reacción de la herramienta a una interrupción sí está probada. No probé Ctrl+C real desde el teclado porque la consola de este entorno no lo permite sin afectarla |

**Caso real** (`ESC-SINT-001`, SUMO 1.27.1):

| Corrida | Resultado |
|---|---|
| Completa | Exitosa; 7,3 s; SUMO usó 35 MB; 0,81 MB de salidas; 1780 vehículos, cohorte de 1338 conciliada |
| Cancelada a los 3 s | `cancelled`, sin código de salida; se conservan 0,36 MB de salidas parciales y los registros |
| Tope de memoria de 10 MB | `failed`, `SIM_FAILED`: «SUMO usó 32 MiB de memoria y el tope es 10 MiB»; se corta en 0,3 s |
| Procesos de SUMO vivos al terminar | 0 |

## Hallazgos de la inspección

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | **Defecto en el tiempo agotado.** Con un límite más corto que el intervalo de vigilancia (0,25 s), el proceso podía terminar antes del siguiente chequeo y su exceso no se contaba como tiempo agotado. Lo detectaron al integrar una prueba de DEV00 y una de DEV06 | El ciclo despierta justo en el límite. Prueba nueva con un intervalo largo |
| 2 | **Una medición equivocada en mis propias pruebas.** En Windows, el `python.exe` del entorno virtual es un lanzador que crea otro proceso; medir su memoria daba 5 MB en vez de 160 MB | Las pruebas usan el intérprete base. SUMO no tiene lanzador |
| 3 | **Una medición manual ensució el ejemplo.** Un comando mío escribió `statistics.xml` junto al ejemplo de pruebas (la configuración usa rutas relativas) | Se borró y se comprobó que el repositorio quedó limpio. Las pruebas siempre usan una copia |
| 4 | **Cambio de comportamiento que conviene saber.** La comprobación de memoria y espacio antes de empezar también afecta a `case receive` (DEV00): en un equipo con menos de 1 GiB disponible, la recepción se rechaza con `SIM_FAILED` en vez de ejecutarse | Es el efecto buscado por D19. Se puede bajar con `min_free_memory_bytes` |
| 5 | **`started_at` y `finished_at` incluyen más que el proceso.** Marcan desde que empieza a armarse la corrida hasta que se publica (incluye copiar las entradas). `duration_s` mide solo el proceso de SUMO | Se documenta aquí y en el modelo. Ambos sirven, para cosas distintas |

## Desviaciones frente a F0

| Tema | F0 | Lo construido | Por qué |
|---|---|---|---|
| Causas de término (D7) | `completed`, `timeout`, `cancelled`, `output_budget`, `sumo_error` | Se agregan `memory_budget` (por D19) y `not_started` (una corrida que falla antes de lanzar SUMO, por ejemplo por una ruta demasiado larga, también lleva su `tiempos.json`) | Toda corrida terminal debe llevar su archivo, y D19 agregó un tope que faltaba nombrar |
| Memoria en otros sistemas (D19) | «con la del sistema» | `/proc` en Linux; en cualquier otro sistema no se mide y la comprobación se omite | No hay una forma sin dependencias nuevas en los demás sistemas |
| Corrida cancelada | Publicada `cancelled` | Se devuelve publicada, sin lanzar excepción. Quien llame decide qué hacer | El comando `simulate run` (F4) la traduce al código de salida 4 |

## Qué no hace F2 (queda para las fases siguientes)

- **F3:** corridas interrumpidas (apagón o proceso terminado a la fuerza) y reintentos con `retry_of`. Hoy, si el programa muere en medio de una corrida, queda una carpeta temporal sin publicar, igual que antes.
- **F4:** el comando `python -m semaforo simulate run`. Hoy se usa solo desde código.
- **F5:** verificación final, mutaciones, inspección y cierre de HU04.

## Estado del repositorio

- Archivos nuevos: `process.py`, `resources.py` y seis archivos de pruebas. Cambian `runner.py`, `run_inputs.py` y `summary.py`.
- Autor `crisroco`, sin línea de coautoría.
- Sin subir: 15 commits locales. `origin/main` sigue en `9fb7944`. No se ha hecho push: se sube cuando lo pida el Product Owner.
