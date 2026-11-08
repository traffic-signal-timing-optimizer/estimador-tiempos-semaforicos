Escrito para: el Product Owner y cualquier persona o agente de IA que deba dejar el proyecto funcionando en una laptop nueva, sin conocer el proyecto. No se asume ningún paso previo: todo lo que hace falta está en este documento.

# Manual: levantar el proyecto en otra laptop

Este manual permite pasar el proyecto **de extremo a extremo** a una laptop con Windows: programas, entorno de Python, PostgreSQL, SUMO, base de datos y pruebas que confirman que todo funciona.

El procedimiento se cotejó en la laptop de origen el 2026-11-07, en el corte `05e55b3`; allí se registraron `doctor`, estado de red, conciliación, regeneración y pruebas rápidas. **No se ha demostrado una instalación desde cero en otra laptop ni se ejecutaron allí T1 a T13 en conjunto.** La base de la laptop de origen se reconstruyó en C2, con D11 y P0–P9 completados el 2026-11-08 ([acta de cierre](../actas/2026-11-08-dev31-f4c-c2-cierre.md)). La puerta completa más reciente pasó con 5434 pruebas, 1 omitida y 43/43 contratos. Las versiones de la sección 1 se basan en el lockfile comprobado en el corte inicial; revíselas si cambia `uv.lock`.

---

## 0. Antes de empezar

### 0.1 ¿Qué caso es el suyo?

Hay dos formas de pasar el proyecto. Elija **una** y siga la sección que le corresponda. Las dos usan las mismas secciones 2, 3, 4 y 5.

| Caso | Qué hace | Qué sí llega | Qué NO llega (hay que traerlo aparte) |
|---|---|---|---|
| **A. Clonar desde GitHub** | `git clone` del repositorio en la laptop nueva | El código, las pruebas, `uv.lock`, las actas y las huellas de referencia (`docs/`) | `datos\` (2.9 GB), `documentacion\`, los respaldos de la base, el entorno `.venv` y la configuración de PostgreSQL de cada usuario |
| **B. Copiar la carpeta** | Copiar la carpeta del proyecto completa (incluido `.git`) desde la laptop de origen | Todo lo del caso A, más `datos\` y `documentacion\` | El entorno `.venv` (no se copia, se vuelve a crear) y la configuración de PostgreSQL de cada usuario |

**Lo que no se copia en ningún caso** (son de cada usuario de Windows o se generan de nuevo):

- `.venv\`: guarda rutas de la laptop de origen. Se borra y se vuelve a crear (sección 4.2).
- `%APPDATA%\postgresql\` (`pgpass.conf` y `.pg_service.conf`): contraseñas de la base. Se generan de nuevo con `bd iniciar` (sección 5.3). **Nunca** se copian ni se escriben en el repositorio ni en un chat.
- `D:\pgdata\semaforo\`: los archivos internos de PostgreSQL. Se regeneran desde `datos\`.

### 0.2 Qué necesita tener la laptop nueva

- Windows 11 de 64 bits (probado en Windows 11 Pro, versión 10.0.26200).
- Al menos **16 GB de RAM** (la de origen tiene 15.4 GB) y **16 procesadores lógicos** (la de origen tiene 16). Con menos RAM, las pruebas con SUMO pueden fallar por memoria.
- Espacio libre: al menos **10 GB en la unidad de `datos\`** (2.9 GB de datos en el caso B, más el entorno) y **5 GB en `D:`** para la base (`D:\pgdata\semaforo`). Si no hay `D:`, use otra unidad y cambie la ruta en la sección 5.2 (y en `bd iniciar`).
- Conexión a internet para instalar los programas y las librerías de Python.
- Permisos de administrador en Windows para instalar PostgreSQL y SUMO.
- Una cuenta de GitHub con acceso al repositorio `traffic-signal-timing-optimizer/estimador-tiempos-semaforicos` (caso A y, para actualizar, el caso B).

---

## 1. Qué programas y versiones se usan

Instale **exactamente estas versiones**. Si instala otra, el proyecto puede no comportarse igual y la verificación de la sección 6 puede no coincidir.

| Programa | Versión probada | Fuente oficial | Cómo se comprueba |
|---|---|---|---|
| Windows | 11 Pro, 64 bits | (ya instalado) | `winver` |
| PowerShell | 5.1 (viene con Windows) | (ya instalado) | `$PSVersionTable.PSVersion` |
| Git para Windows | 2.49.0.windows.1 | https://git-scm.com/download/win | `git --version` |
| Python | **3.12.3**, 64 bits (el proyecto exige 3.12.x) | https://www.python.org/downloads/release/python-3123/ | `python --version` |
| uv (gestor de entorno) | **0.13.2** | `python -m pip install uv==0.13.2` | `uv --version` |
| PostgreSQL | **17.9**, Windows x86-64 | https://www.enterprisedb.com/downloads/postgres-postgresql-downloads (instalador de EDB, versión 17.9) | `& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" --version` |
| SUMO (simulador de tránsito) | **1.27.1** | https://sumo.dlr.de/docs/Downloads.php (Eclipse SUMO, instalador de Windows 1.27.1) | `& "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe" --version` |

Las librerías de Python **no se instalan a mano**: las instala `uv sync --frozen` (sección 4) con las versiones exactas de `uv.lock`:

| Librería | Versión | Para qué |
|---|---|---|
| psycopg[binary] | 3.3.8 | conexión con PostgreSQL |
| pydantic | 2.14.1 | validación de datos |
| defusedxml | 0.7.1 | lectura segura de XML de SUMO |
| pytest | 9.1.1 | pruebas |
| hypothesis | 6.170.3 | pruebas con datos generados |
| ruff | 0.17.1 | estilo y formato de código |
| pyright | 1.1.414 | revisión de tipos |
| pre-commit | 4.7.0 | ganchos de git (opcional) |
| pip-audit | 2.10.1 | revisión de vulnerabilidades (opcional) |

Requisitos de Python que el proyecto declara en `pyproject.toml`: `requires-python = ">=3.12,<3.13"`. Y `uv.lock` usa `requires-python = "==3.12.*"`.

---

## 2. Instalación de los programas

Haga los pasos en orden. Después de cada instalación, cierre y vuelva a abrir PowerShell para que tome el PATH nuevo.

### 2.1 Git para Windows 2.49.0

1. Descargue el instalador de la versión 2.49.0 (Windows, 64 bits) desde https://git-scm.com.
2. Ejecútelo con las opciones por defecto. En la pantalla «Choosing the default editor» puede dejar Vim o elegir otro; no cambia nada del proyecto.
3. Compruebe en PowerShell:
   ```powershell
   git --version
   ```
   Debe mostrar `git version 2.49.0.windows.1` (o una versión 2.49 equivalente).

### 2.2 Python 3.12.3

1. Descargue **Python 3.12.3, Windows installer (64-bit)** desde https://www.python.org/downloads/release/python-3123/.
2. Ejecútelo. En la **primera pantalla** marque **«Add python.exe to PATH»** (casilla abajo). Luego elija **«Install Now»**. Esto instala para el usuario actual, en la carpeta por defecto `C:\Users\<su-usuario>\AppData\Local\Programs\Python\Python312`.
3. Cierre el instalador. Abra PowerShell nuevo y compruebe:
   ```powershell
   python --version
   py -0p
   ```
   `python --version` debe mostrar `Python 3.12.3`. `py -0p` debe listar una línea con `3.12` y la ruta de ese Python.

   > Si `python --version` muestra otra versión, o no responde, revise que la casilla «Add python.exe to PATH» estuviera marcada. Desinstale la versión mal instalada desde «Configuración → Aplicaciones» y repita este paso.

### 2.3 uv 0.13.2

En PowerShell:

```powershell
python -m pip install --user uv==0.13.2
uv --version
```

Debe mostrar `uv 0.13.2`. Si dice «no se reconoce como un comando», la carpeta de los ejecutables de usuario no está en el PATH. Agréguela (`%APPDATA%\Python\Python312\Scripts`) en «Variables de entorno de usuario» y reabra PowerShell. El README del proyecto tiene el mismo paso con imágenes de la ruta.

### 2.4 PostgreSQL 17.9

1. Descargue el instalador de **PostgreSQL 17.9 para Windows x86-64** desde el sitio de EDB (sección 1).
2. Ejecútelo como administrador. Pantallas, en orden:
   - **Installation Directory:** deje `C:\Program Files\PostgreSQL\17`.
   - **Select Components:** deje marcados **PostgreSQL Server**, **Command Line Tools** y **pgAdmin 4** (pgAdmin es opcional, pero útil para mirar la base). **Es imprescindible** que quede marcado **Command Line Tools**: trae `pg_dump` y `pg_restore`, que usa el proyecto para los respaldos.
   - **Data Directory:** deje `C:\Program Files\PostgreSQL\17\data`.
   - **Password:** escriba la contraseña del usuario **postgres** (administrador del servidor). **Guárdela en su administrador de contraseñas.** No la escriba en ningún archivo del proyecto ni en un chat.
   - **Port:** deje **5432**.
   - **Locale:** deje el valor por defecto.
   - Al terminar, **desmarque «Launch Stack Builder»** y finalice.
3. Compruebe que el servicio está activo, en PowerShell:
   ```powershell
   Get-Service postgresql-x64-17
   ```
   Debe mostrar `Status: Running` y `StartType: Automatic`. Si no, ejecútelo como administrador: `Start-Service postgresql-x64-17` y `Set-Service postgresql-x64-17 -StartupType Automatic`.
4. Compruebe las herramientas de respaldo:
   ```powershell
   & "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" --version
   ```
   Debe mostrar `pg_dump (PostgreSQL) 17.9`.

> **Nota sobre `listen_addresses`:** el instalador de EDB deja PostgreSQL escuchando en todas las direcciones (`*`). El proyecto **no lo cambia** (decisión del PO del 2026-11-06). Lo que sí debe quedar cerrado es el archivo de reglas `pg_hba.conf`: solo debe admitir `127.0.0.1` y `::1`. Esto se comprueba en la sección 6 (prueba T6).

### 2.5 SUMO 1.27.1

1. Descargue el instalador de Windows de **Eclipse SUMO 1.27.1** desde https://sumo.dlr.de/docs/Downloads.php y ejecútelo como administrador.
2. Deje la carpeta por defecto: `C:\Program Files (x86)\Eclipse\Sumo`.
3. Compruebe, en PowerShell:
   ```powershell
   & "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe" --version
   ```
   Debe mostrar `Eclipse SUMO sumo Version 1.27.1`.
4. Defina la variable `SUMO_HOME` (en «Variables de entorno de usuario»), si el instalador no la creó:
   - Nombre: `SUMO_HOME`
   - Valor: `C:\Program Files (x86)\Eclipse\Sumo`

   Cierre y reabra PowerShell, y compruebe:
   ```powershell
   echo $env:SUMO_HOME
   ```

---

## 3. Preparar la carpeta y el repositorio

Elija **un solo caso**: 3.A (clonar) o 3.B (copiar). Sin `datos\` ni `documentacion\` el código funciona, pero la base queda vacía y los informes no tienen datos (ver 0.1).

Ejemplo de carpeta: `D:\proyectos`. Use cualquier carpeta **fuera de OneDrive** y que no tenga espacios raros. Los comandos de este manual usan el nombre `estimador-tiempos-semaforicos`; si cambia la carpeta, cámbiela también en los comandos.

### 3.A Caso A: clonar desde GitHub

1. Abra PowerShell y vaya a la carpeta de proyectos:
   ```powershell
   New-Item -ItemType Directory -Force D:\proyectos | Out-Null
   Set-Location D:\proyectos
   ```
2. Clone el repositorio (la primera vez, Git le pedirá iniciar sesión en GitHub con su cuenta):
   ```powershell
   git clone https://github.com/traffic-signal-timing-optimizer/estimador-tiempos-semaforicos.git
   Set-Location estimador-tiempos-semaforicos
   ```
3. Compruebe que está en `main` y en el commit esperado:
   ```powershell
   git branch --show-current
   git log -1 --oneline
   ```
   Debe mostrar `main`. Compare el commit con la referencia publicada en GitHub en el momento de clonar; no se exige un hash fijo. Para reproducir el corte C2 de la laptop de origen, compruebe que el historial incluya `49e29af` (acta de cierre) y `f845262` (huellas aprobadas).
4. **Traiga `datos\` desde la laptop de origen.** No está en git. Copie la carpeta completa `datos` (2.9 GB, por ejemplo con un disco externo) a `D:\proyectos\estimador-tiempos-semaforicos\datos`. Sin esta carpeta la base quedará vacía (ver sección 5.4 y la prueba T8).
5. Traiga también `documentacion\` (no está en git, es la documentación completa del paquete). Cópiela a `D:\proyectos\estimador-tiempos-semaforicos\documentacion`. No es necesaria para ejecutar el código, pero sí para el proyecto.
6. Siga en la sección 4.

### 3.B Caso B: copiar la carpeta completa

1. Copie la carpeta del proyecto **completa**, incluidos los archivos ocultos (`.git`, `.gitignore`, `.gitattributes`, `.pre-commit-config.yaml`) y `datos\`, `documentacion\` y `docs\`, a `D:\proyectos\estimador-tiempos-semaforicos`. Use un disco externo o una copia directa; el copiado debe ser completo (el `.git` es parte del proyecto).
2. **Borre `.venv`** de la copia. Tiene rutas de la laptop de origen y no funciona en otra máquina:
   ```powershell
   Set-Location D:\proyectos\estimador-tiempos-semaforicos
   Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
   ```
3. Opcional: borre las cachés, que se regeneran solas:
   ```powershell
   Remove-Item -Recurse -Force .pytest_cache, .ruff_cache, .hypothesis -ErrorAction SilentlyContinue
   ```
4. Compruebe el estado de git. Los archivos seguidos deberían conservar el mismo estado que en la carpeta de origen. Pueden aparecer carpetas locales sin seguimiento, como `.claude/` y `docs/auditorias/`:
   ```powershell
   git status --short
   git log -1 --oneline
   ```
   Compare cualquier archivo modificado (`M`) o commit local con el origen antes de continuar; no descarte cambios del PO.
5. Compruebe la integridad de `datos\` (no cambió nada en el traslado):
   ```powershell
   .venv\Scripts\python.exe -m semaforo runs verify --workspace datos
   ```
   Debe terminar con código **0**. Este paso requiere que el `.venv` ya exista: haga primero la sección 4.2 y vuelva aquí.
6. Siga en la sección 4.

---

## 4. Entorno de Python del proyecto

Todo el trabajo se hace desde la carpeta raíz del proyecto (`D:\proyectos\estimador-tiempos-semaforicos`). Compruébelo con:

```powershell
Get-Location
```

### 4.1 Verificar Python antes de crear el entorno

```powershell
python --version
uv python find 3.12
```

- `python --version` debe mostrar `Python 3.12.3`.
- `uv python find 3.12` debe mostrar una ruta que termine en `python.exe`, dentro de `...\Python312\`.

> Si `uv python find 3.12` no encuentra nada, **uv descargará un Python propio de internet**. Eso no es lo que queremos: vuelva a la sección 2.2 y reinstale Python 3.12.3 marcando «Add python.exe to PATH».

### 4.2 Crear el entorno e instalar las librerías

```powershell
uv sync --frozen
```

- `--frozen` instala **exactamente** las versiones de `uv.lock`, sin actualizar nada.
- Crea la carpeta `.venv` dentro del proyecto. Tarda uno o dos minutos la primera vez.
- Termina sin mensajes de error. Si aparece `error:`, lea la línea y no siga hasta resolverla (sección 9).

Compruebe las versiones:

```powershell
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -c "import psycopg, pydantic, defusedxml; print(psycopg.__version__, pydantic.VERSION, defusedxml.__version__)"
.venv\Scripts\ruff.exe --version
.venv\Scripts\pytest.exe --version
```

Resultados esperados: `Python 3.12.3`; `3.3.8 2.14.1 0.7.1`; `ruff 0.17.1`; `pytest 9.1.1`.

### 4.3 Diagnóstico del entorno

```powershell
.venv\Scripts\python.exe -m semaforo doctor --workspace datos
```

- Debe terminar con `Diagnóstico todo bien (código de salida 0)` (o «con avisos», con código 0).
- Si la carpeta `datos` no existe, el código de salida será **2**. Cree la carpeta vacía con `New-Item -ItemType Directory datos` para esta prueba, o copie `datos\` (sección 3). Recuerde que sin `datos\` la prueba T4 cambia de resultado.
- La RAM disponible y el espacio libre solo se informan: el diagnóstico no falla por ellos.

---

## 5. PostgreSQL y SUMO: configuración de la base

### 5.1 Requisito previo

Estos pasos suponen que la sección 2.4 (PostgreSQL 17.9 con su servicio `postgresql-x64-17` en ejecución) está hecha. Compruébelo:

```powershell
Get-Service postgresql-x64-17
```

### 5.2 Carpeta de la base

El proyecto guarda la base en un espacio de tablas llamado `semaforo`, en la carpeta **`D:\pgdata\semaforo`**. Esa carpeta debe **no existir o estar vacía**:

```powershell
Test-Path D:\pgdata\semaforo
```

- Si devuelve `False`: bien, el comando la crea.
- Si devuelve `True` y la carpeta tiene archivos: **no la borre a ciegas**. Consulte al PO. Si es una base anterior, puede tener datos que importan.
- Si no hay unidad `D:`, use otra carpeta vacía, por ejemplo `E:\pgdata\semaforo`, y cámbiela en el comando de la sección 5.3.

### 5.3 Crear el espacio de tablas, los usuarios y la base (`bd iniciar`)

Este comando crea, una sola vez:

1. la carpeta de datos y el espacio de tablas `semaforo`;
2. cuatro usuarios del proyecto (`semaforo_admin`, `semaforo_carga`, `semaforo_lectura`, `semaforo_panel`) con **contraseñas nuevas y aleatorias**;
3. sus contraseñas, en `%APPDATA%\postgresql\pgpass.conf`, y su configuración de conexión, en `%APPDATA%\postgresql\.pg_service.conf`;
4. la base `semaforo`, con `semaforo_admin` como dueño;
5. el esquema de la base (57 tablas y las vistas del panel).

El mismo comando crea también `semaforo_panel`, el usuario con el que se genera el panel de resultados: solo puede leer las vistas aprobadas, ninguna tabla.

Necesita la contraseña del usuario **postgres** (la que puso en la sección 2.4). Pásela **solo para este comando**, como variable de la sesión, y bórrela al terminar. En PowerShell, sin que quede escrita en pantalla:

```powershell
$secure = Read-Host "Contraseña del usuario postgres" -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)

.venv\Scripts\python.exe -m semaforo bd iniciar --carpeta-datos D:\pgdata\semaforo

Remove-Item Env:PGPASSWORD
Remove-Variable secure, ptr
```

- Debe terminar con código **0** y decir `PostgreSQL 17.9 listo: base semaforo, esquema sql-891b34e6c96bf201` (versión C2; en una instalación anterior a C2 aparecería la versión previa).
- **Puede repetirse**: lo que ya existe se deja como está y el informe lo dice.
- Si falla con «no hay conexión», el servicio no está en ejecución (sección 2.4, paso 3).
- Si falla con «permiso denegado» sobre la carpeta, ejecute PowerShell **como administrador** y repita.

Compruebe que quedaron los archivos de conexión (sin abrir ni copiar las contraseñas):

```powershell
Test-Path "$env:APPDATA\postgresql\pgpass.conf"
Test-Path "$env:APPDATA\postgresql\.pg_service.conf"
```

Ambos deben devolver `True`.

### 5.4 Cargar los datos del proyecto en la base

Desde la carpeta raíz del proyecto, con `datos\` ya copiado (sección 3):

```powershell
.venv\Scripts\python.exe -m semaforo bd cargar --preliminar --sueltas
```

- Estas dos opciones son las que usó la carga original de la base: `--preliminar` (el escenario escrito a mano se carga como preliminar) y `--sueltas` (las corridas de DEV19 que ninguna búsqueda usa, cargadas como diagnóstico). **No agregue** `--sin-metricas`.
- Tarda varios minutos. Termina con código **0** y un resumen `Carga <id>: completed`.
- Las 3 corridas de DEV00 quedan excluidas **con decisión** («riesgo aceptado»), que se carga desde `datos\derivados\decisiones\` y el acta en git: no aparecen como error.

Si no tiene `datos\`, este comando termina sin cargar nada y la base queda vacía; no es un error del comando, pero **el proyecto no está completo** hasta copiar `datos\`.

### 5.5 Configuración de red (solo lectura)

```powershell
.venv\Scripts\python.exe -m semaforo bd verificar --red --sin-referencia --hba "C:\Program Files\PostgreSQL\17\data\pg_hba.conf"
```

- El resultado de «reglas» debe ser **`aislada`**: significa que las reglas solo admiten conexiones desde la propia laptop.
- Si el resultado es `abierta`, **deténgase**: alguna regla admite equipos de fuera. Avise al PO; no cambie el archivo por su cuenta.
- Si `pg_hba.conf` no se puede leer (permiso denegado), abra PowerShell como administrador y repita el mismo comando. El resultado `no_verificada` sin `--hba` es normal para un usuario común: el archivo lo lee el administrador.

---

## 6. Pruebas para comprobar que todo funciona

Corra las pruebas **en orden**. Cada una dice qué debe salir. Si una falla, no siga: vaya a la sección 9.

Todas las pruebas se corren desde la carpeta raíz del proyecto.

| Prueba | Comando | Resultado esperado |
|---|---|---|
| **T1. Código** | `git log -1 --oneline` | Muestra un commit de `main` (en el caso B, el mismo commit que en el origen) |
| **T2. Python** | `.venv\Scripts\python.exe --version` | `Python 3.12.3` |
| **T3. Librerías** | `.venv\Scripts\python.exe -c "import psycopg, pydantic, defusedxml; print(psycopg.__version__, pydantic.VERSION, defusedxml.__version__)"` | `3.3.8 2.14.1 0.7.1` |
| **T4. Diagnóstico** | `.venv\Scripts\python.exe -m semaforo doctor --workspace datos` | `Diagnóstico todo bien`, código **0** |
| **T5. SUMO** | `& "$env:SUMO_HOME\bin\sumo.exe" --version` | `Eclipse SUMO sumo Version 1.27.1` |
| **T6. Red** | `.venv\Scripts\python.exe -m semaforo bd verificar --red --sin-referencia --hba "C:\Program Files\PostgreSQL\17\data\pg_hba.conf"` | `reglas ... aislada`, código **0** |
| **T7. Base íntegra** | `.venv\Scripts\python.exe -m semaforo bd verificar` | `Base íntegra`, código **0**, con la referencia de git (ver nota) |
| **T8. Base contra archivos** | `.venv\Scripts\python.exe -m semaforo bd conciliar --sin-recalcular` | `status: equal`, código **0**. Cobertura: 143 publicadas, 140 cargadas, 3 con decisión, 0 faltan, 0 sobran |
| **T9. Regeneración** | `.venv\Scripts\python.exe -m semaforo bd regenerar --workspace datos` | `Base regenerada: igual`, código **0** (tarda varios minutos y borra su base temporal) |
| **T10. Pruebas rápidas** | `.venv\Scripts\pytest.exe -q -m "not bd and not sumo"` | `5080 passed, 1 skipped` (tarda unos 3 minutos; probado el 2026-11-07), sin `FAILED` |
| **T11. Pruebas de la base** | `.venv\Scripts\pytest.exe -q -m bd` | Termina sin fallas. Requiere la sección 5 completa |
| **T12. Pruebas con SUMO** | `.venv\Scripts\pytest.exe -q -m sumo` | Termina sin fallas. Requiere SUMO y `SUMO_HOME` |
| **T14. Panel** | `.venv\Scripts\python.exe -m semaforo bd panel` | `Panel publicado: reportes/panel/<fecha>/index.html`, código **0**. Abra ese `index.html` con doble clic: deben verse las diez páginas, con 130 corridas en Inicio |
| **T13. Puerta completa** | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check.ps1` | Termina con `Todas las verificaciones pasaron.`, código **0**. Tarda unos 11 minutos |

**Notas sobre estas pruebas:**

- **T7:** la referencia es la versión de `docs/bd/huellas.json` que está **confirmada en git**. Si al momento de hacer este manual esa versión no coincide con la base real (diferencias en `control.artefactos` o en los manifiestos de decisiones), T7 devuelve `difiere` (código 5). En ese caso no es un error de la instalación: avise al PO para actualizar la referencia.
- **T8:** un resultado distinto de `equal` indica que falta algún archivo de `datos\`. Compare la cobertura del informe con el número de la sección 5.4.
- **T9** crea y borra una base temporal (`semaforo_pruebas_*`). No toca `semaforo`.
- **T10 a T13** también crean bases temporales con nombre `semaforo_pruebas_*`. Ninguna prueba toca `tickers_report_db`, `trading_predict` ni otras bases del servidor.
- **Referencia de la laptop de origen:** T10 dio 5080 pruebas pasaron en el corte inicial del manual. La puerta completa del cierre C2 dio **5434 pruebas pasaron, 1 omitida y 43/43 contratos**. Los conteos cambian si se agregan o retiran pruebas; cada corte debe terminar sin fallos.

Cuando T1 a T13 pasen, la laptop queda **funcionando**.

---

## 7. Después de la instalación

- **Ejecutar el proyecto:** `README.md` documenta los comandos básicos; las operaciones de la base están en las secciones 5 y 6 de este manual y en `docs/actas/` de DEV31. Use siempre `.venv\Scripts\python.exe -m semaforo ...` desde la carpeta raíz.
- **Actualizar el código** (caso A o B, con GitHub): `git pull` y después `uv sync --frozen`.
- **Generar el panel de resultados:** `.venv\Scripts\python.exe -m semaforo bd panel`. Es una foto de la base: se abre con doble clic y se puede copiar a otra computadora. Ver `docs/panel/LEEME.md`.
- **Respaldar la base:** `.venv\Scripts\python.exe -m semaforo bd respaldar --carpeta D:\respaldos\semaforo`. Cada respaldo sale con su ficha (`.dump` y `.dump.sha256`).
- **Respaldos previos:** la laptop de origen tiene dos respaldos en `D:\respaldos\semaforo` (14 MB cada uno). No son necesarios para reconstruir la base (se reconstruye desde `datos\`), pero conviene copiarlos como respaldo adicional.

---

## 8. Lo que debe quedar fuera de git

El repositorio **no** debe recibir nunca:

- `datos\` (datos, simulaciones y resultados; 2.9 GB);
- `.venv\` (entorno local);
- `%APPDATA%\postgresql\` (contraseñas);
- `.claude\` y `docs\auditorias\` (material local de trabajo).

Las dos últimas carpetas aparecen como «sin seguimiento» en `git status` y se dejan así a propósito.

---

## 9. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `python --version` no responde o muestra otra versión | Python no quedó en el PATH | Reinstale Python 3.12.3 con la casilla «Add python.exe to PATH» (2.2) |
| `uv sync --frozen` dice que no encuentra Python 3.12 | `.venv` apunta a un Python que ya no existe | Borre `.venv` y repita 4.2 |
| `uv` descarga Python de internet | No se encontró Python 3.12 en el sistema | Instale Python 3.12.3 (2.2) y repita 4.1 |
| `doctor` devuelve código 3 y dice que falta SUMO | `SUMO_HOME` no está definida | Defínala (2.5, paso 4) y reabra PowerShell |
| `bd iniciar` dice «no hay conexión con PostgreSQL» | El servicio no está en ejecución | `Start-Service postgresql-x64-17` (como administrador) |
| `bd iniciar` o `bd respaldar` dicen «no se encuentra pg_dump» | Command Line Tools no se instaló | Repita el instalador de PostgreSQL y marque «Command Line Tools», o defina `SEMAFORO_PG_BIN` con la carpeta `bin` |
| `bd verificar --red` dice `no_verificada` | Un usuario común no puede leer `pg_hba.conf` | Repita el comando con `--hba` desde PowerShell como administrador |
| T7 o T8 no dan el resultado esperado | Falta `datos\` o la referencia no coincide (ver T7) | Copie `datos\` (3.A paso 4 o 3.B paso 1) o avise al PO |
| Las pruebas de la base fallan | No se ejecutó `bd iniciar` o la carga | Repita 5.3 y 5.4 |
| Las pruebas de SUMO fallan | SUMO no encontrado o memoria baja | Revise 2.5 y que haya al menos 4 GB de RAM libres al correr las pruebas |

**Regla de seguridad:** si algo pide una contraseña que no reconoce, **deténgase** y consulte al PO. No la escriba en un archivo, en el repositorio ni en un chat.
