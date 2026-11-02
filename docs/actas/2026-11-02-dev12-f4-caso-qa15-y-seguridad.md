# Acta 2026-11-02: DEV12 · F4 (caso de prueba de QA15 y seguridad de DEV11 y DEV12)

- **Tipo:** fase F4 de DEV12 (HU07). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D12 y D14 de F0 de DEV12, y D14 de F0 de DEV11 (las pruebas de seguridad de los escenarios quedaron para esta fase).
- **Datos:** sintéticos. Las etiquetas del caso de prueba son valores inventados para la prueba, no resultados de ninguna búsqueda en SUMO.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/aprendizaje/split_access.py` (ampliado) | `rows_digest`: huella SHA-256 de las filas que recibió un ajuste, para dejar anotado qué consumió |
| `tests/unit/test_qa15_preparation.py` | 15 pruebas del caso de QA15 |
| `tests/security/test_dev11_dev12.py` | 64 pruebas de seguridad de DEV11 y DEV12 |

## El caso de prueba de QA15

QA15 pide: «etiquetas con un valor atípico solo en la prueba; entrenar y comparar con la prueba alterada sin tocar desarrollo; modelo, transformaciones y selección iguales; acceso a la prueba bloqueado; hashes del paquete». DEV12 entrega la parte que le toca:

- Una partición publicada y leída de nuevo (como la usaría el entrenamiento), con una etiqueta sintética por escenario y un valor atípico (1 000 000) en el primer escenario de la prueba.
- Las filas que reciben el ajuste (`fit`), la selección (`select`) y el refit (`refit`) son **las mismas y su huella es la misma** si ese valor se cambia por 1 000 000, −1, 0, 1e300, infinito o NaN. Se comprueba además con 8 semillas distintas de la partición.
- La huella de las filas de entrenamiento **sí** cambia si se altera una etiqueta de entrenamiento (la huella no es constante), y la de la evaluación final **sí** ve el valor atípico.
- Pedir ese escenario para ajustar se bloquea, nombrándolo (««…» (test)»); la vista de desarrollo ni siquiera lo conoce.

**Lo que queda para DEV16 (cierre de QA15):** entrenar el modelo y comparar el paquete (modelo, transformaciones, selección y sus huellas) con la prueba alterada. DEV12 deja listo con qué comparar: `rows_for`, `rows_digest` y la vista de desarrollo. Esto es el cambio de matriz del plan (QA15 parcial en DEV12, cierre en DEV16).

## Seguridad de los escenarios y las particiones

Entradas no confiables, como pide la regla del proyecto:

| Qué se prueba | Resultado |
|---|---|
| Especificación anidada 100 000 niveles, de más de 4 MiB, vacía, con claves repetidas, `NaN` o `Infinity`, que no es UTF-8, que es una carpeta o un enlace | Error con código y motivo; no se publica nada; el programa no se cae |
| Nombre de familia con `../`, `/`, `\`, espacios, `ñ`, carácter nulo | Rechazado con SPEC-S02; no se escribe nada |
| Identificador del caso con `../`, `/`, `\` o que empieza por punto | PATH_NOT_ALLOWED; no se crea ni la carpeta de trabajo |
| Cantidades enormes (10^9, 10^30 perturbaciones o semillas), 3000 familias, 100 000 clases en una composición | Rechazadas antes de generar; en menos de 5 s las primeras y menos de 20 s las otras; hasta 100 problemas listados |
| Flujos negativos, 1e308 o infinito; un flujo subnormal (válido) | Los primeros se rechazan; el subnormal no tumba nada |
| Política vacía, rota, `NaN`, anidada 100 000 niveles, o con nombre de política con `../`, `/` o `ñ` | INPUT_SCHEMA; no se publica nada |
| Carpeta de conjunto que es un archivo, una carpeta vacía, el espacio de trabajo o un enlace | INPUT_SCHEMA o PATH_NOT_ALLOWED |
| Manifiesto con rutas `../`, absoluta, `C:/`, `a/../../b`, vacía o `a//b` | Rechazado; no se crea ningún archivo fuera |
| Huella de contenido falsificada; conjunto alterado antes de partirlo | HASH_MISMATCH; no se crea la partición |
| Validar la partición de un conjunto con el de otro | Error con todos los problemas |
| Lo que se escribe | Todo queda dentro de `derivados/escenarios/<caso>/<carpeta>`; las herramientas no tocan el conjunto que leen |
| Línea de comandos | Con una especificación hostil sale 2, la salida estándar es solo JSON, y no se ve ninguna traza sin `--debug` |

## Verificación

- **Pruebas:** 79 nuevas. Suite completa: **3008 pasan, 1 se salta** (una prueba que solo corre fuera de Windows). Formato, lint, tipos, contratos y reglas de capas sin observaciones.
- **Mutaciones:** 6 cambios a propósito en `rows_digest` (valor, orden, separador, salto de línea, escenario, huella). **5 se detectaron y 1 era equivalente**: escribir el valor sin `repr` da el mismo texto para números, así que no se puede distinguir (las filas son números).

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Una primera prueba de «3000 familias» usaba 20 000 y la rechazaba por tamaño del archivo (más de 4 MiB), no por la regla de escenarios | Se ajustó a 3000 familias, que caben en el archivo y prueban la regla de los 2000 escenarios |
| 2 | Una prueba pedía rechazar un flujo de 1e-320, que es un número válido (muy pequeño) | Se sacó de la lista de rechazos y se agregó una prueba de que un flujo subnormal no tumba la generación |
| 3 | Un identificador de prueba con 100 000 corchetes rompía la creación de variables de entorno de pytest | Se le puso un nombre corto (`anidado`), como en DEV09 |
| 4 | `rows_digest` escribía mal el separador por la herramienta de edición (un salto de línea dentro de una cadena) | Se reescribió con la herramienta de edición de archivos, que conserva las barras invertidas, y se comprobó con Ruff y tipos |
| 5 | Ninguna dependencia nueva; `schemas/` sin cambios | — |

## Límites

- Todo el bloqueo es lógico (ADR07 lo asume): quien tenga los archivos ve la prueba. Lo que se bloquea son las vías de código que ajustan, seleccionan y evalúan.
- La seguridad se probó con datos sintéticos; no hay todavía datos de campo en ningún conjunto.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
