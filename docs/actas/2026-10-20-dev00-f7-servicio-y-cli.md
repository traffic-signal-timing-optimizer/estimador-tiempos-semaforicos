# Acta 2026-10-20: DEV00 · F7 (servicio de recepción y CLI)

- **Tipo:** registro de fase del plan de DEV00 (HU04, HU14)
- **Fecha:** 2026-10-20
- **Autorización:** el Product Owner autorizó F7 y aprobó dos ampliaciones para F7 y F8, derivadas de las limitaciones de F5 (ver abajo).
- **Código y pruebas:** commit `42162a2`.
- **Siguiente fase:** F8 (informe público, listas QA23 y QA24, tabla de movimientos por carril y comparación entre recepciones), completada: ver `docs/actas/2026-10-20-dev00-f8-informes-y-revision.md`.

## Ampliaciones aprobadas

| Ampliación | Fase | Motivo |
|---|---|---|
| Guardar en el registro de la recepción la huella SHA-256 del manifiesto de la corrida base | F7 (hecho) | Autenticidad (ADR03): quien pueda escribir en la carpeta de la corrida podría rehacerla junto con su manifiesto. Con la huella fuera de ella, el cambio se nota. |
| Publicar esa huella en el informe de `docs/recepcion/` | F8 (hecho, `cd58da2`) | Al quedar en el historial de git, alterar la corrida sin que se note exigiría reescribir el historial publicado |
| Listar las ejecuciones incompletas (carpetas `.tmp-`) en el registro | F7 (hecho) | No se borran solas y pueden ser la única pista de un fallo; el Product Owner decide qué hacer con ellas |

## Uso

```powershell
python -m semaforo case receive --source <carpeta de la simulación> --config <archivo .sumocfg> `
    --case-id <id> [--workspace datos] [--mode base|smoke] [--sumo-bin <ejecutable de SUMO>]
```

Las opciones siguen los nombres de la documentación (`--workspace` y `--sumo-bin` del comando `doctor`); el nombre del comando lo fijó la decisión D5. Si no se indica `--sumo-bin`, SUMO se busca con `SUMO_HOME`.

## Qué hace una recepción

1. Copia inmutable de las entradas (F2) en `<workspace>/originales/sumo/<snapshot_id>/`. Si ya existe con el mismo contenido, la reutiliza.
2. Auditoría de rutas, demanda y comportamiento (F4) e inventario de la red (F3) sobre esa copia.
3. Antes de ejecutar SUMO comprueba que la recepción no exista: nunca se sobrescribe y no se gasta una corrida.
4. Corrida base de SUMO (F6) en `<workspace>/ejecuciones/<run_id>/`, comparada con los vehículos declarados en la auditoría.
5. Publica de una vez, en solo lectura, `<workspace>/derivados/recepcion/<reception_id>/` con `snapshot_manifest.json`, `inventory.json`, `audit.json` y `reception.json`. El `reception_id` es `<AAAAMMDDTHHMMSSZ>_<8 primeros caracteres del snapshot_id>` (ADR09).

`reception.json` contiene:

- la copia (`snapshot_id`, si se reutilizó), la versión de SUMO y la huella de cada artefacto;
- la corrida base (`run_id`, estado, huella de su manifiesto, código y error, resumen);
- el número de hallazgos del inventario, la auditoría y la corrida;
- las ejecuciones incompletas;
- un **estado propuesto**: `acceptable` (sin hallazgos), `with_findings` (con observaciones) o `failed` (la corrida base falló). Es una propuesta que valida el Product Owner (QA23 y QA24).

Las rutas del registro son relativas al espacio de trabajo y solo se guarda el nombre de la carpeta de origen.

## Salida y códigos de salida

La salida estándar lleva siempre un JSON: el registro, o un error con `status`, `code`, `field` y `message`. Quien la consuma debe leer el estado y no solo el código de salida (diseño técnico). La salida de error lleva un resumen para la persona.

| Código | Cuándo | Códigos de error |
|---|---|---|
| 0 | Recepción completada, aunque tenga hallazgos | — |
| 2 | Entrada no válida o error de sintaxis | `INPUT_SCHEMA` |
| 3 | Dependencia faltante | `DEPENDENCY_MISSING` |
| 4 | Fallo de proceso: la corrida base falló o se pasó del tiempo (el registro se publica igual) | `SIM_FAILED`, `SIM_TIMEOUT`, `OUTPUT_INVALID` |
| 5 | Integridad o ruta no permitida | `HASH_MISMATCH`, `PATH_NOT_ALLOWED`, `RUN_EXISTS` |
| 1 | Error interno no previsto, sin traza (se ve con `--debug`) | `INTERNAL` |

El código 6 (violación del protocolo) no aplica a la recepción.

## Evidencia de la puerta de salida

La CLI se ejecutó con la simulación de R0 en un espacio de trabajo temporal; la recepción R0 en `datos/` corresponde a F9. Según ADR09, el detalle de los resultados no se publica aquí.

| Comprobación | Resultado |
|---|---|
| Código de salida | 0, con el estado propuesto `with_findings` |
| Copia | mismo `snapshot_id` que en F2 |
| Hallazgos | inventario, auditoría y corrida, coherentes con lo que vieron F3, F4 y F6 |
| Archivos publicados | los cuatro JSON, sin rutas del equipo |
| Carpeta original del Product Owner | `vigilar_sumo.ps1`: «Sin cambios» |

## Verificación

- Pruebas: 408 pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios). F7 añade 34, de ellas 6 que ejecutan la CLI de punta a punta en un proceso aparte: éxito, corrida fallida, ruta absoluta, origen inexistente, SUMO ausente y error de sintaxis.
- Las pruebas fallaron antes del código (módulos inexistentes). Al repasarlas se añadieron cuatro casos que faltaban: una recepción `acceptable`, una con hallazgos del inventario, la ausencia de una corrida inútil cuando la recepción ya existe y el error interno de la CLI.
- Diecisiete mutaciones del servicio, la CLI y la publicación de archivos fueron detectadas.
- `ruff`, formato y `pyright` estricto sin errores; el validador de contratos sigue en 43 comprobaciones.

## Limitaciones conocidas

- No hay registro técnico en formato JSONL (documento 03): los errores internos solo se ven con `--debug`. Se incorporará cuando haya más comandos.
- Dos recepciones en el mismo segundo de la misma copia chocan (`RUN_EXISTS`); la segunda se repite un segundo después.
- Si la recepción se interrumpe después de la corrida base y antes de publicar el registro, la corrida queda publicada sin recepción que la cite. Se detecta porque ningún `reception.json` contiene su `run_id`.
