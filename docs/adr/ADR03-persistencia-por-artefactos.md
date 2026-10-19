# ADR03: Persistencia por artefactos inmutables

- **Estado:** Propuesta
- **Tipo:** V/P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

Persistencia por artefactos inmutables en CSV, JSON y XML, con manifiestos y SHA-256. Cada ejecución escribe un directorio nuevo y publica resultados mediante renombrado atómico. La integridad se verifica contra un manifiesto aprobado.

## Motivo

Reproducibilidad y trazabilidad sin base de datos. Un hash guardado junto a un archivo modificable no acredita por sí solo autenticidad.

## Alternativas descartadas

- Base de datos relacional: no se prevén transacciones de base de datos en el alcance.

## Impacto

Afecta a `trazabilidad/` y a todos los módulos que escriben resultados. Una corrección produce un artefacto nuevo; los originales no se sobrescriben.

## Prueba de aceptación

QA09 (dos ejecuciones con mismos insumos producen resultados equivalentes) y QA29 (artefacto modificado bloquea la exportación; sin sobrescritura).
