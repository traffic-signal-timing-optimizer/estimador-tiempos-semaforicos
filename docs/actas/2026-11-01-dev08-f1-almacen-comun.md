# Acta 2026-11-01: DEV08 · F1 (almacén común)

Written for: el Product Owner y el equipo, para revisar cómo se guardan ahora todas las carpetas publicadas y qué quedó probado.

- **Tipo:** fase F1 de DEV08 (HU14). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D2 (candado), D3 (nombre de la temporal), D4 (publicaciones caídas) y D5 (lectura verificada) de F0.
- **Datos:** sintéticos. Se leyó el programa derivado real de `datos/` para comprobar que el lector nuevo lo acepta.

## Qué se construyó

| Archivo | Qué cambia |
|---|---|
| `trazabilidad/fs.py` | `publication` (bloque que publica con candado), `publish_files` lo usa, `recover_publications` aparta caídas, `IncompletePublication` (la marca), `free_name` e `is_plain_folder` compartidos |
| `trazabilidad/verify.py` | `verify_files` y `read_verified`: lectura verificada común |
| `simulacion/compiler.py` | `read_program` |
| `datos/quality_report.py` | `QualityManifest` y `read_quality_report` |
| `caso/reception.py` | La copia de originales usa `publication`; si otra recepción la está copiando a la vez, da `RUN_EXISTS`; si otra ya la publicó, se reutiliza y se verifica |
| `trazabilidad/interrupted.py` | Usa las constantes y ayudantes compartidos de `fs.py` |
| `trazabilidad/store.py` | `scan_files` pasa a ser público (lo usa `verify.py`) |

## Cómo funciona ahora una publicación

1. Se apartan las publicaciones caídas de esa carpeta (a `.incompletas/`, con `INCOMPLETA.json`; no se borran).
2. Se toma el candado del sistema `.lock-<destino>`. Si otra publicación del mismo destino está en curso, se rechaza.
3. Si el destino ya existe, se rechaza antes de escribir nada.
4. Se escribe en `.tmp-<destino>-<aleatorio>`, se deja de solo lectura y se publica con un renombrado. Si en ese instante el destino apareció, se rechaza y no se sobrescribe.
5. Si algo falla al escribir, la temporal se borra (su contenido se puede volver a generar) y el candado se suelta.

Las corridas (`ejecuciones/`) siguen con su propio mecanismo de DEV07; una temporal con `manifest.json` nunca la aparta esta función.

## Verificación

**Pruebas.** 36 nuevas. Suite completa: **1777 pasan, 11 saltadas**. Formato, lint, tipos y contratos sin observaciones.

| Grupo | Qué cubren |
|---|---|
| Publicación (19) | Sin temporales ni candados sobrantes, nombre de la temporal, publicación en curso, destino existente o aparecido a mitad, error al escribir, caídas apartadas (con destino, sin destino, recientes y viejas, de corridas, repetidas, que no se pueden mover, uniones), y un publicador terminado a la fuerza de verdad |
| Lectura verificada (15) | Programa y reporte intactos; archivo cambiado, sobrante o faltante; manifiesto reescrito, roto, de otro modelo o demasiado grande; carpeta o manifiesto inexistentes; ruta que sale de la carpeta; carpeta que es una unión |
| Copia de originales (2) | Copia en curso por otra recepción; copia publicada mientras tanto por otra |

**Mutaciones.** 34 cambios a propósito. **30 detectados en la primera pasada; 4 sobrevivieron.** Tres eran huecos reales (temporal con destino vacío, destino existente antes de escribir, manifiesto válido pero demasiado grande) y se cerraron con pruebas. Queda 1 justificada:

| Sobrevive | Por qué se acepta |
|---|---|
| Comprobar que el manifiesto existe antes de abrirlo | Equivalente: si falta, abrirlo da el mismo error de entrada |

**Con datos reales:** el programa derivado de `datos/derivados/programas/caso-001/20261031T041338Z_63437585` se lee verificado sin cambios.

## Hallazgos de la inspección

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | **En Windows, publicar sobre una carpeta que apareció a mitad daba «Acceso denegado»** en vez de «ya existe» | Se traduce a «ya existe»; prueba nueva |
| 2 | La copia de originales no tenía candado: dos recepciones simultáneas de la misma simulación podían chocar | Ahora la segunda espera a que la primera termine (da `RUN_EXISTS` si sigue en curso) o reutiliza la copia ya publicada, verificándola |
| 3 | Las constantes de `.incompletas` y el ayudante de nombres libres estaban repetidos | Quedan en `fs.py` y los usa también la recuperación de corridas |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
