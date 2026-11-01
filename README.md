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

## Desarrollo

Verificaciones completas (estilo, tipos, pruebas y contratos):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
```

Para que cada commit pase por ruff, instale los hooks una vez: `.venv\Scripts\pre-commit.exe install`.

## Documentación

- `docs/actas/`: decisiones y registro de cada fase.
- `docs/adr/`: decisiones de arquitectura.
- `docs/recepcion/`: informes públicos de las recepciones de la simulación.
