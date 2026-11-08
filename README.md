# estimador-tiempos-semaforicos

Prototipo local de estimación de tiempos semafóricos con SUMO, para el cruce de Los Frutales con Javier Prado (Lima). Se usa desde la línea de comandos: `python -m semaforo`.

## Requisitos (Windows)

| Programa | Versión | Cómo comprobarlo en PowerShell |
|---|---|---|
| Python | 3.12, de 64 bits | `python --version` |
| uv (entorno y dependencias) | 0.13 o posterior | `uv --version` |
| Git | cualquiera reciente | `git --version` |
| SUMO | 1.27.1 | `echo $env:SUMO_HOME` muestra la carpeta de SUMO |
| PostgreSQL | 17.9 para DEV31 y las pruebas de base | `Get-Service postgresql-x64-17` |

**Instalar uv**, si `uv --version` no responde:

1. En PowerShell: `python -m pip install --user uv`
2. Agregue esta carpeta a la variable `Path` de su usuario: `%APPDATA%\Python\Python312\Scripts` (Configuración de Windows → Sistema → Información → Configuración avanzada del sistema → Variables de entorno).
3. Cierre PowerShell, ábralo de nuevo y compruebe con `uv --version`.

**SUMO:** el instalador de Windows crea la variable `SUMO_HOME`. Si no existe, `doctor` puede recibir la ruta del ejecutable con `--sumo-bin`.

**Base de evidencia (HU15/DEV31):** PostgreSQL guarda una copia relacional local para consulta; los archivos publicados en `datos/` con sus manifiestos y huellas siguen siendo el original. La instalación y reconstrucción de esa base requieren pasos adicionales a la instalación básica de Python y SUMO: siga [el manual para otra laptop](docs/manuales/instalacion-en-otra-laptop.md). La puerta completa `scripts/check.ps1` requiere PostgreSQL en ejecución y crea bases temporales de prueba. Al 2026-11-08, F4c C0, C1 y C2 están cerradas; [el acta de C2](docs/actas/2026-11-08-dev31-f4c-c2-cierre.md) registra D11 y el cambio de la base vigente. C3 y F5–F8 siguen pendientes de orden del Product Owner. El [plan F4c](docs/actas/2026-11-07-dev31-plan-correcciones-auditoria.md) conserva las puertas aprobadas. La etiqueta «1.1.0-candidato» del [diccionario generado](docs/bd/diccionario.md) identifica el diseño usado en C2; las tres huellas de ese diseño fueron aprobadas en D11.

**Panel de resultados:** `.venv\Scripts\python.exe -m semaforo bd panel` publica en `datos\reportes\panel\<fecha>\` una foto de la base que se abre con doble clic, sin servidor ni internet: datos de entrada, simulaciones, comparación con el plan actual y evidencia. Ver [docs/panel/LEEME.md](docs/panel/LEEME.md).

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

- `runs verify` revisa todas las carpetas guardadas de `datos/` (corridas, recepciones, copias de originales, programas, entradas, reportes de calidad y de réplica, y conjuntos de escenarios) y dice cuáles están íntegras, alteradas, incompletas, en curso o no siguen un formato conocido. Solo lee: no mueve ni corrige nada. Código 0 si nada está alterado; 5 si algo lo está.
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

## Escenarios controlados: `scenarios generate`

```powershell
.venv\Scripts\python.exe -m semaforo scenarios generate --case RUTA\case.json --spec RUTA\spec.json --seed 7 [--workspace datos] [--debug]
```

Genera un conjunto de escenarios de demanda sobre un caso y lo publica. La **especificación** (`spec.json`, con `schema_version` 1.0.0) dice, por **familia** (un patrón de demanda, por ejemplo una hora punta), el rango de flujo en veh/h de cada movimiento del caso, su composición por clase de vehículo, cuántas **perturbaciones** (flujos distintos dentro de los rangos) y cuántas **semillas** (las mismas cifras con otras llegadas) se piden, más la ventana de observación y los tiempos de calentamiento, medición y drenaje. Un ejemplo completo está en `tests\fixtures\scenario_spec.json`.

- **Repetible:** la misma especificación y la misma semilla dan los mismos escenarios, byte a byte, y por eso la misma `content_id`. Una semilla distinta da otros flujos y otras llegadas.
- **Cada escenario** lleva el grupo de su familia, el origen de la especificación y la frontera del caso, y se valida con las reglas del escenario. Todos los vehículos que llegan en cada escenario están en un archivo fijo (`demanda\<escenario>.csv`) enlazado por su huella: cualquier comparador recibe exactamente los mismos vehículos.
- **Se rechaza antes de publicar** un rango invertido (`min > max`) o fuera del dominio de flujos del movimiento, un movimiento sin rango, una composición que no suma 1, más de 200 perturbaciones o 100 semillas por familia, más de 2000 escenarios en total, o un conjunto de más de 2 millones de vehículos. Se listan todos los problemas, cada uno con su regla (`SPEC-…`), su campo y su motivo.
- El conjunto se publica en `<espacio de trabajo>\derivados\escenarios\<caso>\<fecha>_<huella>\` con `spec.json`, `escenarios\`, `demanda\` y un `manifiesto.json` (caso, semilla, huellas, rangos y flujos usados por escenario). Nunca se sobrescribe, y `runs verify` lo revisa.

| Código de salida | Significado |
|---|---|
| 0 | conjunto publicado |
| 2 | semilla o argumentos mal escritos, o el caso o la especificación no existen o no son válidos (no se publica nada) |
| 5 | ruta no permitida (un enlace) o el conjunto ya existe |
| 1 | error interno; repita con `--debug` para ver el detalle |

## Particiones sin fuga de la prueba: `splits create` y `splits validate`

```powershell
.venv\Scripts\python.exe -m semaforo splits create --scenarios CARPETA_DEL_CONJUNTO --seed 7 [--policy politica.json] [--workspace datos] [--debug]
.venv\Scripts\python.exe -m semaforo splits validate --split CARPETA_DE_LA_PARTICION --scenarios CARPETA_DEL_CONJUNTO [--debug]
```

`create` reparte las **familias completas** de un conjunto de escenarios (el grupo de cada escenario) entre entrenamiento, validación y prueba, y publica la partición congelada. Una familia nunca se parte: todas sus perturbaciones y semillas van a la misma parte. `validate` comprueba una partición ya publicada contra su conjunto.

- **Proporciones:** `--policy` es un archivo JSON (`schema_version` 1.0.0, `policy_id` y `proportions` con `train`, `validation` y `test`, cada una entre 0 y 1 y con suma 1). Sin archivo se usan las **provisionales** 0.6 / 0.2 / 0.2 (DEC07 pendiente) y el mensaje y el manifiesto lo dicen. Hacen falta al menos tres familias, una por parte. La semilla decide cuáles; la misma entrada y semilla dan siempre la misma partición.
- **Reglas** (se listan todos los problemas, cada uno con su regla `SPLIT-…`, campo y motivo): cada escenario asignado una vez, un grupo en una sola parte, el grupo de cada asignación es el del escenario, las tres partes con grupos, partición congelada, y ninguna fuente de campo en dos partes.
- **La prueba se reserva una sola vez:** se publica en `<espacio de trabajo>\derivados\particiones\<caso>\<huella16>\`, con `split.json` (contrato `split` v1.0) y `manifiesto.json`, y la carpeta lleva la huella del conjunto. Nunca se sobrescribe, así que **un conjunto tiene una sola partición**; para otra partición hace falta un conjunto nuevo. `runs verify` la revisa.
- **Bloqueo en el código:** quien ajusta recibe la vista de desarrollo (`semaforo.aprendizaje.split_access`), que solo trae entrenamiento y validación; pedir la prueba para ajustar, seleccionar o repetir el ajuste es un error.

| Código de salida | Significado |
|---|---|
| 0 | partición publicada o válida |
| 2 | argumentos mal escritos, conjunto o política inválidos, o partición con problemas (no se publica nada) |
| 5 | ruta no permitida (un enlace), conjunto o partición alterados, o el conjunto ya tiene su partición |
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
