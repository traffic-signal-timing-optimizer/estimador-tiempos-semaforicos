# Acta 2026-11-01: DEV08 · F2 (vínculos de una corrida y revisión de `datos/`)

Written for: el Product Owner y el equipo, para revisar cómo se sigue una corrida hacia atrás y cómo se revisa todo el espacio de trabajo.

- **Tipo:** fase F2 de DEV08 (HU14). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D6 (vínculos) y D7 (revisión de `datos/`) de F0.
- **Datos:** sintéticos; además se revisó el `datos/` real **solo leyendo**.

## Qué se construyó

`app/integrity.py` (en la capa `app` porque usa los lectores de varios módulos):

- **`trace_run(workspace, run_id)`**: la cadena de una corrida, eslabón por eslabón.
- **`verify_workspace(workspace)`**: revisa todas las carpetas publicadas. Solo lee.

Ayudante de pruebas nuevo: `tests/workspace_tools.py` (arma un `datos/` sintético completo).

## La cadena de una corrida

| Eslabón | Cómo se comprueba | Estados posibles |
|---|---|---|
| La corrida | `read_run`: cada archivo frente a su manifiesto | verificada / alterada (la cadena se corta ahí) |
| Su copia de las entradas | `verify_inputs` sobre `inputs/` de la corrida | verificada / alterada |
| La carpeta de entradas publicada | Se busca en `derivados/entradas/<escenario>/` la que tiene un `manifiesto.json` con la misma huella, y se verifica | verificada / alterada / no encontrada |
| El programa derivado | Se busca en `derivados/programas/<caso>/` por la huella de su manifiesto, se lee verificado y se comprueba que es el programa que copiaron las entradas | verificada / alterada / no encontrada |
| El caso | `casos/<caso>/case.json`: se valida y se compara su huella canónica con la registrada | verificada / **cambiada** / no encontrada |
| La copia de los originales (corridas de recepción, DEV00) | Identificador por contenido de las entradas de la corrida = nombre de la copia; se recalcula sobre la copia | verificada / alterada / no encontrada |
| La corrida anterior (reintento) | `read_run`, o la corrida apartada en `.incompletas` | verificada / alterada / **incompleta** / no encontrada |

La cadena queda `complete` solo si todos los eslabones están verificados; si no, `broken`. El caso usa «cambiada» y no «alterada» porque es un archivo editable: puede cambiar de forma legítima, pero entonces ya no es el que usó la corrida.

## La revisión de `datos/`

| Familia | Carpeta | Se comprueba con |
|---|---|---|
| Corridas | `ejecuciones/` | `read_run` |
| Recepciones | `derivados/recepcion/` | `read_reception` (incluye su corrida base) |
| Copias de originales | `originales/sumo/` | identificador por contenido |
| Programas derivados | `derivados/programas/<caso>/` | `read_program` |
| Carpetas de entradas | `derivados/entradas/<escenario>/` | `verify_inputs` |
| Reportes de calidad | `derivados/calidad/<caso>/` | `read_quality_report` |

Cada carpeta queda **íntegra**, **alterada** (con el motivo), **incompleta** (apartada en `.incompletas`), **temporal** (`.tmp-`, en curso o caída sin apartar) o **desconocida** (no sigue un formato conocido). El estado general es `altered` solo si alguna está alterada. Casos, escenarios y demás archivos editables no son carpetas publicadas y no se revisan aquí.

## Verificación

**Pruebas.** 29 nuevas (22 con SUMO real y 7 sin SUMO). Suite completa: **1806 pasan, 11 saltadas**. Formato, lint, tipos y contratos sin observaciones.

- **Cadena:** completa; caso editado (sigue válido) y caso inválido; carpeta de entradas alterada después de la corrida; entradas, programa o caso ausentes; programa alterado; corrida alterada; la carpeta exacta entre varias; una publicación a medias idéntica nunca se toma por la publicada; reintento de fallida y de interrumpida; corrida inexistente o con nombre inseguro; corrida de recepción con su copia de originales verificada, alterada y ausente.
- **Revisión:** espacio completo íntegro; una carpeta alterada en cada una de las cinco familias con SUMO; reporte de calidad; temporales, apartadas y candados; corridas caídas; archivos sueltos y nombres desconocidos; carpeta con forma de corrida sin publicar; copia de originales con otro contenido o vacía; espacio vacío; **revisar no cambia nada** (se comparan nombres y fechas de todos los archivos antes y después).

**Mutaciones.** 28 cambios a propósito. **24 detectados en la primera pasada; 4 sobrevivieron.** Tres eran huecos reales y se cerraron con pruebas:
- la carpeta exacta entre varias;
- una publicación a medias idéntica;
- un caso editado que siguiera siendo válido: la prueba anterior lo volvía inválido y pasaba por otra razón.

Queda 1 justificada:

| Sobrevive | Por qué se acepta |
|---|---|
| Comprobar que el programa encontrado es el que copiaron las entradas | Defensa adicional: si la huella del manifiesto del programa coincide, el programa ya es ese. Solo fallaría con un manifiesto de entradas fabricado a mano, que la huella de la corrida ya impide |

**`datos/` real (solo lectura):**

| Familia | Íntegras | Desconocidas |
|---|---|---|
| Corridas | 3 (DEV00) | — |
| Recepciones | 3 | 2: `f3-pruebas` y `f4-pruebas` (carpetas de pruebas de DEV00 con nombres a mano) |
| Copias de originales | 2 | 1: `R0-provisional` (la copia inicial de DEV00, antes de los identificadores por contenido) |
| Programas | 1 | — |
| Entradas | 1 | — |

Ninguna alterada. Las tres corridas de DEV00 tienen su cadena completa hasta la copia de originales.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | **Una prueba mía pasaba por la razón equivocada** (el caso «editado» quedaba inválido) | Se separó en dos pruebas: caso editado válido y caso inválido |
| 2 | **Tres carpetas viejas de DEV00 no siguen el formato** (`f3-pruebas`, `f4-pruebas`, `R0-provisional`) | Se informan como «desconocidas»; no se tocan. Conviene que el Product Owner decida si se archivan fuera de `datos/` |
| 3 | Los reportes de calidad de DEV05 no tenían una carpeta fija (cada llamada elegía la suya) | Se fija `derivados/calidad/<caso>/` como la carpeta que revisa `verify_workspace`. DEV05 no tiene comando, así que no cambia nada existente |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
