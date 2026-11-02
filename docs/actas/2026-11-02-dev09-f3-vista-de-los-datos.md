# Acta 2026-11-02: DEV09 · F3 (vista de los datos)

- **Tipo:** fase F3 de DEV09 (HU02 y HU03). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D5, D7, D8, D9, D10 y D11 de F0.
- **Datos:** sintéticos (los de QA06). El `datos/` real no tiene todavía un reporte de calidad: los aforos reales de Frutales siguen pendientes.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/app/report_data_view.py` | `render_data`: la página de los datos |
| `src/semaforo/app/reports.py` (ampliado) | `publish_data_report`: publica el informe de los datos con su manifiesto |
| `tests/unit/test_report_data_view.py` | 44 pruebas |
| `tests/unit/test_reports.py` (ampliado) | 6 pruebas de la publicación del informe de datos |

## Qué muestra la vista de los datos

| Sección | Contenido |
|---|---|
| Resumen | El caso, su origen en palabras, las huellas del caso y de los dos conteos, los periodos del conteo principal, la **fuente del control**, el límite de error relativo usado (o «sin límite fijado: no se excluyó ningún dato») y cuándo se creó el reporte |
| Cobertura de la ventana de estudio | La ventana (si se declaró o se dedujo de los datos), su duración, los segundos con datos, la cobertura en porcentaje y en fracción, y si cumple el mínimo. Por movimiento: segundos y cobertura. Los huecos, los periodos que se solapan y los que caen fuera de la ventana |
| Ventanas de observación | Cuántas hay de cada tipo: comparables, solo en el conteo principal, solo en el control y no comparables |
| Observados, corregidos y excluidos | La cantidad de cada uno. **Corregidos es siempre 0**, con la explicación de que en esta etapa no se corrige ningún dato |
| Comparación con el conteo de control | Una fila por ventana, movimiento y clase: observado, control y error absoluto en vehículos, error relativo como fracción, estado, motivo y fuente del control |
| Datos que faltan | Cada combinación de movimiento y clase que falta, con la aclaración de que un dato que falta no se trata como cero |
| Exclusiones y su causa | Cada conteo excluido con su error y la causa |

**Cero y faltante.** Un cero se escribe `0`; un dato que no existe se escribe `sin dato` y nunca `0`. Cuando el control es cero, el error relativo no se calcula y la celda dice por qué («no se calcula (control cero)»). Las ventanas sin pareja o con filas que faltan ocupan una fila que dice `sin dato` en los números y da su motivo.

**Horas.** Cada instante se muestra con su hora local y su desfase, por ejemplo `2026-10-18 08:00 (-05:00)`.

**Publicación.** `datos/reportes/informes/datos/<id-del-caso>/<fecha>_<huella>/`, con `index.html` y `manifiesto.json`. El manifiesto guarda las huellas del caso, del conteo principal y del control, y de cada archivo del reporte de calidad del que salieron los números.

## Verificación

- **Pruebas:** 50 nuevas. Suite completa: **2215 pasan, 1 se salta**. Formato, lint, tipos y contratos sin observaciones.
- **Mutaciones:** 73 cambios a propósito, de a uno. **63 se detectaron en la primera pasada y 10 no.** Los 10 eran huecos reales: el redondeo del porcentaje, la alineación a la derecha de los números en tres tablas, tres valores por movimiento que se confundían con los de la ventana (porque en el caso base valían lo mismo), una ventana ausente que contaba uno, un periodo vacío en una exclusión y la hora del pie del informe. Se cerraron con 5 pruebas y los 73 quedan detectados.
- **Texto hostil:** una prueba pone texto con `<script>`, imágenes con `onerror`, entidades y etiquetas de cierre en **todos** los campos libres que la vista muestra (periodos, fuentes, movimientos, clases, estados, motivos, faltantes, exclusiones, solapes y el ID del caso) y comprueba que la página sigue siendo segura y que el texto aparece como texto.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Los títulos de las tablas decían «1 conteos excluidos» | Ahora dicen «Conteos excluidos: 1», que se lee bien con cualquier cantidad |
| 2 | Tres valores por movimiento (segundos, cobertura y mínimo) se confundían con los de toda la ventana en el caso base, porque eran iguales | Una prueba con valores distintos para cada movimiento |
| 3 | El caso base no tenía solapes ni periodos fuera de la ventana | Se prueban por separado, con y sin esos periodos |

## Límite

La vista usa el reporte de calidad de DEV05, que guarda conteos en vehículos por ventana, no vehículos por hora ni la composición por clase (eso lo calcula DEV04 y no se guarda). Por eso la vista muestra conteos, con su unidad, y no repite la normalización.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría.
