# Acta 2026-11-01: DEV10 · F4 (registro de evidencia)

Written for: el Product Owner y el equipo, para revisar cómo queda archivada la evidencia de las pruebas y qué dice la primera ejecución.

- **Tipo:** fase F4 de DEV10 (HU01–HU04 y HU14). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D3 (registro de ejecución), D4 (dónde se guarda) y D5 (severidades) de F0.
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `scripts/evidencia.py` | Corre toda la suite y escribe el registro. `--sensibilidad` incluye el ensayo de F3; `--allow-dirty` permite probar con cambios sin guardar. Devuelve 1 si hay fallos críticos |
| `tests/evidence_lib.py` | La lógica: lee el resultado de pytest (`--junitxml`, con `defusedxml`), lo cruza con el catálogo y arma el registro; quita las rutas de la máquina; calcula la huella de los datos de prueba |
| `tests/unit/test_evidence.py` | 21 pruebas de esa lógica con resultados de pytest fabricados |
| `docs/evidencia/<fecha>_<commit>/` | `informe.md` (para leer) y `registro.json` (para máquinas). **Sin rutas de la máquina**; se versiona |
| `datos/reportes/evidencia/<fecha>_<commit>/` | `pytest.log`, `junit.xml` y `sensibilidad.json`. No se versiona |

## Qué conserva cada ejecución (lo que pide la documentación)

| La documentación pide | Dónde queda |
|---|---|
| Comando | `python -m pytest -q tests` (sin la ruta del intérprete) |
| Fecha | Hora UTC de la ejecución |
| Entorno | Python, sistema, versión de SUMO, memoria disponible, versiones de `pydantic`, `defusedxml`, `pytest`, `hypothesis` y del proyecto |
| Commit | Hash completo y si había cambios sin guardar (el script se niega a correr si los hay) |
| Fixture | Cantidad de archivos de `tests/fixtures` y su identificador por contenido (cambia si cambia cualquier archivo) |
| Resultado | Por QA: pruebas clave, cuántas pasan, fallan y se saltan, y su estado (`cumplido`, `cumplido con salvedad`, `no cumplido`); totales de la suite |
| Log | `pytest.log` completo y `junit.xml` en `datos/reportes/` |
| Fallos por severidad y vinculados a tareas | **Crítico:** falla una prueba clave de un QA (bloquea la puerta de F1). **Mayor:** falla otra prueba, o se salta una sin declarar. Cada crítico lleva la tarea de origen (DEV02, DEV04…) |
| Saltos | Todos los de la suite, con su motivo; si el motivo no está en la lista de declarados, es un hallazgo mayor |

El informe lleva una nota en su encabezado: **no completa las tablas de resultados del Sprint 1**; eso lo hace el Product Owner a partir de este registro (D10).

## Primera ejecución real

Commit `42a81e4a`, con el ensayo de sensibilidad incluido. Ver `docs/evidencia/20261102T000842Z_42a81e4a/informe.md`.

| Dato | Resultado |
|---|---|
| Puerta de F1 | **Sin fallos críticos** (0 críticos, 0 mayores) |
| Suite | 1920 pasan, 0 fallan, 0 con error, 12 se saltan |
| Estado de los casos | QA01 a QA09: **cumplido**. QA10: **cumplido con salvedad** |
| Salvedad de QA10 | 128 pruebas clave, 117 pasan, 11 se saltan: todas son de enlaces simbólicos, que este equipo no puede crear sin privilegios (D8) |
| Otro salto (fuera de los QA) | 1: una prueba que solo aplica fuera de Windows |
| Ensayo de sensibilidad | 32 cambios a propósito: 32 detectados, 0 sobrevivieron |
| Rutas de la máquina en `docs/evidencia/` | 0 |

## Verificación

**Pruebas.** 22 nuevas (21 del registro y 1 del catálogo). Suite completa: **1920 pasan, 12 saltadas**. Formato, lint, tipos y contratos sin observaciones.

**Mutaciones.** 19 cambios a propósito sobre el registro y el catálogo. **16 detectados en la primera pasada; 3 sobrevivieron y eran huecos reales** (un error fuera de las pruebas clave no se contaba como fallo mayor; el nombre de la línea de la puerta; un archivo sin pruebas se tomaba por prueba clave). Se cerraron con pruebas y **los 19 quedan detectados**.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | **Mi primera versión solo declaraba los saltos de las pruebas clave** y dejaba fuera 9 de los 12 de la suite | El registro lista ahora todos los saltos de la suite con su motivo, y uno sin declarar es un hallazgo mayor |
| 2 | **QA10 parecía tener solo 3 saltos**, porque las pruebas de enlaces de otros módulos no eran clave del caso. Eso daba una imagen demasiado optimista de la parte de enlaces | Se agregaron al catálogo las 8 pruebas de enlaces de otros módulos: QA10 muestra ahora 11 saltos |
| 3 | La primera versión de las pruebas del registro tardaba 191 s porque releía todos los archivos de prueba una y otra vez | Se guarda en memoria lo ya leído: 1 s |
| 4 | `git_state` (commit y cambios sin guardar) se prueba solo por su forma, no con un repositorio de prueba | Aceptado: es una consulta directa a `git` |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
