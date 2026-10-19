# Acta 2026-10-19: estructura del paquete y herramientas

- **Tipo:** registro de aprobaciones del Product Owner (no es un ADR de la documentación)
- **Fecha:** 2026-10-19
- **Aprobado por:** Product Owner
- **Relacionado con:** HU01, HU14 · DEV01 (entorno y repositorio)

## Qué se aprobó

1. **Estructura de paquetes** en `src/semaforo/` con los módulos de `documentacion/documentos/01_Diseno_tecnico.md`: `app`, `cli`, `dominio`, `datos`, `caso`, `simulacion`, `referencias`, `aprendizaje`, `estimacion`, `evaluacion`, `trazabilidad`. Nombres en español, como la documentación; identificadores de código y pruebas en inglés; docstrings en español.
2. **Herramientas:** uv (entorno y lockfile), ruff (lint y formato), pyright en modo estricto, pytest, hypothesis, pre-commit, pip-audit y pydantic 2.x (desarrollo). Python 3.12.
3. **Contratos JSON** movidos de `documentacion/contratos/` a `schemas/` en la raíz del repositorio, para que git los versione.
4. **Ejemplos y validador de referencia:** `documentacion/ejemplos/` pasa a `tests/fixtures/`; el validador y sus modelos pasan a `tools/contracts/`. Ese código de referencia se conserva tal cual lo entregó la documentación y ruff lo excluye.
5. **Ruta de SUMO:** `C:\Program Files (x86)\Eclipse\Sumo` (SUMO 1.27.1). Se lee desde configuración, no se fija en el código.
6. **Regla de aislamiento:** solo `semaforo.simulacion` importa `traci`, `sumolib` o `subprocess`.
7. **Herramientas de vigilancia** de la carpeta de SUMO en `tools/sumo/`; su línea base es estado local y no se versiona.
8. **Finales de línea** normalizados a LF con `.gitattributes`.

## Cómo se verifica

| Aprobación | Verificación |
|---|---|
| Regla de aislamiento de SUMO | `tests/unit/test_estructura.py` (análisis sintáctico con `ast`) |
| Contratos en `schemas/` | `tests/unit/test_schemas.py` |
| Fixtures y validador de referencia | `tests/unit/test_fixtures.py` y `tools/contracts/validar_paquete.py` (43 comprobaciones) |
| Dependencias entre módulos (ADR01) | `tests/unit/test_arquitectura.py` |
| Todo lo anterior | `scripts/check.ps1` (ruff, formato, pyright, pytest, validador y versión de ruff) |

## Relación con otros registros

- Es coherente con las propuestas ADR01 a ADR08 de `docs/adr/`, pero no las acepta ni las sustituye.
- Las vistas HTML (ADR02) siguen sin decidirse; la ruta de SUMO se implementará en DEV01 (`doctor`).
