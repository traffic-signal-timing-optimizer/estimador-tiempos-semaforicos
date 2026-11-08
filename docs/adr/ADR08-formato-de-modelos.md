# ADR08: Formato de modelos sin deserialización insegura

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
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

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`. Se implementa en DEV17; hoy no hay modelos ni código que cargue `pickle` o `joblib`.

1. **Formato.** La elección entre JSON y UBJ se hace en DEV17, midiendo. Ambos son seguros; ninguno ejecuta código al cargarse.
2. **Versiones.** Las librerías están fijadas en `uv.lock`. La versión de SUMO (1.27.1) la revisa `doctor` y queda en cada manifiesto; la de PostgreSQL queda en cada carga (`control.cargas`).
3. **La base no guarda modelos.** Guarda sus datos, su huella y su ruta. El modelo sigue siendo un archivo con huella (ADR03).
4. **Pruebas pendientes.** QA20 y la parte de modelos de QA29 se cumplen en DEV17.
