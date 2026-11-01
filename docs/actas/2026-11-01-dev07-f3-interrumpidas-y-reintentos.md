# Acta 2026-11-01: DEV07 · F3 (corridas interrumpidas y reintentos)

Written for: el Product Owner y el equipo, para revisar qué pasa cuando una corrida se cae a medias y cómo se reintenta.

- **Tipo:** fase F3 de DEV07 (HU04; P0, tamaño M). Dependencias: F0, F1 y F2 de DEV07.
- **Autorización:** el Product Owner aprobó F3 («ok ejecuta F3»). Modelo: Sonnet, el sugerido en F0.
- **Decisiones que aplica:** D8 (corridas interrumpidas) y D9 (reintentos) de F0, más una adición propia (ver «Desviaciones»).
- **Datos:** sintéticos. El caso real usa la carpeta que publicó DEV06 en F2.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `trazabilidad/lock.py` | `RunLock`: bloqueo del sistema operativo (`msvcrt` en Windows, `fcntl` en los demás). El sistema lo suelta solo cuando el proceso muere, de la forma que sea |
| `trazabilidad/interrupted.py` | `recover_interrupted` aparta las corridas caídas a `.incompletas/<run_id>/` con una marca `INCOMPLETA.json`; `list_interrupted` las lista |
| `trazabilidad/retry.py` | `check_retry`: reglas de `retry_of` |
| `simulacion/job.py` | `KillOnClose`: en Windows, SUMO muere junto con el programa que lo lanzó |
| `trazabilidad/store.py` | `RunWriter` usa `RunLock` en vez del archivo creado con `O_EXCL` |
| `simulacion/runner.py` | `run_simulation` aparta las corridas caídas y comprueba el reintento antes de empezar |
| `simulacion/run_inputs.py` | `run_inputs` acepta `retry_of` |
| `simulacion/process.py` | El proceso lanzado entra en el grupo de `KillOnClose` |
| `app/reception.py` | `case receive` aparta y lista las corridas caídas desde `.incompletas` |

## Cómo funciona

**Corridas caídas (D8).** Una corrida en curso vive en `.tmp-<8 caracteres>` con el bloqueo `.lock-<run_id>` tomado. Antes de cada corrida se revisan esas carpetas:

| Situación | Qué se hace |
|---|---|
| El bloqueo lo tiene otro proceso vivo | No se toca |
| El bloqueo se puede tomar (el dueño murió) | Se escribe `INCOMPLETA.json` y la carpeta se mueve a `.incompletas/<run_id>/` |
| Sin manifiesto legible y modificada hace menos de 60 s | No se toca: puede estar naciendo |
| Sin manifiesto legible y más vieja que eso | Se aparta con el `run_id` desconocido, con el nombre de su carpeta |
| Es un enlace o una unión | No se toca ni se sigue |
| No se puede mover (otro programa la tiene abierta) | Se deja donde está y se vuelve a intentar la próxima vez; las demás se apartan igual |
| El mismo `run_id` cayó dos veces | Se conservan las dos: `<run_id>` y `<run_id>-2` |

- **No se borra nada.** Lo escrito hasta la caída queda como evidencia.
- **Nunca se publica como corrida:** `read_run` de ese `run_id` no la encuentra, así que jamás aparece como `succeeded`. El contrato `run_manifest` no cambia.
- `INCOMPLETA.json` guarda: `run_id`, carpeta de origen y de destino, fecha de creación y de detección, estado provisional (`running`), caso, versión, escenario y causa.

**Reintentos (D9).** `retry_of` solo se acepta si cumple:

| Regla | Si no se cumple |
|---|---|
| Es un nombre de carpeta seguro | `PATH_NOT_ALLOWED` |
| La corrida existe: publicada, o interrumpida en `.incompletas` | `INPUT_SCHEMA` («no existe») |
| No es `succeeded` | `INPUT_SCHEMA` («una corrida exitosa no se reintenta») |
| Mismo caso, misma versión del caso y mismo escenario | `INPUT_SCHEMA`, diciendo cuál no coincide |
| Si está publicada, pasa la verificación de integridad (`read_run`) | `HASH_MISMATCH` |

- El reintento siempre es una corrida **nueva**, con `run_id` nuevo; la anterior queda intacta (se comprueba su huella).
- Se comprueba antes de crear nada: un reintento rechazado no deja carpeta temporal ni bloqueo.
- Se puede reintentar un reintento. Se puede reintentar una interrumpida en la misma llamada que la aparta.

## Verificación

**Pruebas.** 64 pruebas nuevas; 1 más se salta (solo aplica fuera de Windows). Suite completa: **1684 pasan, 11 saltadas**. Formato, lint, tipos, contratos y `.gitignore` sin observaciones (`scripts/check.ps1`).

| Grupo | Pruebas | Qué cubren |
|---|---|---|
| Bloqueo | 10 | Tomar, soltar, soltar dos veces, archivo sin dueño, otro proceso vivo, proceso muerto a la fuerza, hijo que no mantiene el bloqueo, archivo que se está borrando |
| Interrumpidas | 21 | Apartar sin perder nada, no publicar nunca, dos veces el mismo `run_id`, corrida viva intacta, corrida viva en otro programa y luego terminada a la fuerza, manifiesto ilegible/grande/recién reescrito, carpeta que no se puede mover, unión, listado con marca dañada |
| Reintentos | 21 | Cada regla de arriba, interrumpidas, alteradas, reintento de reintento, la anterior no cambia |
| Grupo de procesos | 4 | Cerrar mata lo de adentro, proceso inexistente, el programa muerto mata a su hijo, un nieto no sobrevive a la corrida |
| Con SUMO real | 8 | Reintento de tiempo agotado y de cancelada, exitosa no se reintenta, caída apartada al empezar, reintento de interrumpida, `run_inputs` con reintento, programa terminado a la fuerza con SUMO corriendo |

**Mutaciones.** 53 cambios a propósito sobre el código nuevo. **49 detectados en la primera pasada y 4 sobrevivieron.** Los 2 huecos reales (la prueba de la unión pasaba porque la carpeta destino era nueva; el cierre del grupo al terminar la corrida no se comprobaba con el programa todavía vivo) se cerraron con pruebas y esos 2 pasaron a detectarse. Quedan 2 justificadas:

| Sobrevive | Por qué se acepta |
|---|---|
| Soltar el bloqueo de forma explícita antes de cerrar el archivo | Equivalente: en Windows, cerrar el archivo también lo suelta |
| Cerrar el acceso temporal al proceso al meterlo en el grupo | Equivalente: no cambia nada observable; el sistema lo libera al terminar el programa |

**Caso real** (`ESC-SINT-001`, SUMO 1.27.1):

| Prueba | Resultado |
|---|---|
| Cancelada a los 3 s y reintentada | La primera queda `cancelled` y verificable; el reintento es `succeeded`, con `run_id` nuevo y `retry_of` correcto |
| Programa terminado a la fuerza a los 3 s | SUMO vivo antes del corte, **muerto después**. Ninguna corrida publicada por el corte |
| Siguiente corrida | Aparta la caída a `.incompletas/`, con `statistics.xml`, `sumo.log`, `sumo.stderr.txt`, `sumo.stdout.txt` y `tripinfo.xml` conservados y estado provisional `running` |
| Reintento de la interrumpida | `succeeded`, `retry_of` correcto, 7,1 s |
| `sumo.exe` vivos al final | 0 |

## Hallazgos de la inspección

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | **Un SUMO huérfano.** Si el programa se termina a la fuerza, SUMO seguía vivo escribiendo en una corrida que nadie vigilaba, sin tope de tiempo. La detección de caídas por sí sola no lo resolvía | `KillOnClose`: el proceso entra en un grupo que el sistema mata cuando el programa muere. Medido en vivo con SUMO real |
| 2 | **El archivo de bloqueo anterior no servía.** Creado con `O_EXCL`, una caída lo dejaba para siempre y nadie podía volver a usar ese `run_id` ni saber si el dueño seguía vivo | `RunLock`: el sistema lo suelta solo; un archivo sin dueño se retoma |
| 3 | **Una prueba mía pasaba por la razón equivocada.** La de la unión con nombre temporal no la fallaba la unión sino lo nuevo de la carpeta | Se hizo vieja la carpeta destino; la mutación correspondiente pasó a detectarse |
| 4 | **Una medición mía registraba el proceso equivocado.** En la prueba con SUMO real, el número de proceso anotado era el de la consulta de versión | Solo se anota el proceso que corre en una carpeta de corrida |
| 5 | **Cambia el listado de `case receive`.** Antes mostraba la carpeta `.tmp-…`; ahora la corrida caída se aparta y se muestra `.incompletas/<run_id>`. El informe de hallazgos usa el nuevo nombre | Se actualizó la prueba de DEV00 que esperaba `.tmp-` y se agregó que la carpeta ya no queda en `.tmp-` |

## Desviaciones frente a F0

| Tema | F0 | Lo construido | Por qué |
|---|---|---|---|
| Procesos huérfanos (D8) | No se mencionaba | SUMO muere con el programa (Windows) | Una corrida «interrumpida de verdad» dejaba un SUMO vivo y sin límite de tiempo (hallazgo 1) |
| Carpeta sin manifiesto legible | No se mencionaba | Se espera 60 s antes de apartarla | Una carpeta recién creada o con el manifiesto reescribiéndose no es una caída |
| Nombre en `.incompletas` | `.incompletas/<run_id>/` | Igual, con sufijo `-2`, `-3` si el mismo `run_id` cayó antes | Nunca se sobrescribe evidencia |

## Límites que conviene conocer

- **Linux y macOS no se probaron aquí** (el equipo es Windows). El bloqueo usa `fcntl` y la regla de borrar el archivo con el bloqueo puesto, escritos por lectura y por la documentación del sistema; las pruebas están hechas para correr en ambos.
- **Fuera de Windows, SUMO no muere con el programa** (`KillOnClose` solo actúa en Windows). Un SUMO huérfano seguiría; la carpeta no se podría apartar mientras tenga archivos abiertos y se reintentaría después.
- **Si el programa ya corre dentro de un trabajo de Windows que no admite anidar** (Windows anteriores a 8), `KillOnClose` no se activa y la corrida sigue sin esa garantía. No se pudo probar aquí.
- **Ctrl+C real de teclado** sigue sin probarse en vivo (heredado de F2).
- **La carpeta `.incompletas` crece sin límite.** No hay política de limpieza; es evidencia y no se borra sola.

## Qué no hace F3 (queda para las fases siguientes)

- **F4:** el comando `python -m semaforo simulate run` con `--retry-of`. Hoy se usa solo desde código.
- **F5:** verificación final, mutaciones, inspección y cierre de HU04 (QA08, QA10, QA31 parcial).

## Estado del repositorio

- Archivos nuevos: `lock.py`, `interrupted.py`, `retry.py`, `job.py`, `process_tools.py` y cinco archivos de pruebas. Cambian `store.py`, `runner.py`, `run_inputs.py`, `process.py`, `reception.py`, `reception_models.py` y una prueba de DEV00.
- Autor `crisroco`, sin línea de coautoría.
- Sin subir: 16 commits locales con este. `origin/main` sigue en `9fb7944`. No se ha hecho push: se sube cuando lo pida el Product Owner.
