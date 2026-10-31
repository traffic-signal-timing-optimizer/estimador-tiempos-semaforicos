# Acta 2026-10-30: DEV03 · F1 (mapa de la red: movimientos y enlaces del semáforo)

- **Tipo:** fase F1 del plan de DEV03 (HU01, HU04; P0, tamaño L). Dependencias: DEV00 y DEV02, cerradas.
- **Autorización:** el Product Owner aprobó el plan por fases y pidió continuar con F1 tras cerrar F0 (acta `2026-10-30-dev03-f0-tiempos-y-limites.md`).
- **Alcance de la fase:** extraer el semáforo, sus enlaces y sus conexiones de la red; asignar cada enlace a un movimiento del caso; comprobar la coincidencia. No genera ningún programa ni modifica la red.

## Qué se construyó

Módulo `src/semaforo/caso/network_map.py`, con `build_network_map(path, case) -> NetworkMap`.

- **Política de un solo semáforo** (decidida en F0): si la red tiene un número distinto de semáforos, la función se detiene con un error `INPUT_SCHEMA` y no asigna nada por suposición.
- **Reglas del mapa** (los problemas se informan todos juntos, con su campo y su motivo):
  - `MAP-01` (propiedad de enlaces): el semáforo del movimiento debe ser el de la red; ningún enlace puede pertenecer a dos movimientos; cada enlace del semáforo debe pertenecer a algún movimiento.
  - `MAP-02` (conexiones): cada enlace declarado debe tener al menos una conexión en la red; el carril de salida de cada conexión y la calle de llegada deben estar declarados en el movimiento; cada carril declarado debe usarse.
- **Puntos de espera:** un giro con espera tiene una señal propia que SUMO numera aparte. El mapa la asigna al movimiento que entra por el enlace de paso.
- Reutiliza `read_movements` (conexiones, QA23) e `read_network_inventory` (número de enlaces, DEV00). No duplica la lectura del XML.

## Verificación

- **Pruebas nuevas:** `tests/unit/test_network_map.py`, 10 pruebas que pasan. Cubren el fixture de demostración sin problemas, puntos de espera, cero o dos semáforos (rechazo), enlace sin conexión, calle no declarada, carril no usado, enlace sin dueño, enlace con dos dueños y semáforo ajeno.
- **Suite completa:** 901 pruebas que pasan y 4 saltos por enlaces simbólicos (que este equipo no permite crear sin privilegios).
- **Calidad:** formato, lint y tipos sin observaciones en los archivos nuevos.
- **Red real revisada (recepción R1):** se comparó el mapa con la tabla de movimientos que QA23 y QA24 ya revisaron (`datos/derivados/recepcion/20261028T031008Z_15e51d6c/movements.json`).
  - Resultado: 1 semáforo, 26 enlaces, 23 movimientos, 0 problemas.
  - Los enlaces 0 a 22 son de paso y los enlaces 23, 24 y 25 son puntos de espera de giros.
  - Todos los enlaces tienen dueño.
  - La comprobación se hizo con un script de exploración fuera del repositorio; no se versiona porque apunta a datos de la simulación.
- **Red original intacta:** la huella SHA-256 de `osm.net.xml.gz` del escenario R1 es `89d4a252…`, igual a la del manifiesto de la recepción. F1 solo lee.

## Hallazgos para las fases siguientes

- Los tres puntos de espera (enlaces 23 a 25) no aparecen en la lista de enlaces de los movimientos del caso, pero sí forman parte de un giro. El programa derivado (F2) debe dejarlos en el estado que corresponde en cada fase. Si no se hace, el programa quedaría incompleto.
- El identificador del caso que usa la recepción (`frutales-r1`) contiene el nombre del cruce. Lo registrado en F0 pide que la carpeta del programa derivado use un identificador neutro. Se fijará en el caso que se formalice en F2; la recepción, que es inmutable, no cambia.

## Pendiente

- **F2:** `simulacion/compiler.py` genera el programa derivado a partir de los tiempos del caso y del mapa de F1, en la carpeta definida en F0.
- **F3:** prueba de que, con los tiempos actuales, el programa derivado es idéntico al original, fase por fase, y revisión de QA23 y QA24 por el Product Owner.
- **F4:** cierre de DEV03.
