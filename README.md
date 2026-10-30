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
