# ADR 0001: Estructura del paquete y herramientas de desarrollo

- **Estado:** aceptada
- **Fecha:** 2026-10-19
- **Responsable:** Product Owner (validación funcional)

## Contexto

El repositorio no tenía código. La documentación técnica define la estructura de módulos, el uso de contratos JSON y la lista de herramientas (T17), pero el prompt de desarrollo pedía que estas decisiones se aprobaran explícitamente.

## Decisión

1. Diseño de paquetes en `src/semaforo/` con los módulos de `documentacion/documentos/01_Diseno_tecnico.md`: `app`, `cli`, `dominio`, `datos`, `caso`, `simulacion`, `referencias`, `aprendizaje`, `estimacion`, `evaluacion`, `trazabilidad`.
2. Los contratos JSON se mueven de `documentacion/contratos/` a `schemas/` en la raíz del repositorio, para que git los versione. El validador de referencia y el inventario se actualizaron a la nueva ruta.
3. Herramientas: uv (entorno y lockfile), ruff (lint y formato), pyright (tipos, modo estricto), pytest y hypothesis, pre-commit, pip-audit. Python 3.12.
4. Ruta de SUMO: `C:\Program Files (x86)\Eclipse\Sumo` (SUMO 1.27.1). Se lee desde la configuración; no se fija en el código.
5. Regla verificada por prueba automatizada: solo `semaforo.simulacion` importa `traci`, `sumolib` o `subprocess`.

## Alternativas descartadas

- Dejar los contratos dentro de `documentacion/`: impide versionarlos con git.
- Usar pip + venv sin lockfile: no fija versiones de forma reproducible.

## Impacto

Contratos, validador de referencia (`documentacion/herramientas/validar_paquete.py`) e inventario SHA-256 de `documentacion/`. Las versiones en `uv.lock` fijan las herramientas.

## Pendiente

- Las vistas HTML (ADR02 de la documentación) siguen sin aceptar. Se registrarán en un ADR propio.
- Los `.docx` de `documentacion/` pueden mencionar la ruta antigua `contratos/`; no se editan automáticamente.
