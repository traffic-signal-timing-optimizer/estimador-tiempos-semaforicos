# ADR07: Prueba final separada

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
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

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`.

1. **La base también ciega.** Las filas de prueba quedan ocultas al usuario de lectura y al panel hasta que exista el hito de apertura (ADR12, QA35). Los hitos tienen orden obligatorio: protocolo, partición y modelo congelados, y luego la apertura.
2. **Límite conocido.** Quien administra la laptop puede saltarse los permisos, como ya asumía esta decisión. Lo que protege la tesis es que el cambio deja rastro: huellas en git y regeneración de la base.
3. **Varios cruces.** La apertura es por partición, así que abrir la prueba de un caso no abre la de otro.
4. **Estado de las pruebas.** QA14 y QA18 están cumplidas. QA15 está a medias: falta la parte que necesita un modelo entrenado (DEV16). QA35 se comprobó en bases desechables, porque la base real aún no tiene una prueba cerrada.
