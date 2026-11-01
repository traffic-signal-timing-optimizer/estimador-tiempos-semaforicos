# Acta 2026-11-01: DEV07 · F4 (comando `simulate run`)

Written for: el Product Owner y el equipo, para revisar cómo se ejecuta ahora una simulación con un solo comando y qué significa cada código de salida.

- **Tipo:** fase F4 de DEV07 (HU04; P0, tamaño M). Dependencias: F0 a F3 de DEV07.
- **Autorización:** el Product Owner delegó la decisión de incluir el comando en F0 (decisión «Sí») y aprobó F4 («ejecuta f4»). Modelo: Sonnet, el sugerido en F0.
- **Decisión que aplica:** D12 de F0 (comando y códigos de salida) y la decisión delegada n.º 3 (cancelada = código 4 con `status: cancelled`).
- **Datos:** sintéticos. El caso real usa la carpeta que publicó DEV06 en F2.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `app/simulate.py` | `run_prepared`: aparta las corridas caídas, ejecuta la carpeta de entradas y arma el informe `RunReport`; `exit_code_of`: código de salida de una corrida publicada |
| `cli/main.py` | Grupo `simulate`, acción `run`, y el resumen para la persona |
| `README.md` | Sección «Ejecutar una simulación: `simulate run`» con los argumentos y los códigos |

La interfaz solo traduce argumentos y resultados; la lógica vive en la capa `app` (ADR01), como el resto de los comandos.

## El comando

```
python -m semaforo simulate run --inputs <carpeta> [--workspace datos] [--sumo-bin RUTA] [--wall-timeout SEGUNDOS] [--retry-of RUN_ID] [--debug]
```

- La corrida se publica en `<workspace>/ejecuciones/<run_id>`.
- `--wall-timeout` acepta solo números mayores que cero (rechaza 0, negativos, texto, `inf` y `nan` con código 2).
- Por la **salida estándar** va solo el JSON; por la **salida de error**, un resumen en lenguaje sencillo (corrida y estado, motivo si fracasó, y las corridas caídas que se apartaron).

**Informe (`RunReport`):** `status` (`succeeded`, `failed` o `cancelled`), `run_id`, `path`, `retry_of`, `scenario_id`, `error_code`, `error_message`, `timing` (el contenido de `tiempos.json`), `summary` (resumen de SUMO), `conciliation` (conteos de la cohorte), `recovered_interrupted` y `exit_code`.

| Código | Cuándo |
|---|---|
| 0 | Corrida exitosa |
| 2 | Carpeta de entradas inválida o inexistente; `--retry-of` que no se puede reintentar; argumento mal escrito |
| 3 | Falta SUMO |
| 4 | Corrida fallida (error de SUMO, tiempo agotado, salidas inválidas), **cancelada**, o falta de memoria o espacio |
| 5 | Carpeta de entradas alterada (huella distinta) o ruta no permitida |
| 1 | Error interno (con `--debug` se ve la traza) |

**Una corrida fallida o cancelada no es una excepción:** queda publicada con sus registros y salidas parciales y el informe lo dice. Los errores previos a ejecutar (entradas, SUMO, reintento no válido, recursos) salen como JSON `{"status": "error", "code", "field", "message"}` con el código que corresponde.

## Verificación

**Pruebas.** 50 pruebas nuevas. Suite completa: **1734 pasan, 11 saltadas**. Formato, lint, tipos, contratos y `.gitignore` sin observaciones (`scripts/check.ps1`).

| Grupo | Pruebas | Qué cubren |
|---|---|---|
| Informe y códigos (sin SUMO) | 19 | Cada código de salida, informe de fallida y de exitosa, `tiempos.json` y conciliación leídos de la corrida, archivos ausentes, dañados o demasiado grandes, límites y reintento que llegan a la corrida, corridas caídas apartadas y reportadas |
| Comando (sin SUMO) | 22 | JSON solo en la salida estándar, código igual al del informe, resumen para la persona, argumentos y valores por defecto, `--wall-timeout` inválido, `--inputs` obligatorio, errores previos con sus códigos, error interno y `--debug` |
| De punta a punta con SUMO real | 9 | Proceso aparte: exitosa (0), tiempo agotado (4), reintento de fallida, exitosa no reintentable (2), carpeta inexistente (2), SUMO ausente (3), carpeta alterada (5, sin crear nada), caída apartada y cancelada (4, `status: cancelled`, sin conciliar) |

**Mutaciones.** 36 cambios a propósito sobre el código nuevo. **35 detectados en la primera pasada y 1 sobrevivió:** quitar la regla «cancelada = 4». Era un hueco real de mi prueba: el ayudante que fabricaba corridas canceladas les ponía un error, cosa que el corredor no hace, y el error daba 4 por casualidad. Se corrigió el ayudante y la mutación pasó a detectarse. No queda ninguna sin detectar.

**Caso real** (`ESC-SINT-001`, SUMO 1.27.1), ejecutado con el comando en un proceso aparte:

| Prueba | Resultado |
|---|---|
| Corrida normal | Código 0, `succeeded`, 6,8 s, `completed`; la tabla de conciliación tiene 1780 vehículos, 1338 terminaron |
| `--wall-timeout 1` | Código 4, `failed`, `SIM_TIMEOUT` |
| `--retry-of` de la fallida | Código 0, `succeeded`, `retry_of` correcto |
| `--retry-of` de la exitosa | Código 2, `INPUT_SCHEMA`: «una corrida exitosa no se reintenta» |
| `sumo.exe` vivos al terminar | 0 |

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | **Hueco de una prueba mía** (la regla de la cancelada se podía quitar sin que fallara nada) | Corregido; ver mutaciones |
| 2 | **Ctrl+C antes de lanzar SUMO no se traduce.** Una interrupción mientras se comprueban las entradas (antes de empezar la corrida) no pasa por el control de la corrida: sale la traza de Python, no un JSON | Se deja como límite conocido (abajo); durante la corrida, que es lo largo, sí se cancela de forma ordenada |
| 3 | El nombre de la carpeta de corridas (`ejecuciones`) estaba definido solo en la recepción de DEV00 | `simulate` lo importa de ahí en vez de repetirlo, para que no se desfasen |
| 4 | El README no explicaba el comando nuevo | Se agregó la sección con argumentos y códigos |

## Desviaciones frente a F0

| Tema | F0 (D12) | Lo construido | Por qué |
|---|---|---|---|
| Informe | «`status`, `run_id` y motivo» | Además: resumen de SUMO, tiempos, conciliación y corridas caídas apartadas | Es lo que la persona necesita ver sin abrir la carpeta; son datos que la corrida ya tiene |
| Cancelada | Código 4 con `status: cancelled` | Igual | — |

## Límites que conviene conocer

- **Ctrl+C de teclado en vivo sigue sin probarse** (heredado de F2): la consola de este entorno no lo permite sin afectarla. La cancelación se prueba con la señal de código (la misma que usa Ctrl+C por dentro) y la reacción a la interrupción de la consola con pruebas del corredor.
- **Una interrupción antes de lanzar SUMO** muestra la traza de Python en vez de un JSON (hallazgo 2).
- **`--workspace` por defecto es `datos`** relativo a la carpeta desde donde se ejecuta el comando, igual que en los demás comandos.
- Heredados de F3: Linux y macOS sin probar aquí, y `.incompletas` sin política de limpieza.

## Qué no hace F4 (queda para F5)

- **F5:** verificación final con el caso real, inspección de toda DEV07 contra la documentación y cierre de HU04 con su tabla (QA08, QA10, QA31 parcial, QA09 parcial).

## Estado del repositorio

- Archivos nuevos: `app/simulate.py` y tres archivos de pruebas. Cambian `cli/main.py` y `README.md`.
- Autor `crisroco`, sin línea de coautoría.
- Sin subir: 17 commits locales con este. `origin/main` sigue en `9fb7944`. No se ha hecho push: se sube cuando lo pida el Product Owner.
