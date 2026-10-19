# ADR06: Corrección determinista acotada

- **Estado:** Propuesta
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
