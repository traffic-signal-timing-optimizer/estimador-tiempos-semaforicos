Escrito para: el Product Owner (revisión de C1 de la fase F4c de DEV31) y el equipo técnico.

# DEV31 F4c, etapa C1: controles nuevos, sin cambiar el esquema

- **Fecha:** 2026-11-07
- **Tarea:** DEV31 (historia HU15). Plan de correcciones v3.4: `docs/actas/2026-11-07-dev31-plan-correcciones-auditoria.md`, sección C1.
- **Orden:** «ejecuta todo C1» (PO, 2026-11-07).
- **Modelo:** Sonnet, dos sesiones, como indica el plan.
- **Estado actualizado al 2026-11-07:** C1 cerrada técnicamente. La conciliación y las decisiones D7 se actualizaron después del corte inicial de esta acta; C1.11 recibió dos correcciones posteriores, documentadas en actas propias. C2 sigue sin orden de ejecución.
- **Esquema:** no cambió (`sql-d405569d4d1daf46`, 56 tablas, 871 columnas, 113 relaciones). No hubo migraciones.

## Qué se hizo, en palabras simples

| Tarea | Qué quedó funcionando |
|---|---|
| **C1.1 Catálogo de fuentes** | Un solo lugar (`src/semaforo/bd/carga/fuentes.py`) enumera todo lo publicado en `datos/`: casos, protocolos, escenarios escritos a mano, escenarios generados, conjuntos, corridas, métricas, búsquedas, etiquetas, comparadores, hitos y decisiones. El cargador, la conciliación y las métricas recorren `datos/` con él, así que ven lo mismo. |
| **C1.2 Errores aislados** | Una corrida con manifiesto ilegible, protocolo ausente o carpeta incompleta queda como «no verificada» con su motivo, y el resto sigue. `bd metricas` revisa una carpeta de métricas que ya existe antes de darla por publicada. |
| **C1.3 Cobertura en los dos sentidos** | `bd conciliar` parte de lo publicado, no de la base. Informa faltantes, sobrantes, excluidas con decisión y excluidas pendientes. Una base vacía da «incompleta», nunca «igual». |
| **C1.4 Códigos de salida** | 0 = todo bien; 3 = sin conexión; 4 = errores aislados; 5 = diferencia, incompleto o pendiente; 6 = sin resultado concluyente. Cada código tiene su prueba. |
| **C1.5 Decisiones en archivo** | `bd decidir` escribe `datos/derivados/decisiones/<id>/` con `decision.json` y su manifiesto. Una decisión identifica el archivo por **ruta y huella**. Si el archivo cambia, la decisión vieja no lo cubre y el archivo queda pendiente otra vez. El acta que la respalda tiene que estar confirmada en git. Cargar otra vez no reabre un conflicto ya decidido (N5). |
| **C1.6 Verificación de solo lectura** | `bd verificar` no escribe nada. Toma el candado compartido: si hay una carga en curso, el resultado es «no concluyente». Compara contra la referencia de git y distingue «otra versión del esquema» (no concluyente) de «difiere». |
| **C1.7 Conciliación en una instantánea** | `bd conciliar` lee dentro de una sola transacción de solo lectura, con el mismo candado. Si una carga cambia la base mientras se lee, el resultado es «no concluyente». |
| **C1.8 Fichas y prueba de respaldos** | Cada respaldo nuevo sale con su ficha, tomada de la misma instantánea que el volcado. Cada campo dice su estado: *verificado*, *declarado*, *no comprobado* o *desconocido*. `bd probar-respaldo` restaura el respaldo en una base temporal, **recalcula** la huella sobre lo restaurado y la compara con una referencia guardada antes de restaurar. Un respaldo viejo (sin ficha) se describe solo con lo que se puede leer sin restaurar. Una ficha que ya existe no se reescribe. |
| **C1.9 Estado de la red** | `bd verificar --red` dice en qué direcciones escucha PostgreSQL y qué reglas de acceso admiten equipos fuera de la laptop. Si no puede leer las reglas, lo dice en vez de suponer. |
| **C1.10 Reglas instaladas** | La huella de referencia incluye disparadores (y si están activos), seguridad por filas, políticas, permisos, funciones, vistas e índices. Desactivar un disparador sin tocar datos cambia la huella (N3). |
| **C1.11 `bd reconstruir` seguro** | Crea la candidata con nombre temporal y la valida en pasos (P0 a P7). Solo cambia el nombre si todas las puertas pasan, con la huella aprobada por el PO y con las pruebas declaradas. Si el segundo cambio de nombre falla, el primero se revierte (probado). No toca bases que no son del proyecto. |
| **C1.12 Guiones versionados** | Los ensayos de daño de DEV31 F2 a F4 y de C1 están en `scripts/mutaciones/` con su índice en `LEEME.md`. |

Además:
- `docs/bd/huellas.json` se regeneró con la base real: esquema 1.1.0, con el algoritmo de huella (`contenido-1`) y el de reglas (`reglas-1`).

## Cómo se verificó

**Puerta de calidad completa** (`scripts/check.ps1`, 2026-11-07, código de salida 0):
- ruff (estilo y formato), pyright (tipos): sin observaciones.
- Esquema al día: 56 tablas aprobadas, 0 propuestas.
- Pruebas: **5402 pasaron, 1 omitida** (`tests/unit/test_job.py:24`, que el propio proyecto omite en este caso). Tardó 10 min 32 s.
- Contratos de referencia: 43 de 43.
- Ningún archivo de código ignorado por git; versión de ruff alineada.

**Ensayos de daño** (cada uno rompe a propósito una regla y comprueba que alguna prueba lo nota):

| Ensayo | Resultado final |
|---|---|
| `dev31_esquema.py` | 14 de 14 detectados |
| `dev31_f2.py` | 17 de 17 detectados |
| `dev31_f3.py` | 23 de 23 detectados (3 se actualizaron porque el código cambió en C1; las 3 nuevas se detectan) |
| `dev31_f4.py` | 13 de 13 detectados (2 se actualizaron y se volvieron a correr: 2 de 2) |
| `dev31_c1.py` | 23 de 23 detectados (un daño sobrevivía: se agregó una prueba de corridas «no verificadas» aisladas; otro se reemplazó por un daño equivalente sobre el código actual, y ambos se detectan) |

Pruebas nuevas de C1: unitarias de fuentes, acceso, decisiones, referencia y contexto; de integración de controles, cobertura, respaldos, reconstrucción y fuentes con SUMO (7 pruebas); y de línea de comandos (7 pruebas).

**Conciliación de la base real en el corte inicial de C1** (`bd conciliar --sin-recalcular`, solo lectura):
- 2615 archivos, 130 corridas, 0 diferencias.
- Cobertura: 137 cargadas de 140 publicadas; **3 excluidas pendientes**; 0 faltan; 0 sobran.
- Código de salida 5: la base estaba **incompleta** en ese corte, no igual. Las 3 pendientes eran las corridas de DEV00. El estado posterior se registra abajo.

**Actualización posterior de D7, verificada en la bitácora del proyecto:** se publicaron tres decisiones «riesgo aceptado», una por cada corrida de DEV00, con ruta y huella del archivo. La conciliación posterior informó 143 unidades publicadas: 140 cargadas y 3 con decisión, sin pendientes, código 0. `docs/bd/huellas.json` se confirmó después en el commit `ad04c8c` con la última carga `20261107T230813Z_9cd9f1e2` y 2625 artefactos. Estas cifras son del registro posterior; no sustituyen la medición inicial de 2615 archivos y 130 corridas de esta acta.

## Límites honestos

- La conciliación con recalculo completo (`bd conciliar` sin `--sin-recalcular`) no se corrió sobre la base real en esta etapa: tarda y no era necesaria para cerrar C1, porque las pruebas con SUMO ya la cubren.
- `bd probar-respaldo` está probado con respaldos de prueba; no se corrió sobre un respaldo real de la base `semaforo`.
- `bd reconstruir` está probado con bases temporales; no se ejecutó un cambio real de la base vigente. Eso va en C2, con orden expresa.
- El envío a git (`push`) no se hizo. Solo commit local.

## Decisiones de DEV00 (D7)

Las 3 corridas de DEV00 se publicaron después de confirmar esta acta en git como decisiones verificables «riesgo aceptado». Sus identificadores y la conciliación posterior están en `documentacion/CONTEXTO.md`, sección 10. La decisión no convierte esas corridas en datos válidos para entrenamiento.

## Correcciones posteriores de C1.11

- `docs/actas/2026-11-07-dev31-f4c-aprobacion-tres-huellas.md`: P7 y P9 comparan versión del esquema, huella de contenido y huella de reglas. `bd reconstruir cambiar` exige la aprobación de los tres valores.
- `docs/actas/2026-11-07-dev31-f4c-c1-p9-reversion-excepciones.md`: P9 intenta revertir también cuando `verify()` lanza una excepción después de P8. Si falla la reversión, informa que el estado de las bases debe comprobarse. Dos pruebas nuevas reprodujeron el defecto antes de la corrección y pasaron después. Puerta completa posterior: 5408 pruebas pasaron, 1 omitida y 43/43 contratos.

## Próximo paso

**C2 (Opus)** solo con orden expresa del PO: cambio de esquema y reconstrucción real de la base. El cambio de `listen_addresses` a `localhost` (C0.6) es una acción separada, todavía sin orden; requiere reiniciar PostgreSQL. El push también requiere orden expresa.
