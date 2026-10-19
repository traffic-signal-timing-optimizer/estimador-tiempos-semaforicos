# ADR 0001: Estructura del paquete y herramientas de desarrollo

- **Estado:** aceptada, con una adición pendiente de confirmación (ver «Adiciones»)
- **Fecha:** 2026-10-19
- **Responsable:** Product Owner (validación funcional)

## Contexto

El repositorio no tenía código. La documentación técnica define la estructura de módulos, el uso de contratos JSON y la lista de herramientas, pero el prompt de desarrollo pedía que estas decisiones se aprobaran explícitamente. Donde ambos difieren, prevalece `documentacion/`.

## Decisión

1. Diseño de paquetes en `src/semaforo/` con los módulos de `documentacion/documentos/01_Diseno_tecnico.md`: `app`, `cli`, `dominio`, `datos`, `caso`, `simulacion`, `referencias`, `aprendizaje`, `estimacion`, `evaluacion`, `trazabilidad`. Los nombres de paquete se mantienen en español por la documentación; los identificadores internos del código y de las pruebas van en inglés y los docstrings en español.
2. Los contratos JSON se mueven de `documentacion/contratos/` a `schemas/` en la raíz del repositorio, para que git los versione. El validador de referencia, el inventario y los documentos (`LEEME.md`, `01_Diseno_tecnico.md` y su `.docx`) se actualizaron a la nueva ruta.
3. Herramientas: uv (entorno y lockfile), ruff (lint y formato), pyright (tipos, modo estricto), pytest y hypothesis, pre-commit, pip-audit. Python 3.12.
4. Ruta de SUMO: `C:\Program Files (x86)\Eclipse\Sumo` (SUMO 1.27.1). Se lee desde la configuración; no se fija en el código.
5. Regla verificada por prueba automatizada: solo `semaforo.simulacion` importa `traci`, `sumolib` o `subprocess` (el análisis es sintáctico y cubre imports dinámicos con literales).
6. Verificaciones locales en `scripts/check.ps1` (ruff, formato, pyright, pytest y coherencia de la versión de ruff). pre-commit queda solo con los hooks de ruff, que no dependen de `uv` en el PATH.
7. Finales de línea normalizados a LF con `.gitattributes`.
8. Las herramientas de vigilancia de la carpeta de SUMO viven en `tools/sumo/`; su línea base es estado local y no se versiona.

## Adiciones pendientes de confirmación

- `hatchling` como backend de construcción en `pyproject.toml`. No estaba en la lista de herramientas aprobada. Alternativa: `setuptools`. Si no se confirma, se sustituye.

## Alternativas descartadas

- Dejar los contratos dentro de `documentacion/`: impide versionarlos con git.
- Usar pip + venv sin lockfile: no fija versiones de forma reproducible.
- Hooks locales de pre-commit con `uv run`: fallan si `uv` no está en el PATH.

## Impacto

Contratos, validador de referencia (`documentacion/herramientas/validar_paquete.py`) e inventario SHA-256 de `documentacion/`. Las versiones en `uv.lock` fijan las herramientas.

## Pendiente

- Las vistas HTML (ADR02 de la documentación) siguen sin aceptar. Se registrarán en un ADR propio.
- Este ADR usa numeración propia; las decisiones ADR01–ADR08 de la documentación siguen como propuestas hasta DEC09.
