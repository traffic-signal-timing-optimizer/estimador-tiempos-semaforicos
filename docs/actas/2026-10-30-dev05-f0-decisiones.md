# Acta 2026-10-30: DEV05 · F0 (decisiones del control de calidad de aforos)

- **Tipo:** fase F0 de DEV05 (HU03; P0, tamaño M). Dependencia: DEV04, cerrada en local (commit `abb9825`).
- **Autorización:** el Product Owner aprobó el plan por fases de DEV05 y pidió ejecutar F0 («ok ejecuta f0»).
- **Alcance de F0:** solo decisiones por escrito. No hay código ni archivos de datos. Los datos son sintéticos.

## Qué pide la documentación

- `02_Requisitos_y_plan.md`, HU03: «Cero distinto de faltante; control manual o sintético identificado; exclusiones justificadas; error relativo nulo si control cero». Verificación: QA05 y QA06.
- `01_Diseno_tecnico.md`, «Aforos y calidad»: el reporte de calidad conserva el error absoluto frente a un control manual, la cobertura temporal y los faltantes por movimiento y clase. Si el control es cero, el error relativo es nulo con su motivo. Los umbrales de campo quedan en el protocolo y requieren piloto.
- `03_Pruebas_y_operacion.md`, QA06: control 100/0 y observado 90/5 con faltantes conocidos. Resultado esperado: error absoluto 10/5; error relativo 0.1/nulo; cobertura exacta.
- `03_Pruebas_y_operacion.md`, I1: error de conteo por movimiento y clase, cobertura temporal y procedencia; tolerancias del piloto; cero y faltante separados.
- DEC05 (P1): calidad y cobertura de aforos y observaciones independientes; el investigador define el piloto y bloquea la validación local.

## Decisiones

### D1. Cómo es el archivo de control

El control usa **el mismo formato y el mismo lector** que el conteo principal (`read_counts` de DEV04). Se distingue por `source_id`, que debe ser distinto del conteo principal y nombrar la fuente (por ejemplo, conteo manual o revisión independiente). Así se cumple «control identificado» sin formato nuevo.

Un control también debe tener el mismo `case_id` y el mismo `origin` que el caso; el lector de DEV04 ya lo exige.

### D2. Cómo se emparejan las observaciones

Se emparejan por **ventana temporal exacta** (mismo `start` y mismo `end`), por movimiento y por clase. No se empareja por `observation_id`, porque el control puede tener su propio identificador.

- Una ventana que existe solo en uno de los dos archivos queda **sin pareja** y se informa como tal; no se descarta en silencio ni se compara con otra ventana.
- Una ventana con pareja en ambos archivos, pero con un periodo incompleto en uno de ellos, se informa como **no comparable**, con el motivo.

### D3. Definición de error

Para cada ventana, movimiento y clase, con `observado` el conteo principal y `control` el conteo de control:

- **Error absoluto** = `observado − control`, con signo. Se informa también su valor absoluto.
- **Error relativo** = `|observado − control| / control`.
- **Si el control es cero:** el error relativo es nulo y el motivo queda escrito («control cero»). Si el observado también es cero, el error absoluto es 0 y el relativo sigue nulo con el mismo motivo.

Esto cumple QA06: con control 100 autos y observado 90, el error absoluto es 10 y el relativo 0.1. Con control 0 buses y observado 5, el error absoluto es 5 y el relativo es nulo.

### D4. Definición de cobertura temporal

**Cobertura = segundos de la ventana de estudio que tienen datos completos ÷ segundos totales de la ventana de estudio.**

- Un periodo cuenta como cubierto solo si está completo (todos los movimientos y clases del caso).
- Dos periodos que se pisan no cuentan dos veces: se calcula la unión de sus intervalos.
- La **ventana de estudio** es un parámetro explícito de la corrida. Si no se da, se toma desde el inicio del primer periodo hasta el fin del último, y el reporte indica que la ventana fue deducida, no declarada.
- La cobertura se informa en total y por movimiento.

### D5. Faltantes y exclusiones

- **Faltantes:** se listan por periodo, movimiento y clase, igual que en DEV04. Un faltante nunca se cuenta como cero.
- **Exclusiones:** en esta fase la herramienta **no excluye nada por sí sola**. Solo marca como excluido un periodo si el Product Owner entrega un umbral explícito de error o de cobertura. Sin umbral, todo se informa y nada se descarta.
- **Motivo obligatorio:** toda exclusión lleva el motivo y el valor que lo causó.

Esto respeta «exclusiones justificadas» y que los umbrales dependen del piloto (DEC05). No invento un umbral.

### D6. Formato del reporte

- **Planilla de detalle** (`calidad.csv`): una fila por ventana, movimiento y clase, con: `observation_id`, `control_source_id`, `start`, `end`, `movement_id`, `vehicle_class`, `observado`, `control`, `error_absoluto`, `error_relativo`, `motivo_error_relativo`, `estado` (comparable, sin pareja, no comparable, excluido) y `motivo_estado`.
- **Resumen** (`resumen.json`): cobertura total y por movimiento, ventana de estudio y si fue declarada o deducida, número de pares comparados, ventanas sin pareja, faltantes y exclusiones con su motivo.
- **Formato del CSV:** el mismo que los reportes de recepción: UTF-8 con BOM, separador de punto y coma y fin de línea de Windows. Así se abre directamente en Excel, como pide la revisión manual del PO.
- **Ubicación:** `datos/derivados/calidad/<identificador-del-caso>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/`, con un `manifiesto.json` que registra las huellas de los archivos de entrada (conteo principal y control) y del reporte. Igual que el programa derivado de DEV03.

### D7. Redondeo y precisión

Los cálculos se hacen con los valores exactos. El redondeo se aplica solo al mostrar el reporte, a tres decimales, y el valor exacto queda en el archivo JSON. Esto evita que un cambio de redondeo cambie una conclusión.

## Qué queda para el Product Owner (no bloquea F1)

1. **Umbrales de error y cobertura** que sirven para excluir un periodo. Vienen del piloto (DEC05). Hoy la herramienta solo informa.
2. **Ventana de estudio de Frutales**: si la fijo con el investigador o la deduzco de los datos.
3. **Fuente del control de Frutales**: quién hará el conteo de control y cómo se identifica en `source_id`.
4. **Valores de `quality_state`** (pendiente desde DEV04): hoy solo `observed`.

## Fases siguientes

| Fase | Qué se hace | Criterio de cierre |
|---|---|---|
| F1 | Comparación con el control (D2, D3): pares, errores absolutos y relativos, nulos con motivo | QA06 pasa exactamente (10/5, 0.1/nulo) |
| F2 | Cobertura, faltantes y exclusiones (D4, D5) | Cobertura exacta en un caso con faltantes conocidos; ninguna exclusión sin motivo |
| F3 | Reporte en carpeta nueva con manifiesto (D6); mutaciones | Archivos publicados con huellas correctas; mutaciones detectadas |
| F4 | Cierre de DEV05 | Acta y tabla de cumplimiento de HU03 |

## Estado

- Sin código, sin archivos de datos y sin commits en esta fase. Este acta es el único cambio.
