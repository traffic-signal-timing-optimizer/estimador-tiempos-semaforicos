# ADR07: Prueba final separada

- **Estado:** Propuesta
- **Tipo:** V/P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

## Decisión

La prueba final se separa por grupos de origen, con protocolo congelado y semillas independientes de la búsqueda. Los identificadores de prueba no autorizan el acceso a sus etiquetas para entrenar. El aislamiento lógico y las comprobaciones de conjuntos son obligatorios, aunque el investigador tenga acceso local a los archivos.

## Motivo

Evitar la fuga de información entre entrenamiento y prueba, que invalidaría cualquier métrica.

## Alternativas descartadas

- Confiar en el acceso restringido por convención: no es verificable; se exige aislamiento lógico.

## Impacto

Afecta a `aprendizaje/` (particiones) y `evaluacion/`. Un cambio aprendido de los resultados de prueba implica un experimento nuevo.

## Prueba de aceptación

QA14 (una partición por grupo; fuga bloqueada), QA15 (un test alterado no cambia el modelo ni la selección) y QA18 (semillas solapadas se bloquean).
