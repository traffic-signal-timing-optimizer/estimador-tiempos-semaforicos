# Acta 2026-10-31: DEV05 · F1 (comparación con el conteo de control)

- **Tipo:** fase F1 de DEV05 (HU03; P0, tamaño M). Dependencia: DEV04 y F0 de DEV05.
- **Autorización:** el Product Owner pidió ejecutar F1 («ejecuta F1»).
- **Alcance de la fase:** emparejar el conteo principal con el conteo de control y calcular los errores (decisiones D1 a D3 de `2026-10-30-dev05-f0-decisiones.md`). No mide cobertura ni decide exclusiones (F2) y no genera el reporte (F3). Datos sintéticos.

## Qué se construyó

`src/semaforo/datos/quality.py`, con `compare_files(principal, control, caso)` y `compare_with_control(...)`. Reutiliza el lector de DEV04: los dos archivos pasan por las mismas validaciones y, si uno falla, se rechaza con el detalle por fila.

- **Independencia del control (D1):** el `source_id` del control no puede coincidir con el del conteo principal; si coincide, `QualityError` con campo `source_id`.
- **Emparejamiento (D2):** por ventana temporal exacta (mismo inicio y fin). Dos instantes iguales en zonas horarias distintas son la misma ventana. Resultados por ventana:
  - `comparable`: las dos matrices están completas.
  - `only_observed` y `only_control`: la ventana existe en un solo archivo; se informa, no se descarta.
  - `not_comparable`: a alguno de los dos le faltan filas; el motivo dice cuáles y a cuál de los dos. Un faltante nunca se compara como cero.
- **Errores (D3):** por movimiento y clase, `absoluto = observado menos control` (con signo; también se expone su valor absoluto) y `relativo = |observado menos control| / control`. Con control cero el relativo es nulo y el motivo dice «control cero»; con los dos en cero, el absoluto es 0 y el relativo sigue nulo.
- **Ambigüedad:** si un archivo tiene dos periodos con la misma ventana (con distinto `observation_id`), no hay forma de emparejarlo y se rechaza con `QualityError`, indicando de cuál archivo.
- **Trazabilidad:** el resultado lleva la huella SHA-256 de cada archivo, el identificador de cada lado y la fuente del control.
- Las ventanas salen ordenadas por tiempo.

## Verificación

- **QA06 (control 100/0 y observado 90/5):** error absoluto de −10 (valor absoluto 10) y 5; error relativo 0.1 y nulo con motivo «control cero». Coincide con lo que espera la documentación.
- **Pruebas nuevas:** `tests/unit/test_quality.py`, 17 casos: QA06; ceros en ambos lados; signo del error; orden de movimientos y clases; identificadores y fuente; ventanas sin pareja en cualquiera de los dos lados; ventanas con otro inicio o fin; misma ventana en otra zona horaria; periodos incompletos en el principal, en el control y en ambos; faltante nunca como cero; orden por tiempo; fuente repetida; ventana ambigua; archivo inválido; huellas.
- **Suite completa:** 982 pruebas pasan y 4 se saltan (enlaces simbólicos, que este equipo no permite).
- **Calidad:** formato, lint y tipos sin observaciones.
- **Mutaciones:** 19 fallos introducidos a propósito en `quality.py`; los 19 se detectaron en la primera pasada. Antes de correrlas se corrigió una prueba que comparaba el motivo con la constante del código y no con el texto «control cero».

## Pendiente

- **F2:** cobertura temporal, lista de faltantes y exclusiones con motivo (D4 y D5).
- **F3:** reporte (planilla y resumen) en carpeta nueva con manifiesto (D6), y mutaciones del conjunto.
- **F4:** cierre.
- Siguen abiertos para el Product Owner: umbrales de exclusión (piloto, DEC05), ventana de estudio de Frutales, quién hace el conteo de control y la lista de valores de `quality_state`.
