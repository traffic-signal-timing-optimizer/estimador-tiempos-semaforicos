# ADR05: XGBoost como candidato y mediana como predictor sencillo

- **Estado:** Propuesta
- **Tipo:** V/P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

XGBoost es el candidato, con un regresor por salida de duración variable y reconstrucción del ciclo y los verdes. El predictor sencillo es la mediana de cada salida, calculada solo con datos de entrenamiento. Ambos pasan las mismas reglas de factibilidad. El candidato final se decide con datos de desarrollo, no por preferencia tecnológica.

## Motivo

Comparar un modelo frente a una referencia simple bajo condiciones idénticas.

## Alternativas descartadas

- Elegir XGBoost por preferencia tecnológica: prohibido por la documentación.

## Impacto

Afecta a `aprendizaje/` y `estimacion/`. Sustituir el predictor no toca restricciones ni evaluación, porque ambos cumplen la misma interfaz.

## Prueba de aceptación

QA19 (medianas esperadas; registro completo; no obliga a que gane XGBoost) y QA20 (paquete con orden o reglas alteradas se bloquea).
