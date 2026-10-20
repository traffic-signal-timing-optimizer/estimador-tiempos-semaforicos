# Acta 2026-10-19: DEV00 · F2 (hash y copia inmutable)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha:** 2026-10-19, 21:00 (UTC−5)
- **Autorización:** el Product Owner autorizó F2 («continua con F2») tras aceptar ADR09.
- **Código y pruebas:** commit `b503e86`; esta acta, `3ba664e`. Una revisión posterior corrigió errores de F2 y del andamiaje (ver «Revisión posterior»). Sin publicar a la fecha de esta acta.
- **Siguiente fase:** F3 (inventario de red y semáforos), a la espera de la autorización expresa del Product Owner.

## Qué se implementó

| Módulo | Responsabilidad |
|---|---|
| `trazabilidad/hashing.py` | SHA-256 de archivos, leídos por bloques, y de bytes |
| `trazabilidad/ids.py` | `content_id`: identificador por contenido, definido en ADR09 |
| `trazabilidad/fs.py` | marcar solo lectura una copia y borrarla aunque lo esté |
| `caso/errors.py` | `CasoError` con código estable y campo afectado |
| `caso/sumo_config.py` | lectura segura del `.sumocfg`: referencias a archivos y rutas absolutas |
| `caso/reception_models.py` | manifiesto pydantic (`SnapshotManifest`); sus campos no se pueden reasignar |
| `caso/reception.py` | `snapshot_source`: clasifica, copia con doble verificación y publica |

## Decisiones tomadas en F2

1. **La copia contiene solo los archivos de identidad** (el `.sumocfg` y los archivos de su sección `<input>`). Los demás archivos se registran en el manifiesto con hash y rol, pero no se copian. Es la lectura más literal de ADR09 y garantiza que dos copias con el mismo identificador son idénticas byte a byte. La aclaración se añadió a ADR09.
2. **`defusedxml` entra en F2** y no en F3: hace falta para leer el `.sumocfg`, que es un archivo externo. D6 de la acta de F0 queda corregida.
3. **Nuevo código de error `PATH_NOT_ALLOWED`**, para rutas fuera de la carpeta permitida, enlaces y uniones. No figura en la lista de códigos de la documentación. `INPUT_SCHEMA` y `HASH_MISMATCH` sí figuran.
4. **Reglas de clasificación:**
   - En `<input>` y `<gui_only>`, una opción es un archivo si su nombre termina en `-file` o `-files`. En `<input>` también lo es `load-state`, la única opción de entrada de SUMO 1.27.1 que es un archivo y no termina así (añadida en la revisión posterior). En `<output>`, si termina en `-output`.
   - Los scripts se reconocen por extensión (`.bat`, `.cmd`, `.ps1`, `.sh`).
   - Las salidas de un `.sumocfg` heredado (`tripinfos`, `stats`, `edgeData`) quedan como «sin referenciar», porque el `.sumocfg` de entrada no las declara.
5. **Referencias absolutas o que salen de la carpeta no se siguen.** Se registran como dependencia faltante y, si son absolutas, como hallazgo `ABSOLUTE_PATH`. La recepción continúa con lo que sí existe.
6. **Límites y reintentos provisionales, pendientes del piloto:** 500 entradas, 512 MiB observados, 1 MiB de `.sumocfg`, 3 intentos con 0,5 s de espera. Referencia medida en R0: 21 archivos, 1,29 MB y un `.sumocfg` de 593 bytes.
7. **Pyright ahora usa el entorno `.venv` del proyecto.** Antes resolvía los paquetes con el Python del sistema, lo que ocultaba dependencias que faltaban en el proyecto.

## Evidencia de la puerta de salida (R0, datos reales)

| Comprobación | Resultado |
|---|---|
| `snapshot_id` de R0 | `be52433f098605cebaee9eb04a4db2537f4911e1a88bce72e9ed8596871ccfb6` |
| Primera y segunda recepción | la primera crea la copia; la segunda la reutiliza; mismo identificador y manifiestos idénticos |
| Archivos observados | 21, ninguno ilegible; 21/21 con el hash de la línea base |
| Roles | 1 `entry_config`, 2 `input`, 1 `view`, 2 `output`, 2 `script`, 13 `unreferenced` |
| Identidad | `frutales_solo.sumocfg`, `frutales_solo.rou.xml` y `osm.net.xml.gz` |
| Dependencias faltantes y hallazgos | ninguno |
| Recálculo independiente del identificador con la línea base | coincide |
| Copia | 3 archivos idénticos al original, en solo lectura |
| R0 tras las dos recepciones | hash, fecha y solo lectura de los 21 archivos sin cambios |
| Carpeta original del Product Owner | `vigilar_sumo.ps1`: «Sin cambios» |
| Manifiesto | no contiene rutas absolutas |

### Alias de R0

`datos/originales/sumo/R0-provisional/` es la copia completa de F0 (21 archivos). Su identidad de entrada es el `snapshot_id` anterior, que está en `datos/originales/sumo/be52433f098605cebaee9eb04a4db2537f4911e1a88bce72e9ed8596871ccfb6/`. La carpeta no se renombra (ADR09, punto 6).

## Verificación

- Pruebas: 174 pasan y 1 se salta de forma declarada (no se pueden crear enlaces simbólicos sin privilegios). La prueba equivalente con uniones (`mklink /J`) sí se ejecuta, y la rama de enlaces simbólicos se cubre con entradas simuladas. Al cerrar F2 eran 161; las otras 13 se añadieron en la revisión posterior.
- Las pruebas nuevas fallaron antes de existir el código (6 de 6 archivos sin poder importarse).
- Diez mutaciones del código (identificador sin ordenar, hash omitido, enlaces ignorados, DTD aceptado, entre otras) fueron detectadas por las pruebas.
- La autorrevisión encontró un hueco: un archivo con el nombre de un `snapshot_id` provocaba un error del sistema con la ruta del equipo. Se corrigió con una prueba previa.
- `ruff`, formato y `pyright` estricto sin errores; `pip-audit` sin vulnerabilidades; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- Las referencias dentro de archivos adicionales (por ejemplo, `file=` en un detector) no se siguen: las revisan F3 y F4.
- Una copia es de solo lectura: para borrarla hay que quitar el atributo (existe `remove_tree`).
- Que el informe publicado no contenga rutas absolutas se verifica en F8, que es donde se genera.
- Las opciones de archivo fuera de `<input>` no se siguen, porque ADR09 limita la identidad a esa sección: las tablas de `astar`, `phemlight-path`, el archivo de `fcd-replay` y `configuration-file` (una configuración anidada). Ninguna aparece en la configuración de Frutales (R0).
- Las salidas cuyo nombre no termina en `-output` (`netstate-dump`, `save-state.prefix`, `save-state.files`) se registran como «sin referenciar». Es solo informativo: las salidas nunca forman parte de la identidad.
- Dos recepciones simultáneas del mismo contenido: la segunda falla con un error del sistema y la copia ya publicada no se altera. Repetirla la reutiliza.

## Revisión posterior (2026-10-19)

El Product Owner pidió revisar todo lo hecho y corregir los errores. La revisión usó un clon limpio del repositorio (ruff, formato, pyright y pruebas sin `documentacion/` ni `datos/`), la cobertura de líneas con el módulo `trace`, mutaciones temporales del código, la reejecución de SUMO sobre el fixture, la comparación de ADR01 a ADR08 con la documentación y el inventario de hashes de `documentacion/`.

| # | Hallazgo | Efecto | Corrección | Commit |
|---|---|---|---|---|
| 1 | El patrón `datos/` del `.gitignore` no estaba anclado a la raíz | `src/semaforo/datos` nunca se versionó: un clon no tenía ese paquete | Patrones `/datos/` y `/documentacion/`, `__init__.py` versionado y una comprobación en `scripts/check.ps1` que falla si `.gitignore` oculta código | `02de5bf`, `b3e4786` |
| 2 | `load-state` no se reconocía como entrada | Un estado cargado no cambiaba el `snapshot_id` | Se trata como archivo de `<input>` | `98a8a49` |
| 3 | La carpeta de copias ya existía como archivo | Error crudo `FileExistsError` con la ruta del equipo | `CasoError` con código `INPUT_SCHEMA` | `98a8a49` |
| 4 | Ninguna prueba recorría cuatro invariantes del manifiesto, la opción sin valor, el origen que es una unión, los enlaces y tipos especiales ni el número de reintentos | Esas ramas no estaban verificadas | Pruebas nuevas. Una aserción débil de enlaces se reforzó porque una mutación sobrevivía; las 11 mutaciones aplicadas se detectan | `98a8a49` |
| 5 | Se llamaba «inmutables» a modelos cuyas listas son mutables | Afirmación imprecisa | Redacción corregida: solo impiden reasignar campos | `98a8a49` |
| 6 | El hook de pre-commit usaba el alias obsoleto `ruff` | Se retiraría en una versión futura | `ruff-check` | `b3e4786` |
| 7 | Los scripts de PowerShell no tenían BOM | Los acentos salían deformados en Windows PowerShell 5.1 | BOM UTF-8 | `b3e4786` |
| 8 | `tools/sumo` incluía la carpeta de la simulación y el nombre de usuario de Windows | Datos de un equipo en un repositorio público (ya publicados) | La carpeta se indica con `-Carpeta` o `SUMO_WATCH_DIR` | `f88d085` |

El historial ya publicado conserva las rutas del punto 8. Quitarlas exigiría reescribirlo, y eso lo decide el Product Owner.

Además, 12 archivos tenían finales de línea CRLF en el árbol de trabajo. Se normalizaron a LF; el contenido versionado ya era LF, así que git no registra cambio.

Verificado sin hallazgos:

- ADR01 a ADR08 reproducen la documentación y sus referencias QA07 a QA30, DEV09 y DEV21 existen y significan lo que dicen.
- El inventario de `documentacion/` (44 hashes) coincide con los archivos, y ni los `.md` ni los `.docx` modificados citan las rutas antiguas.
- El fixture reproduce lo documentado en `tests/fixtures/sumo/README.md`: 150 viajes (90, 10 y 50), 150 vehículos insertados, fin en el segundo 916, código 0 en `demo` y código 1 en `missing_edge` y `truncated_net`.
- `uv.lock` está sincronizado con `pyproject.toml`.
- La puerta de salida de F2 sobre R0 da el mismo `snapshot_id`, con 21 de 21 hashes iguales a la línea base.
