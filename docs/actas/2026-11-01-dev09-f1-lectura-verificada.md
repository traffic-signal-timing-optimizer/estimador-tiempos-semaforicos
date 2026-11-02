# Acta 2026-11-01: DEV09 · F1 (lectura verificada de las entradas)

- **Tipo:** fase F1 de DEV09 (HU01, HU02 y HU03). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D4 (entrada del caso), D5 (entrada de datos) y D6 (lectura de `calidad.csv` y `resumen.json`) de F0.
- **Datos:** sintéticos, y el caso-001 real solo para leerlo.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/datos/quality_report.py` (ampliado) | `read_quality_data(carpeta)`: verifica la carpeta del reporte de calidad y devuelve el manifiesto, el resumen y las filas de la planilla, con tipos. Modelos `QualitySummary`, `QualityRow`, `QualityData` y sus partes |
| `src/semaforo/app/report_inputs.py` | `load_case_inputs(ruta)`: el reporte de las reglas y el caso. `load_data_inputs(caso, carpeta)`: el caso y su reporte de calidad, vinculados por la huella |
| `tests/quality_tools.py` | Un caso y un reporte de calidad sintéticos publicados (los de QA06), para las pruebas de las vistas |
| `tests/unit/test_quality_reader.py` y `test_report_inputs.py` | 40 y 18 pruebas |

## Cómo funciona

**Reporte de calidad.** Primero se verifica la carpeta con lo que ya existía (`read_quality_report`: exactamente los archivos del manifiesto, sin enlaces y con su huella). Después, los bytes que se interpretan se leen una sola vez y se comparan con la huella del manifiesto: si un archivo cambió entre la verificación y la lectura, no se usa. Se interpretan con el formato exacto que escribe DEV05 (separador `;`, marca BOM, identificadores entre `="..."`, tres decimales). Cualquier otra cosa se rechaza con la línea que falla. Un cero se lee como `0` y una ventana sin datos como filas sin movimiento ni números: nunca se confunden.

**Caso.** El archivo se lee dos veces (reglas y contenido). Si no describen el mismo caso, el archivo cambió a medias y no se muestra nada. Un caso inválido sí se devuelve, solo con su reporte, para que la vista muestre qué falló.

**Vínculo entre caso y reporte.** Se compara el ID y la huella canónica del caso con las del manifiesto del reporte. Si el caso se editó después de generar el reporte, o es de otro caso, no se muestra nada.

## Verificación

- **Pruebas:** 58 nuevas. Suite completa: **1989 pasan, 1 se salta** (antes 1931 y 1). El salto es una prueba que solo corre fuera de Windows. Formato, lint, tipos y contratos sin observaciones.
- **Mutaciones:** 52 cambios a propósito, de a uno. En la primera pasada **49 se detectaron, 2 sobrevivieron y 2 no se aplicaron** por un error mío al copiar el texto. Los 2 que sobrevivieron eran huecos reales (una fila con menos columnas y una fecha de fin inválida, que no se probaban); se cerraron con 2 pruebas. Los 2 que no se aplicaron se repitieron bien, más uno nuevo: los 52 quedan detectados.
- **Caso real (solo lectura):** el caso-001 se lee entero: 19 de 19 reglas cumplidas, red verificada, 23 movimientos, 5 grupos, 9 slots, origen de campo y representación sin verificar. Está listo para la vista.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Un manifiesto que no lista la planilla pasa la verificación de la carpeta (la carpeta solo tendría el manifiesto) y luego fallaría al leerla | Se rechaza con un mensaje claro y se prueba |
| 2 | El reporte de calidad guarda los errores relativos con tres decimales en la planilla y exactos en el resumen | La vista usará los exactos para las exclusiones y los de la planilla para la tabla, como ya hace la planilla |
| 3 | Con los enlaces simbólicos ya disponibles en este equipo, la prueba de carpeta-enlace se ejecuta de verdad | Pasa |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría.
