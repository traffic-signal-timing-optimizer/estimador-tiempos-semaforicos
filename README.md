# estimador-tiempos-semaforicos

Prototipo local de estimación de tiempos semafóricos con SUMO, para el cruce de Los Frutales con Javier Prado (Lima). Se usa desde la línea de comandos: `python -m semaforo`.

## Requisitos (Windows)

| Programa | Versión | Cómo comprobarlo en PowerShell |
|---|---|---|
| Python | 3.12, de 64 bits | `python --version` |
| uv (entorno y dependencias) | 0.13 o posterior | `uv --version` |
| Git | cualquiera reciente | `git --version` |
| SUMO | 1.27.1 | `echo $env:SUMO_HOME` muestra la carpeta de SUMO |

**Instalar uv**, si `uv --version` no responde:

1. En PowerShell: `python -m pip install --user uv`
2. Agregue esta carpeta a la variable `Path` de su usuario: `%APPDATA%\Python\Python312\Scripts` (Configuración de Windows → Sistema → Información → Configuración avanzada del sistema → Variables de entorno).
3. Cierre PowerShell, ábralo de nuevo y compruebe con `uv --version`.

**SUMO:** el instalador de Windows crea la variable `SUMO_HOME`. Si no existe, `doctor` puede recibir la ruta del ejecutable con `--sumo-bin`.

## Instalación desde cero

En PowerShell, en la carpeta donde quiera el proyecto:

```powershell
git clone https://github.com/traffic-signal-timing-optimizer/estimador-tiempos-semaforicos.git
cd estimador-tiempos-semaforicos
uv sync --frozen
New-Item -ItemType Directory datos
.venv\Scripts\python.exe -m semaforo doctor
```

- `uv sync --frozen` crea la carpeta `.venv` e instala exactamente las versiones de `uv.lock`, sin actualizar nada.
- `datos` es la carpeta de trabajo. Git no la versiona porque guarda simulaciones y resultados del equipo.
- `doctor` debe terminar con «Diagnóstico todo bien (código de salida 0)» o «con avisos». Si termina «con errores», la línea marcada `[ERROR]` dice qué falta.

## Diagnóstico del entorno: `doctor`

```powershell
.venv\Scripts\python.exe -m semaforo doctor [--workspace datos] [--sumo-bin RUTA\sumo.exe] [--debug]
```

Comprueba Python, los paquetes, el sistema operativo, la CPU, la RAM, la carpeta de trabajo, el espacio libre y SUMO. Por la salida estándar escribe el diagnóstico en JSON; por la salida de error, una línea por comprobación (`[bien]`, `[AVISO]` o `[ERROR]`).

| Código de salida | Significado |
|---|---|
| 0 | todo bien, o solo avisos (por ejemplo, otra versión de SUMO) |
| 2 | la carpeta de trabajo no existe |
| 3 | falta Python 3.12, un paquete o SUMO |
| 5 | la carpeta de trabajo es un enlace, no es una carpeta o no admite escritura |
| 1 | error interno; repita con `--debug` para ver el detalle |

La RAM y el espacio libre solo se informan: los umbrales los fija el piloto.

## Ejecutar una simulación: `simulate run`

```powershell
.venv\Scripts\python.exe -m semaforo simulate run --inputs CARPETA_DE_ENTRADAS [--workspace datos] [--sumo-bin RUTA\sumo.exe] [--wall-timeout SEGUNDOS] [--retry-of RUN_ID] [--debug]
```

Ejecuta SUMO sobre una carpeta de entradas ya preparada y publica la corrida en `<workspace>\ejecuciones\<run_id>`. Antes de empezar comprueba que la carpeta de entradas no se haya alterado, aparta las corridas que una caída anterior dejó a medias (quedan en `ejecuciones\.incompletas`, sin borrarse) y exige memoria y espacio libres. Por la salida estándar escribe un informe en JSON; por la salida de error, un resumen para la persona.

- **Lea `status` del JSON, no solo el código de salida.** Una corrida fallida o cancelada también queda publicada, con sus registros y salidas parciales.
- `--wall-timeout`: tiempo real máximo en segundos (por defecto, 900). Si se pasa, SUMO se corta y la corrida queda `failed`.
- `--retry-of`: vuelve a intentar una corrida `failed`, `cancelled` o interrumpida del mismo caso, versión y escenario. Siempre crea una corrida nueva; la anterior no se toca. Una corrida exitosa no se reintenta.
- Ctrl+C cancela la corrida de forma ordenada: SUMO se corta, se conservan los registros y la corrida queda `cancelled`.

| Código de salida | Significado |
|---|---|
| 0 | corrida exitosa |
| 2 | carpeta de entradas inválida, o `--retry-of` que no se puede reintentar |
| 3 | falta SUMO |
| 4 | corrida fallida, tiempo agotado o cancelada (mire `status`), o falta memoria o espacio |
| 5 | carpeta de entradas alterada o ruta no permitida |
| 1 | error interno; repita con `--debug` para ver el detalle |

## Revisar y comparar corridas: `runs verify` y `runs compare`

```powershell
.venv\Scripts\python.exe -m semaforo runs verify [--workspace datos] [--run-id RUN_ID] [--debug]
.venv\Scripts\python.exe -m semaforo runs compare --run-a RUN_ID --run-b RUN_ID [--workspace datos] [--tolerance 1e-9] [--debug]
```

- `runs verify` revisa todas las carpetas guardadas de `datos/` (corridas, recepciones, copias de originales, programas, entradas, reportes de calidad y de réplica) y dice cuáles están íntegras, alteradas, incompletas, en curso o no siguen un formato conocido. Solo lee: no mueve ni corrige nada. Código 0 si nada está alterado; 5 si algo lo está.
- `runs verify --run-id` sigue una corrida hacia atrás: su carpeta de entradas, el programa derivado y el caso (o la copia de originales, en las corridas de recepción) y la corrida anterior si es un reintento. Código 0 si la cadena está completa; 5 si un eslabón está alterado; 3 si falta o cambió alguno.
- `runs compare` dice si dos corridas son réplicas: mismas entradas y semilla, y mismos resultados sin contar la hora ni las duraciones. Publica el reporte en `datos/derivados/replicas/` y sale con código 0 tanto si son `equivalent` como `different` (mire `status`). `--tolerance` es la diferencia admitida en números con decimales.

## Informes HTML del caso y de los datos: `report case` y `report data`

```powershell
.venv\Scripts\python.exe -m semaforo report case --case RUTA\case.json [--workspace datos] [--debug]
.venv\Scripts\python.exe -m semaforo report data --case RUTA\case.json --quality-report CARPETA_DEL_REPORTE_DE_CALIDAD [--workspace datos] [--debug]
```

Cada comando publica una página HTML que se abre con doble clic en el navegador (no usa internet ni servidor) y escribe en la salida estándar un JSON con la ruta del informe; el mensaje para la persona (salida de error) da la ruta completa de la página.

- `report case` muestra el origen (sintético o real), el estado de la validación con sus 19 reglas, los límites del plan, los movimientos, las clases de vehículos y la evidencia de las restricciones. Un caso inválido **también** genera informe, con sus problemas a la vista: lea `case_status` del JSON.
- `report data` muestra la cobertura, los datos que faltan (nunca como cero), la comparación con el conteo de control, lo observado, corregido y excluido, y la causa de cada exclusión. Parte del reporte de calidad que ya publicó la preparación de datos (`derivados/calidad/<caso>/<fecha>_<huella>`), que se verifica antes de mostrarlo.
- Los informes se publican en `<espacio de trabajo>\reportes\informes\<caso|datos>\<id-del-caso>\<fecha>_<huella>\` con su `manifiesto.json` (huellas de la página y de lo que se usó). Nunca se sobrescriben. Todo el texto se escapa: un identificador con `<script>` se ve como texto y no se ejecuta.

| Código de salida | Significado |
|---|---|
| 0 | informe publicado (también con un caso inválido o con avisos) |
| 2 | el archivo del caso o la carpeta del reporte de calidad no existen o no son válidos, o el reporte es de otro caso |
| 5 | ruta no permitida (un enlace), reporte alterado, caso cambiado desde que se generó el reporte, o el informe ya existe |
| 1 | error interno; repita con `--debug` para ver el detalle |

## Desarrollo

Verificaciones completas (estilo, tipos, pruebas y contratos):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

Para que cada commit pase por ruff, instale los hooks una vez: `.venv\Scripts\pre-commit.exe install`.

### Evidencia de pruebas (QA01 a QA10)

```powershell
.venv\Scripts\python.exe scripts\evidencia.py [--sensibilidad] [--allow-dirty]
```

Corre toda la suite y guarda el registro de la ejecución: comando, fecha, entorno, commit, huella de los datos de prueba, resultado por caso QA01 a QA10, pruebas saltadas con su motivo y fallos con su gravedad y tarea. El resumen, sin rutas de su equipo, queda en `docs/evidencia/<fecha>_<commit>/` (se versiona); el registro completo de pytest, en `datos/reportes/evidencia/` (no se versiona). Con `--sensibilidad` incluye el ensayo que rompe a propósito una regla de cada caso y comprueba que las pruebas lo detectan (varios minutos). Se niega a correr con cambios sin guardar, salvo `--allow-dirty`. Termina con código 1 si hay fallos críticos. Qué pruebas demuestran cada caso está en `tests/qa_catalog.py`.

## Documentación

- `docs/actas/`: decisiones y registro de cada fase.
- `docs/adr/`: decisiones de arquitectura.
- `docs/recepcion/`: informes públicos de las recepciones de la simulación.
