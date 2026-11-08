# ADR06: Corrección determinista acotada

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
- **Tipo:** P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

Corrección determinista y acotada de duraciones. Se registra el valor antes y después. Si las restricciones restantes no se cumplen, se rechaza. La consulta no hace búsqueda ni simulación como sustitución silenciosa.

## Motivo

Un plan entregado debe ser factible, y cualquier ajuste debe quedar trazado.

## Alternativas descartadas

- Búsqueda o simulación durante la consulta: sustituiría silenciosamente el modelo.

## Impacto

Afecta a `dominio/` (validador y corrector) y a `estimacion/`. La cobertura sobre entradas admisibles debe informarse aunque la corrección falle.

## Prueba de aceptación

QA22 (corrección determinista: misma entrada, misma salida; los aceptados cumplen todas las reglas; los rechazados cuentan en la cobertura).

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`.

1. **Implementada en DEV13** (`dominio/feasibility.py`), con QA22 cumplida (`tests/unit/test_correction.py`, `test_correction_coverage.py`). La decisión no necesita cambios.
2. **El orden de ajuste es un dato del caso.** Cuando un plan se pasa del ciclo máximo, se le quita tiempo a los tramos en el orden que declara el caso, y se da en el orden inverso (`dominio/adjust_order.py`). Si el caso no declara orden, se usa la secuencia. Esto precisa el «orden canónico» del documento 01 y sirve para cualquier cruce.
