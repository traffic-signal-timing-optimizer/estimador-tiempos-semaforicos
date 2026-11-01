# Acta 2026-10-31: DEV07 · F1 (ejecución desde la carpeta de entradas)

Written for: el Product Owner y el equipo, para revisar qué hace ahora la ejecución y qué queda por hacer.

- **Tipo:** fase F1 de DEV07 (HU04; P0, tamaño M). Dependencias: DEV06 (cerrada) y el corredor de DEV00.
- **Autorización:** el Product Owner aprobó F0 y delegó sus decisiones. Para F1 pidió analizar los recursos del equipo antes de ejecutar; el análisis está en el acta de F0.
- **Decisiones que aplica:** D1 a D3 y D10 de F0. Además D17 y D18, que F0 asignó a esta fase.
- **Datos:** sintéticos. La prueba con el caso real usa la carpeta que publicó DEV06 en F2.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `simulacion/run_inputs.py` | `run_inputs` (ejecuta una carpeta de entradas) y `verify_inputs` (comprobación completa antes de lanzar SUMO) |
| `simulacion/tripinfo.py` | `read_trips`: lectura en flujo de `tripinfo.xml`, con las mismas protecciones que la lectura normal |
| `trazabilidad/fs.py` | `read_at_most`: lectura con tope que no reserva el tope en memoria |
| `simulacion/runner.py` | Se agrega el parámetro `finalize`: un paso previo a publicar que puede agregar salidas nuevas, nunca reemplazar las existentes |
| `simulacion/reconcile.py` | La lectura de viajes pasa a `read_trips` |

Los lectores que antes reservaban el tope (`read_bounded`, `read_text_file`, `read_json`, la lectura de casos, del importador y de la red) pasan a `read_at_most`. Sus mensajes y límites no cambian.

## Qué hace `run_inputs`, en orden

1. **Comprueba la carpeta entera antes de lanzar SUMO (D2):**
   - el manifiesto es válido;
   - la carpeta tiene exactamente los archivos del manifiesto, sin enlaces ni subcarpetas, y cada uno con su huella;
   - la configuración de SUMO es **el** archivo `escenario.sumocfg` de la carpeta, y dice lo mismo que el manifiesto (red, demanda, programa, inicio, fin, paso y semilla).
2. **Ejecuta con el corredor de DEV00**, con el fin, la semilla, el escenario y la versión del caso tomados del manifiesto (D3). El límite de 7200 s de DEV00 no se usa aquí.
3. **Antes de publicar, concilia la cohorte (D10):** vuelve a comprobar la copia de las entradas que usó SUMO y agrega a `outputs/` la tabla `cohorte_conciliada.csv` y el resumen `conciliacion.json`. Si la conciliación falla, la corrida queda `failed` con `OUTPUT_INVALID` y sin métricas. Vehículos sin terminar o que no entraron **no** la hacen fallar: se cuentan.

## Verificación

**Pruebas.** 84 pruebas nuevas (18 + 24 + 27 + 15). La suite completa pasa: 1518 pruebas, 9 saltadas, todas de enlaces simbólicos (este equipo no los permite).

| Grupo | Pruebas | Qué cubren |
|---|---|---|
| Lectura con tope | 18 | Memoria medida con `tracemalloc`; el límite sigue funcionando; ningún código del proyecto pide el tope entero |
| Lectura en flujo de tripinfo | 24 | Estados, orden, comprimido, DTD, bomba de entidades, raíz equivocada, tope descomprimido, memoria |
| Comprobaciones previas | 27 (y 2 saltadas por enlaces) | Archivos de más o de menos, cambios, configuración distinta del manifiesto, enlaces, manifiesto que apunta a otro archivo |
| Con SUMO real | 15 | Corrida completa, fin del manifiesto, tabla igual a la de F3, corrida corta con no terminados, carpeta alterada no se ejecuta, conciliación fallida, paso final que no puede reemplazar salidas |

**Mutaciones.** 45 cambios a propósito sobre el código nuevo (lectura por partes, tripinfo, paso final y comprobaciones previas). **45 de 45 detectadas**, ninguna sobrevivió. Los archivos quedaron restaurados.

**Calidad.** Formato, lint y tipos sin observaciones.

**Caso real** (`ESC-SINT-001`, SUMO 1.27.1):

| Resultado | Cifra |
|---|---|
| Estado | `succeeded`, código 0 |
| Vehículos cargados, insertados y terminados | 1780 de 1780 |
| Choques y teletransportes | 0 y 0 |
| Avisos de SUMO | 4, heredados del programa original (igual que en F2 y F3) |
| Cohorte conciliada | 1338 pedidos = 1338 terminados |
| Tiempo real | 11 a 19 s |
| Memoria máxima de Python en la corrida | 4,6 MB |
| Entradas originales | intactas (huellas iguales antes y después) |

## Hallazgos de la inspección

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | **Defecto de memoria.** La lectura con tope pedía de una vez todo el tope: leer un `tripinfo` de 0,8 MB con el tope de 512 MiB ocupaba 512 MB. En una corrida pasaba varias veces | Lectura por partes en `read_at_most`. Se cambian los 5 lugares que lo usaban. Una prueba revisa el código con el árbol de sintaxis para que la forma antigua no vuelva |
| 2 | **Lectura del `tripinfo`.** El árbol completo ocupaba 4,4 MB para 1780 viajes (unos 2,5 KB por viaje); con 200 000 vehículos, unos 500 MB, y se leía dos veces | Lectura en flujo: 0,7 MB para el mismo archivo, guardando solo identificador, salida y llegada. Lo usan el resumen y la conciliación |
| 3 | **Hallazgo de seguridad.** La configuración de SUMO se abría con la ruta que decía el manifiesto, antes de comprobar que fuera uno de los archivos verificados. Un manifiesto alterado con `../..` podía hacer que se leyera un archivo de fuera de la carpeta. SUMO no llegaba a ejecutarse (el corredor rechaza esas rutas), pero la lectura ya habría ocurrido | El manifiesto debe declarar `escenario.sumocfg`, el archivo de la carpeta; cualquier otra ruta se rechaza con `PATH_NOT_ALLOWED`. Prueba con tres rutas hostiles |
| 4 | **Código sobrante.** `reconcile` tenía una lectura de viajes propia, duplicada con la del resumen | Se usa `read_trips` en los dos lugares |

## Desviaciones frente a F0

| Tema | F0 | Lo construido | Por qué |
|---|---|---|---|
| Nombre del resultado | `RunResult` | `SimulationResult` (el que ya existe) | Así lo decidió F0 (D1): no se renombra algo que ya funciona |
| Memoria antes de empezar (D19) | Se exige 1 GiB libres y se vigila SUMO | **Pendiente**: va en F2 | Lo que se midió en F1 es la memoria de Python, no la de SUMO. Vigilar SUMO requiere el proceso controlado de F2 |
| `tiempos.json` (D7) | Se escribe en toda corrida terminal | **Pendiente**: va en F2 | Depende de medir el tiempo dentro del proceso controlado |

## Qué no hace F1 (queda para las fases siguientes)

- **F2:** proceso controlado (tiempo límite, cancelación, topes de salida, vigilancia de la memoria de SUMO) y `tiempos.json`.
- **F3:** corridas interrumpidas y reintentos.
- **F4:** el comando `simulate run` (si lo aceptas).
- **F5:** verificación final con el caso real, mutaciones, inspección y cierre de HU04.

## Estado del repositorio

- Archivos nuevos: `run_inputs.py`, `tripinfo.py` y cuatro pruebas. Cambian `fs.py`, `runner.py`, `reconcile.py` y los lectores (cambios pequeños, sin cambiar mensajes ni límites).
- Autor `crisroco`, sin línea de coautoría.
- Sin subir: 14 commits locales. `origin/main` sigue en `9fb7944`. No se ha hecho push: se sube cuando lo pida el Product Owner.
