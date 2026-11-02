# Acta 2026-11-01: planes de DEV09, DEV11 y DEV12 (sin código)

- **Estado:** propuesta. Espera el OK del Product Owner antes de empezar cualquier fase.
- **Fuentes:** `documentacion/documentos/02_Requisitos_y_plan.md` (secciones DEV09, DEV11, DEV12 y HU06, HU07), `documentacion/matrices/tareas.csv`, `pruebas.csv` (QA13, QA14, QA15, QA25, QA30), `documentacion/documentos/01_Diseno_tecnico.md` (particiones y comandos) y el código de `src/semaforo` al 2026-11-01.
- **Datos:** sintéticos.

## Resumen

| Tarea | Prioridad | Tamaño | Dependencias | Complejidad | Esfuerzo | Riesgo | Modelo | Fases |
|---|---|---|---|---|---|---|---|---|
| DEV09 Presentar caso y datos | P1 | M | DEV02, DEV05, DEV08 (cerradas) | media | mediano | bajo | Sonnet | F0 a F5 |
| DEV11 Generar escenarios controlados | P0 | M | DEV02, DEV07, DEV08 (cerradas) | media | mediano | bajo | Sonnet | F0 a F5 |
| DEV12 Separar grupos y bloquear fuga | P0 | M | DEV11 (pendiente) | media | mediano | medio | Sonnet | F0 a F5 |

**Orden propuesto:** DEV09, DEV11, DEV12. DEV12 no puede empezar antes que DEV11.

---

## DEV09 · Presentar caso y datos

### Qué pide la documentación
- Un informe HTML estático para el caso y otro para los datos. Todo texto escapado, con tablas de estado, unidades, cero frente a faltante, y la causa de cada problema. Se abre en el navegador, sin servidor.
- HU01: el origen (sintético o real) debe verse en el informe.
- Verificación: QA30 (cinco vistas con errores y texto HTML inyectado; los campos y unidades se revisan a mano).

### Qué ya existe y se reutiliza
- Lectura del caso con verificación: `caso/case_validation.py` (`validate_case`, `read_case`) y su reporte `CaseReport`.
- Reporte de calidad con huellas: `datos/quality_report.py` (`read_quality_report`).
- Motivos de exclusión y cero frente a faltante: `datos/quality.py` y `datos/importer.py`.
- Hoy no hay ningún código HTML en `src/`. Todo se escribe desde cero.

### Fases

| Fase | Qué se hace | Complejidad |
|---|---|---|
| F0 | Decisiones (ver abajo). Sin código | baja |
| F1 | Leer caso y reporte de calidad solo si sus huellas coinciden. Si no coinciden, no se muestra nada y aparece un aviso | baja-media |
| F2 | Vista del caso: estado, reglas (aprobadas, avisos, fallos), límites, origen y red | media |
| F3 | Vista de datos: aforos por periodo, unidades, cero frente a faltante, causa de exclusión y cobertura | media |
| F4 | Pruebas automáticas: texto inyectado queda escapado, no se ejecuta nada, los estados se ven. La revisión manual la hace el PO con una lista que yo preparo | baja-media |
| F5 | Cierre: acta, inspección contra la documentación y el caso real, bitácora | baja |

### Decisiones propuestas
1. **Solo dos de las cinco vistas de QA30.** Las otras tres (construcción, consulta y resultados) son de DEV21. QA30 queda parcial hasta DEV21.
2. **Sin librería de plantillas.** Agregar una dependencia exige regenerar `uv.lock`, y este equipo no tiene `uv`. Se usa la biblioteca estándar de Python.
3. **Dónde se guardan:** en `datos/reportes/`, en carpetas publicadas con manifiesto, como los demás resultados.

---

## DEV11 · Generar escenarios controlados

### Qué pide la documentación
- Demandas con rangos explícitos, semillas, grupos y origen. Las llegadas por movimiento y clase deben ser idénticas entre comparadores.
- HU06: origen y grupo por escenario; rangos trazables; composición coherente; fronteras fijas; las perturbaciones pertenecen a la familia original.
- Verificación: QA13 (generar dos veces da lo mismo; un rango inválido se rechaza; la familia se conserva).

### Qué ya existe (DEV06)
- `dominio/scenario.py`: modelo de un escenario, con su contrato (`scenario` v1.0) y reglas SCEN-S01 a S03 y SCEN-C01 a C06.
- `simulacion/cohort.py`: genera la cohorte con N exacto, semilla por movimiento y calentamiento fuera de la cohorte.
- `schemas/scenario.schema.json`.
- **Falta:** la especificación con rangos, la generación de un conjunto de escenarios, las familias con perturbaciones y el manifiesto del conjunto.

### Fases

| Fase | Qué se hace | Complejidad |
|---|---|---|
| F0 | Decisiones (ver abajo). Sin código | baja-media |
| F1 | Especificación con rangos por movimiento, composición, ventana, semillas y familia. Un rango inválido se rechaza con su motivo; nada sale del dominio del caso | media-baja |
| F2 | Generación repetible: misma especificación y semilla dan los mismos escenarios y los mismos hashes. Las perturbaciones quedan dentro de la familia. Cada escenario lleva su origen y su grupo | media |
| F3 | Llegadas iguales para todos los comparadores: dos comparadores reciben el mismo archivo de demanda (reutiliza la cohorte de DEV06) | baja-media |
| F4 | Manifiesto del conjunto publicado con la función de DEV08 (`publish_files`). Se agrega la nueva carpeta a la verificación de `runs verify` (`app/integrity.py`) | media |
| F5 | Cierre: acta, inspección, bitácora | baja |

### Decisiones propuestas
1. **Ubicación:** `datos/scenarios.py`, como dice la matriz. Los modelos siguen en `dominio/scenario.py`.
2. **Formato de la especificación:** un archivo JSON validado con el contrato, sin campos desconocidos.
3. **Comando de línea** `scenarios generate` (está en el diseño técnico, no en la matriz). Propuesta: incluirlo en F4. Ver pregunta 4.

### Punto que requiere su OK
- **QA25 no corresponde a esta tarea.** QA25 prueba la cohorte de HU12 y HU13 (terminados, inconclusos y no insertados), y ya se verificó en DEV06 F3. Propuesta: quitarlo de DEV11 y dejar solo QA13. Esto cambia la matriz de tareas.

---

## DEV12 · Separar grupos y bloquear fuga

### Qué pide la documentación
- HU07: un grupo queda en una sola partición; cada escenario se asigna una vez; la prueba queda fuera del ajuste; el manifiesto es inmutable.
- Diseño: agrupar primero por día o familia; reservar la prueba una sola vez; entrenamiento y validación se hacen sobre grupos de desarrollo; prohibido compartir IDs de escenario, grupos o procedencia real.
- Verificación: QA14 (una partición por grupo; fuga y duplicados bloqueados) y QA15 (entrenar con la prueba alterada no cambia nada).

### Qué ya existe
- `schemas/split.schema.json` (contrato de partición).
- `aprendizaje/` solo tiene el archivo de inicio. Todo lo demás se escribe desde cero.

### Fases

| Fase | Qué se hace | Complejidad |
|---|---|---|
| F0 | Decisiones (ver abajo). Sin código | baja-media |
| F1 | Asignación determinista con semilla registrada. Validación de cobertura (cada escenario una vez), disjunción de grupos y de IDs (QA14) | media |
| F2 | Bloqueo: la parte que ajusta solo recibe entrenamiento y validación. Pedir la prueba desde el ajuste es un error | media |
| F3 | Manifiesto de la partición inmutable, publicado con DEV08 y validado con `split.schema.json`. Se agrega la nueva carpeta a `runs verify` | baja-media |
| F4 | Preparar el caso de QA15: un valor atípico que solo aparece en la prueba, y la prueba de que no entra al ajuste. El QA15 completo (entrenar y comparar) se cierra en DEV16 | media-baja |
| F5 | Cierre: acta, inspección, bitácora | baja |

### Decisiones propuestas
1. **Unidad de asignación:** la familia completa del escenario (día o familia, como dice el diseño).
2. **Proporciones y número de grupos:** DEC07 está pendiente. Mientras tanto se usan valores provisionales, declarados en el manifiesto, igual que la tolerancia de la réplica.
3. **Procedencia real compartida:** hoy no hay datos reales, así que la comprobación solo cubre IDs y grupos. Queda anotado como límite.

### Puntos que requieren su OK
- **QA15 no se puede cerrar en DEV12.** Entrenar un modelo es de DEV16. Propuesta: DEV12 entrega el caso de prueba y el bloqueo; QA15 se cierra en DEV16. Esto cambia la matriz.
- **Riesgo medio.** Un error de fuga invalida todos los resultados posteriores sin que nada falle a la vista. Por eso F1 y F2 se verifican con mutaciones, como en DEV10.

---

## Puntos comunes

- **Sin `uv`:** no se pueden agregar dependencias. Todo se hace con la biblioteca estándar y con paquetes ya bloqueados.
- **Verificación al cerrar:** cada tarea termina con inspección contra la documentación y el caso real, y con su entrada en la bitácora de `documentacion/CONTEXTO.md`.
- **Datos:** sintéticos. Ninguna salida se presenta como resultado observado en Lima.

## Preguntas para el Product Owner

1. ¿Aprueba el orden DEV09, DEV11, DEV12?
2. ¿Aprueba quitar QA25 de DEV11, y dejar QA15 parcial en DEV12 con cierre en DEV16?
3. ¿Aprueba QA30 parcial en DEV09 (dos vistas) y completo en DEV21?
4. ¿Incluimos los comandos `scenarios generate` y `splits create / validate` del diseño en DEV11 y DEV12, o los dejamos para después?
5. ¿Aprueba valores provisionales para las proporciones de DEV12 hasta que DEC07 se decida?
6. Para QA30, ¿puede hacer la revisión manual con la lista que yo preparo?
7. ¿Ejecuto F0 a F5 seguidas en cada tarea, como en DEV08 y DEV10, o espero su OK en cada fase?
