# Acta 2026-10-31: DEV05 · F2 (cobertura, faltantes y exclusiones)

- **Tipo:** fase F2 de DEV05 (HU03; P0, tamaño M). Dependencia: F1 de DEV05.
- **Autorización:** el Product Owner pidió ejecutar F2 («ejecuta F2»).
- **Alcance de la fase:** medir la cobertura del tiempo de estudio, listar los faltantes y marcar exclusiones solo con un límite explícito (decisiones D4 y D5 de `2026-10-30-dev05-f0-decisiones.md`). No genera el reporte (F3). Datos sintéticos.

## Qué se construyó

### `src/semaforo/datos/coverage.py`

- **`assess_coverage(prepared, case, window=None, min_coverage=None)`**
  - **Cobertura** = segundos de la ventana de estudio con datos completos ÷ segundos de la ventana.
  - Solo cuentan los periodos completos (todos los movimientos y clases del caso). Los periodos que se pisan cuentan una sola vez (unión de intervalos) y los solapes se informan por pares de periodos.
  - Los periodos se recortan a la ventana. Uno que solo toca el borde de la ventana, o que queda fuera, no cuenta y se lista en `outside_window`.
  - Los **huecos** son los tramos de la ventana sin datos completos.
  - La **cobertura por movimiento** usa la misma regla con la matriz completa de ese movimiento (todas sus clases).
  - La **ventana** es un parámetro. Si no se da, va del inicio del primer periodo al fin del último, y el resultado dice `window_declared = False`. Sin periodos y sin ventana no se puede deducir y se rechaza.
- **`list_missing(prepared)`**: los faltantes por periodo, movimiento y clase, en orden de periodo. Un faltante nunca se cuenta como cero.

### `src/semaforo/datos/quality.py` (se amplía)

- **`find_exclusions(comparison, max_relative_error=None)`**
  - **Sin límite no excluye nada.** La herramienta solo informa.
  - Con límite excluye las comparaciones cuyo error relativo lo **supera** (estricto: un error igual al límite no excluye). Cada exclusión lleva el movimiento, la clase, el valor que la causó, el límite y el motivo escrito.
  - Un error relativo nulo (control cero) no se puede evaluar contra un límite relativo y no excluye; sigue visible en la comparación con su motivo.
  - Solo se evalúan las ventanas comparables.

## Decisión que refina F0

D5 decía que se excluye un periodo si el Product Owner da un umbral «de error o de cobertura». La cobertura es una propiedad de **todo el tiempo de estudio**, no de un periodo suelto, así que el límite mínimo de cobertura se aplica como **veredicto** sobre la ventana y sobre cada movimiento (`meets_minimum`: verdadero, falso o nulo si no hay límite). No excluye periodos. El límite de error sí excluye comparaciones, como decía D5. El mínimo es inclusivo: una cobertura igual al mínimo cumple.

## Verificación

- **Pruebas nuevas:** 34. `tests/unit/test_coverage.py`, 25 casos: cobertura total y parcial, huecos en ambos extremos, periodo incompleto, cobertura por movimiento, solapes contados una vez, periodo contenido dentro de otro, periodos adyacentes, ventana deducida y declarada, recorte en el inicio y en el fin, periodos fuera y en el borde, otra zona horaria, veredicto del mínimo (por ventana y por movimiento), ventana vacía o inversa, límites inválidos y faltantes en orden. `tests/unit/test_quality.py`, 9 casos nuevos de exclusiones.
- **Suite completa:** 1016 pruebas pasan y 4 se saltan (enlaces simbólicos, que este equipo no permite).
- **Calidad:** formato, lint y tipos sin observaciones.
- **Mutaciones:** 26 fallos introducidos a propósito en `coverage.py` y `quality.py`. En la primera pasada sobrevivieron 2, ambos huecos reales de las pruebas: el recorte de un periodo que termina después de la ventana, y el límite mínimo exacto para cada movimiento. Se agregaron esas dos pruebas. Segunda pasada: 26 de 26 detectadas. Antes de correrlas se agregaron también las pruebas del periodo contenido dentro de otro y del periodo que toca el borde de la ventana.

## Pendiente

- **F3:** reporte (planilla de detalle y resumen) en carpeta nueva con manifiesto, y mutaciones del conjunto (D6 y D7).
- **F4:** cierre de DEV05.
- Siguen abiertos para el Product Owner: umbral de error y cobertura mínima (piloto, DEC05), ventana de estudio de Frutales, quién hace el conteo de control y la lista de valores de `quality_state`.
