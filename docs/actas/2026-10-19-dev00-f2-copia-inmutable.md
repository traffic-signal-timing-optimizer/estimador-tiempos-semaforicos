# Acta 2026-10-19: DEV00 · F2 (hash y copia inmutable)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha:** 2026-10-19, 21:00 (UTC−5)
- **Autorización:** el Product Owner autorizó F2 («continua con F2») tras aceptar ADR09.
- **Código y pruebas:** commit de F2 en `main`, sin publicar a la fecha de esta acta.
- **Siguiente fase:** F3 (inventario de red y semáforos), a la espera de la autorización expresa del Product Owner.

## Qué se implementó

| Módulo | Responsabilidad |
|---|---|
| `trazabilidad/hashing.py` | SHA-256 de archivos, leídos por bloques, y de bytes |
| `trazabilidad/ids.py` | `content_id`: identificador por contenido, definido en ADR09 |
| `trazabilidad/fs.py` | marcar solo lectura una copia y borrarla aunque lo esté |
| `caso/errors.py` | `CasoError` con código estable y campo afectado |
| `caso/sumo_config.py` | lectura segura del `.sumocfg`: referencias a archivos y rutas absolutas |
| `caso/reception_models.py` | manifiesto pydantic inmutable (`SnapshotManifest`) |
| `caso/reception.py` | `snapshot_source`: clasifica, copia con doble verificación y publica |

## Decisiones tomadas en F2

1. **La copia contiene solo los archivos de identidad** (el `.sumocfg` y los archivos de su sección `<input>`). Los demás archivos se registran en el manifiesto con hash y rol, pero no se copian. Es la lectura más literal de ADR09 y garantiza que dos copias con el mismo identificador son idénticas byte a byte. La aclaración se añadió a ADR09.
2. **`defusedxml` entra en F2** y no en F3: hace falta para leer el `.sumocfg`, que es un archivo externo. D6 de la acta de F0 queda corregida.
3. **Nuevo código de error `PATH_NOT_ALLOWED`**, para rutas fuera de la carpeta permitida, enlaces y uniones. No figura en la lista de códigos de la documentación. `INPUT_SCHEMA` y `HASH_MISMATCH` sí figuran.
4. **Reglas de clasificación:**
   - En `<input>` y `<gui_only>`, una opción es un archivo si su nombre termina en `-file` o `-files`. En `<output>`, si termina en `-output`.
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

- Pruebas: 161 pasan y 1 se salta de forma declarada (no se pueden crear enlaces simbólicos sin privilegios). La prueba equivalente con uniones (`mklink /J`) sí se ejecuta.
- Las pruebas nuevas fallaron antes de existir el código (6 de 6 archivos sin poder importarse).
- Diez mutaciones del código (identificador sin ordenar, hash omitido, enlaces ignorados, DTD aceptado, entre otras) fueron detectadas por las pruebas.
- La autorrevisión encontró un hueco: un archivo con el nombre de un `snapshot_id` provocaba un error del sistema con la ruta del equipo. Se corrigió con una prueba previa.
- `ruff`, formato y `pyright` estricto sin errores; `pip-audit` sin vulnerabilidades; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- Las referencias dentro de archivos adicionales (por ejemplo, `file=` en un detector) no se siguen: las revisan F3 y F4.
- Una copia es de solo lectura: para borrarla hay que quitar el atributo (existe `remove_tree`).
- Que el informe publicado no contenga rutas absolutas se verifica en F8, que es donde se genera.
