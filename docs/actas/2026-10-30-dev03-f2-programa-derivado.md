# Acta 2026-10-30: DEV03 · F2 (compilador del programa derivado)

- **Tipo:** fase F2 del plan de DEV03 (HU01, HU04; P0, tamaño L). Dependencias: DEV00 y DEV02, cerradas.
- **Autorización:** el Product Owner aprobó continuar con F2 tras F1 (acta `2026-10-30-dev03-f1-mapa-de-la-red.md`).
- **Alcance de la fase:** convertir duraciones de los slots en un programa de semáforo para SUMO, sin modificar la red, y publicarlo en la carpeta acordada en F0. No ejecuta simulaciones del plan ni compara con QA23/QA24 (eso es F3).

## Qué se construyó

- `src/semaforo/dominio/case_plan.py`: comprobación pura de unas duraciones frente a los límites del caso. Reglas `PLAN-01` (una duración finita por slot, ninguna de más), `PLAN-02` (límites del slot, inclusivos), `PLAN-03` (múltiplo del tick), `PLAN-04` (ciclo dentro del rango) y `PLAN-05` (verde de cada grupo dentro de sus límites). El ciclo y los grupos solo se evalúan si lo anterior pasa. Queda en el dominio porque la consulta del modelo necesitará la misma comprobación.
- `src/semaforo/simulacion/compiler.py`:
  - `compile_program(case, network_map, durations)` devuelve el programa (fases, XML y huella). Se niega a compilar si el mapa de la red de F1 tiene diferencias, si un slot no trae exactamente un estado del semáforo de la red y del largo correcto (`COMPILE-01`), o si las duraciones incumplen `PLAN-01` a `PLAN-05`.
  - `publish_program(root, case, program)` publica `root/<id-del-caso>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/` con `programa.tll.xml`, `tramos.json` (duraciones, límites y verde total de cada grupo) y `manifiesto.json` (huellas del programa, del caso y de la red). Reutiliza `publish_files`: la carpeta se escribe aparte y se publica de una vez, queda de solo lectura y nunca se sobrescribe (`RUN_EXISTS`). El identificador del caso debe servir como nombre de carpeta (letras, números, punto, guion y guion bajo); si no, `PATH_NOT_ALLOWED`.

## Decisión de formato (comprobada con SUMO 1.27.1)

El programa derivado es un **archivo adicional** de SUMO (`<additional><tlLogic .../></additional>`) con su propio `programID` (`derived`). Se comprobó con la red de demostración y con la red real revisada:

- Un programa con el **mismo** `programID` que uno de la red hace que SUMO se detenga con error; no se puede reemplazar el de la red.
- Un programa con un `programID` **nuevo** se suma a la red y SUMO lo activa desde el segundo 0. La red original no se toca.

El archivo no lleva las conexiones (`<connection>`) que sí lleva el programa de la candidata: esas sirven para reconstruir la red con `netconvert`, y aquí la red no se reconstruye.

## Verificación

- **Pruebas nuevas:** `tests/unit/test_case_plan.py` (11) y `tests/unit/test_compiler.py` (20), 31 en total. Suite completa: 932 pruebas que pasan y 4 saltos por enlaces simbólicos. Formato, lint y tipos sin observaciones.
- **Red de demostración:** el programa compilado con los tiempos de `response.json` tiene las mismas 6 fases (duración y estado) que el programa de la red.
- **Red real revisada (R1), con un caso armado fuera del repositorio:** mapa completo (23 movimientos, 26 enlaces); el programa derivado con los tiempos actuales (82, 5, 45, 5, 45, 5, 10, 5, 4 s) tiene las 9 fases iguales a las del programa de la red, ciclo de 206 s.
- **SUMO sobre una copia de R1 con el archivo derivado:** programa activo `derived`; las fases cambian en los segundos 0, 82, 87, 132, 137, 182, 187, 197, 202 y 206.
- **Mutaciones** (fallos introducidos a propósito en `network_map`, `case_plan` y `compiler`, para comprobar que alguna prueba los detecta): 55 en la primera pasada, 54 detectadas. La que sobrevivió era un filtro de `network_map.py` (F1) que ignoraba las conexiones de otro semáforo. Era código que nunca actuaba: el inventario también cuenta como semáforo a cualquiera citado solo en una conexión, así que con exactamente un semáforo toda conexión es suya. Se quitó el filtro y se agregó una prueba que fija esa política (un semáforo citado solo en una conexión cuenta como segundo semáforo y se rechaza). Segunda pasada: 54 de 54 detectadas.
- **Pruebas totales tras el cambio:** 933 pasan y 4 se saltan.
- **Red original intacta:** F2 solo lee la red; la prueba formal de huellas es de F3.

## Pendiente y hallazgos

- **F3:** comparar formalmente, sobre la red real, el programa compilado con el original (fase por fase y huellas), y revisión de QA23 y QA24 por el Product Owner. Pasos de ejecución real fuera del repositorio usaron una copia de R1 y el archivo de vista de la carpeta de la candidata, porque la copia de la recepción no trae `vista_buses.xml`, que la configuración pide.
- **Caso de Frutales:** todavía no existe como archivo del caso. Las pruebas reales usaron un caso armado en memoria. Formalizarlo (con un identificador neutro, según F0) es un paso previo a DEV06.
- **Formato:** SUMO escribe `<phase ... />` con un espacio antes de `/>`; es solo estética y no cambia el significado.
- **Fuera de alcance de F2:** varios semáforos por caso (se bloquean), peatones (DEC03) y ejecución del plan en una corrida (DEV06).
