# ADR08: Formato de modelos sin deserialización insegura

- **Estado:** Propuesta
- **Tipo:** P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

Modelos XGBoost en formato nativo JSON o UBJ, con metadatos JSON. El predictor mediano también en JSON. No se deserializan pickle ni joblib de origen no confiable. Las versiones exactas se fijan tras una prueba de instalación. No se usa «latest» ni se promete compatibilidad con cualquier versión de SUMO.

## Motivo

Cargar un pickle de origen desconocido puede ejecutar código arbitrario.

## Alternativas descartadas

- Pickle o joblib sin verificación: riesgo de ejecución de código.

## Impacto

Afecta a `aprendizaje/` (empaquetado) y `estimacion/` (carga). El cargador comprueba versión, transformaciones, esquema y reglas antes de inferir.

## Prueba de aceptación

QA20 (bundle con orden, reglas o hash alterados, y pickle externo, se bloquean sin deserialización) y QA29 (hash incompatible bloquea).
