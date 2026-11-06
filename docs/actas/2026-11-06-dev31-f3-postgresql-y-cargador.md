Escrito para: el Product Owner (revisión de F3) y el equipo técnico (F4 a F8 de DEV31).

# DEV31 F3: PostgreSQL preparado y cargador verificado

- **Fecha:** 2026-11-06
- **Tarea:** DEV31 (historia propuesta HU15). Orden de fases: sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`.
- **Estado:** hecho y **pendiente de tu revisión**.
  - Se creó la base `semaforo` en tu PostgreSQL con su esquema completo. Está **vacía**: cargar los datos existentes es F4.
  - No toca `datos/` (solo se leyó, para un ensayo en una base temporal), `documentacion/` ni las bases `tickers_report_db` y `trading_predict`.
- **Modelo:** Opus.
- **Complejidad:** media-alta. **Riesgo:** medio. **Esfuerzo:** una sesión.

## Qué quedó hecho

### En tu PostgreSQL (con tu autorización y la contraseña del administrador solo para ese comando)

| Qué | Cómo quedó |
|---|---|
| Carpeta de los datos | `D:\pgdata\semaforo`, registrada como espacio de tablas `semaforo`. La cuenta del servicio («Servicio de red») tiene permiso sobre ella |
| Usuarios del proyecto | `semaforo_admin` (dueño; puede crear bases temporales para las pruebas), `semaforo_carga` (solo agrega filas y puede usar tablas temporales) y `semaforo_lectura` (solo lee, con la prueba final oculta). Ninguno es administrador del servicio ni puede saltarse el cegado |
| Contraseñas | Nuevas y aleatorias, solo en tu `%APPDATA%\postgresql\pgpass.conf` (que solo tu usuario de Windows puede abrir). Al servicio se le mandaron ya cifradas (SCRAM), así que no pueden quedar en sus registros. Los datos de conexión están en `%APPDATA%\postgresql\.pg_service.conf`. Nada de esto está en el repositorio |
| Base `semaforo` | UTF-8, en `D:`, con `semaforo_admin` como dueño. Solo entran los tres usuarios del proyecto |
| Esquema | 56 tablas, 871 columnas, 221 relaciones (112 del diseño más las 109 que unen cada fila con su carga y su archivo), 12 vistas, 22 tablas con cegado (44 reglas por filas), 112 disparadores de «solo agregar», 5 disparadores de reglas y 4 índices de hitos. Versión `sql-903e4137442d4fe7` |
| Lo que no se tocó | La configuración del servicio (`listen_addresses` sigue en `*`, como decidiste) y las otras bases |

### En el repositorio

| Archivo | Qué es |
|---|---|
| `src/semaforo/bd/` (nuevo) | El paquete de la base: diseño (`diseno.py`), generador del SQL (`ddl.py`), el SQL (`sql/01_tablas.sql` y `03_seguridad.sql` generados, `02_reglas.sql` escrito a mano), conexión por servicio, instalación, bases temporales, huella de contenido, respaldo y el cargador (`carga/`) |
| `src/semaforo/simulacion/herramientas.py` (nuevo) | Lanza las herramientas cortas del sistema que necesita la base (ver hallazgo 0) |
| `src/semaforo/app/bd_commands.py` y `cli/main.py` | Los comandos `bd iniciar`, `bd cargar`, `bd verificar`, `bd hito` y `bd respaldar` |
| `scripts/bd_esquema.py` | Ahora genera también el SQL desde `docs/bd/esquema.toml` y con `--comprobar` falla si el SQL o el diccionario no están al día |
| `scripts/check.ps1` | La puerta comprueba el esquema y **necesita PostgreSQL**: sin él, las pruebas de la base fallan (no se saltan) |
| `pyproject.toml` y `uv.lock` | `psycopg[binary]==3.3.8`, de PyPI oficial, con sus huellas. `pip-audit`: sin vulnerabilidades conocidas |
| `docs/adr/ADR03-persistencia-por-artefactos.md` | Enmienda: las huellas de lo publicado se guardan en git (aprobado por ti) |

## Cómo funciona el cargador (`bd cargar`)

Recorre `datos/` en este orden: caso, protocolos, conjuntos de escenarios con su partición, escenarios escritos a mano, corridas con sus métricas, búsquedas con su etiqueta, comparadores e hitos. Cada carpeta es una **unidad** que entra entera o no entra. Para cada unidad:

- **Verificación:** se lee con su lector oficial (las huellas de su manifiesto). Cada archivo que da filas se vuelve a comprobar con los mismos bytes que se cargan.
- **Ya cargada:** si todo está igual en la base, se salta. Cargar dos veces no duplica nada.
- **Conflicto:** si una clave ya está con otro contenido, o un archivo cambió después de cargarse, no se escribe nada y queda en `control.conflictos` (una sola vez, aunque cargues muchas veces).
- **Pendiente:** si le falta algo que se publica aparte (su escenario, sus métricas), espera y el informe dice qué falta.
- **No cargable:** si la carpeta no tiene un formato cargable (por ejemplo, las 3 corridas de DEV00 sin escenario), su archivo queda registrado con su motivo.
- **Las métricas se copian** de `metricas.json` (F2); el cargador no calcula ninguna (B10).
- **Tres autorizaciones explícitas** (quedan anotadas en la carga):
  - `--preliminar` carga escenarios sin partición congelada. Un preliminar nunca podrá pasar a prueba: la base lo rechaza.
  - `--sueltas` carga como diagnóstico las corridas que ninguna búsqueda publicada usa. Sin esto, una corrida de una búsqueda en curso no queda marcada para siempre como diagnóstico.
  - `--sin-metricas` carga corridas exitosas cuyas métricas no se pueden publicar. Sus métricas quedan vacías y ya no se podrán agregar.
- **Al terminar:** la carga se cierra con sus conteos y la **huella de contenido** de toda la base. Solo puede haber una carga a la vez.

## Reglas que aplica la propia base

| Regla | Qué pasa si se intenta romper |
|---|---|
| Solo agregar | Modificar, borrar o vaciar cualquier tabla se rechaza, **incluso para el dueño**. Las dos excepciones del diseño (cerrar una carga, decidir un conflicto) se permiten una sola vez |
| Cegado de la prueba | El usuario de lectura no ve los escenarios asignados a prueba ni nada de lo que cuelga de ellos (corridas, vehículos, colas, búsquedas, etiquetas…). Al registrar la apertura aparecen, sin cambiar ningún dato. Las vistas aplican el cegado a quien consulta |
| Orden de los hitos | Solo se congela un protocolo publicado como congelado. El modelo no se congela sin su partición y un protocolo congelados antes, y la prueba no se abre sin su modelo, su protocolo y su partición congelados antes. Hay un solo hito de cada tipo por objeto |
| Preliminares y familias | Un escenario preliminar no pasa a prueba. Una familia va completa a una sola partición y asignación |
| Corridas | La etapa «final» solo en escenarios de prueba, y cada semilla en la etapa que le asigna el protocolo |
| Permisos | El usuario de lectura no puede escribir ni crear tablas temporales. El de carga no puede modificar filas |

## Cómo se verificó

### Ensayo con tus datos reales, en bases temporales

`datos/` solo se leyó; las bases temporales se borraron al terminar.

| Ensayo | Resultado |
|---|---|
| `datos/` tal cual | Entraron el caso, los 3 protocolos, el escenario ESC-SINT-001 (como preliminar) y los comparadores. Las 3 corridas de DEV00 quedaron «no cargables» con su motivo. Las 130 restantes **esperan sus métricas publicadas**, porque las 133 corridas son anteriores a F2. La segunda carga no escribió nada y dio la misma huella |
| Copia de trabajo en `D:\tmp\f3ensayo` con las 102 corridas del piloto | Les calculé las métricas con el código oficial, solo en la copia. Entraron las 102 corridas, con 181 560 vehículos, 1 499 400 filas de cola segundo a segundo, 408 resultados por acceso y 2 040 por movimiento. También entraron la búsqueda del piloto (21 candidatos, 102 resultados por semilla y su etiqueta «sin referencia») y los comparadores, en 196 s. La segunda carga tardó 5 s y no escribió nada |
| `bd verificar --regenerar` | La base regenerada en otra base temporal dio **la misma huella de contenido**: `3f813e2a…` (QA36). Se revisaron 211 archivos raíz |
| `bd respaldar` y restaurar | Respaldo de 11 MB en 3 s. Restaurado en otra base, **la misma huella** (QA36) |
| Un `case.json` cambiado después de cargar | `bd verificar` lo detectó (código 5). `bd cargar` rechazó el caso y registró 2 conflictos (`hash_mismatch` y `key_conflict`) |
| Un hito inválido | Congelar el protocolo del piloto, que es borrador, se rechazó **antes de publicar nada**: no quedó ningún archivo de hito |

### Puerta de calidad y pruebas nuevas

- **Puerta:** `ruff` y `pyright` limpios; esquema al día; **5 299 pruebas pasan** (1 omitida, solo para sistemas que no son Windows; 64 más que en F2); contratos **43/43**; ningún archivo de código oculto a git.
- **Pruebas nuevas, con bases temporales y corridas reales de SUMO sobre la red de demostración:**
  - 33 sin base de datos: SQL generado, archivos de conexión, lectura del registro de SUMO, de la cohorte y de `tripinfo`, entorno y planes.
  - 10 de reglas de la base: cegado, orden de hitos, solo agregar, permisos, preliminares, familias, corridas finales e inyección de texto.
  - 10 de la carga completa: carga, recarga sin duplicar, regeneración, pendientes, métricas faltantes, archivo cambiado, carpeta ilegible, hito, acta sin confirmar, y respaldo y restauración.
  - 7 de seguridad (QA34).
  - 3 de la línea de comandos.
- **Ensayo de daño a propósito:** **23 roturas, 23 detectadas**. Cubrió el SQL de la base (borrar evidencia, cerrar una carga dos veces, cegado que no se abre o que se abre antes, abrir sin modelo congelado, preliminar a prueba, familia repartida, corrida final en entrenamiento, vista sin cegado, política abierta y permiso de modificar) y el cargador (conflictos ignorados, duplicados, atajo sin huella, el −1 de SUMO, errores del registro, etapas, autorización del preliminar, huella de contenido, archivos cambiados, respaldo alterado y borrado de bases ajenas). Para cerrar tres huecos agregué tres comprobaciones a las pruebas antes de correrlo. El guion está en la carpeta de trabajo de la sesión (`f3_danio.py`) y deja cada archivo como estaba (se comprueba por su huella).
- **Bases temporales:** todas se borraron. En el servicio quedan solo `semaforo` (vacía) y tus otras dos bases.

## Lo que se encontró

0. **La regla de estructura «solo `simulacion` lanza procesos» se cumple.** La base necesita tres herramientas cortas del sistema (`icacls` para los permisos, `pg_dump`/`pg_restore` y `git` para el acta). Las lanza un ayudante nuevo dentro de `simulacion` (`herramientas.py`), con lista fija de argumentos, sin consola y con tiempo máximo. Lo detectó la puerta en su primera vuelta.
1. **Un error del cargador que el piloto no mostraba.** Si una etiqueta tiene plan ganador, ese plan llega dos veces en la misma unidad, desde la traza y desde la etiqueta, y el cargador lo tomaba como dos versiones distintas. Lo encontraron las pruebas nuevas y ya está corregido.
2. **Las 133 corridas existentes no tienen métricas publicadas** (son de antes de F2). Para cargarlas en F4 hay que publicárselas:
   - Las **102 del piloto** se miden con el protocolo del piloto; ya lo ensayé.
   - De las **28 sueltas** (diagnóstico), las que probé no se pueden medir con ese protocolo, porque 43 carriles de su zona no están en su FCD (el mismo límite de F2). Hay que decidir con qué protocolo medirlas, o cargarlas sin métricas (`--sin-metricas`). Pregunta 2.
3. **Tres accesos de la zona no tienen vehículos de la cohorte** (`1185174556`, `1436359637#0` y `563085958`). Su cola está en `cola_segundo`, pero no en `resultados_acceso`, porque esa tabla exige los datos de la cohorte. Es un hueco del diseño para F7: dejar esas columnas vacías en esos accesos.
4. **Tiempo de carga:** unos 2 s por corrida la primera vez, y unos segundos en total las siguientes (se salta lo ya cargado). Para las 4 692 corridas de DEV16 serían unas 2,6 horas la primera vez. Se mide y, si hace falta, se acelera en F4.
5. **Los hitos los escribe el cargador desde su archivo, no el administrador a mano.**
   - `bd hito` comprueba el hito contra la base, lo publica como carpeta de solo lectura con la huella de su acta (que tiene que estar confirmada en git) y lo carga.
   - Así la base se puede regenerar con sus hitos (B1).
   - Es un ajuste al texto de los usuarios del acta F1 («admin registra los hitos»). Se regulariza en F7.
6. **Tus otras dos bases** siguen como estaban. Como cualquier base nueva de PostgreSQL, permiten entrar a cualquier usuario del servicio (también a los del proyecto), pero los del proyecto no tienen permiso sobre sus tablas, salvo que esas bases las hayan abierto a todos. Cerrarlas es decisión de ese proyecto; no lo hice.
7. **`version_esquema`:** el diccionario dice «última migración aplicada», pero no hay migraciones. Si el diseño cambia, se crea una base nueva y se vuelve a cargar (B1). La versión es la huella de los tres archivos SQL. El texto se corrige en F7.
8. **El servicio sigue aceptando conexiones de la red** (`listen_addresses = '*'`): riesgo que asumiste (2026-11-06).
9. **Lo que no entra en F3 y va después:**
   - La carga real de lo existente, la conciliación (QA33) y la prueba del cegado con datos reales (QA35) son F4.
   - El archivo `docs/bd/huellas.json` se escribe en F4, después de la primera carga real: hoy la base está vacía.
   - `bd exportar` (CSV por tabla y paquete para el jurado) va con el panel (F5) o en F6.

## Lo que pido al PO

1. ¿Apruebas F3?
2. Para F4, las 28 corridas sueltas (diagnóstico): ¿las mido con algún protocolo (¿cuál?) o las cargo sin métricas (`--sin-metricas`)? Las 102 del piloto se miden con su propio protocolo.
3. ¿Cargo ESC-SINT-001 como preliminar (`--preliminar`)? No tiene partición congelada y, una vez preliminar, nunca podrá ser de prueba.
4. ¿Ejecuto F4 (carga de lo existente, conciliación y cegado con datos reales)? Recomiendo **Sonnet**, como dice el plan.
