# Acta 2026-10-31: DEV06 · F2 (entradas de SUMO de la corrida aislada)

- **Tipo:** fase F2 de DEV06 (HU04; P0, tamaño M). Dependencias: F0 y F1 de DEV06; DEV03 (programa derivado).
- **Autorización:** el Product Owner pidió ejecutar F2 («ok Ejecuta f2») después de la propuesta de F1 de admitir dos políticas de frontera. También pidió que, desde ahora, cada tarea cierre con una inspección propia de lo desarrollado; la de esta fase está más abajo.
- **Alcance de la fase:** materializar las entradas de SUMO en una carpeta nueva, autosuficiente y con manifiesto (D1 a D4 y D9 a D19 de F0). No ejecuta SUMO en producción (D2). La verificación formal con SUMO (QA07, QA25) es de F3; aquí solo se hizo una corrida de control. Datos sintéticos. No toca código del modelo.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `src/semaforo/caso/json_input.py` | `read_json`: lectura segura de JSON (límite de tamaño, sin enlaces, UTF-8 con o sin BOM, sin claves repetidas ni `NaN`) |
| `src/semaforo/caso/network_graph.py` | `read_network_graph`: calles, tramos internos, carriles con sus permisos y pares de calles conectadas |
| `src/semaforo/caso/case_network.py` | Se agrega `verified_network_path`, que reutiliza la verificación CASE-N01 (dentro de la carpeta del caso, sin enlaces y con su huella) |
| `src/semaforo/simulacion/demand_inputs.py` | Modelos `RouteTable` (`rutas.json`) y `VehicleTypes` (`tipos.json`); lectores de rutas, tipos y escenario; reglas ROUTE-01 a 05 y TYPE-01 a 03 |
| `src/semaforo/simulacion/prepare.py` | `build_inputs` (arma los archivos sin escribir) y `publish_inputs` (publica la carpeta) |

### La carpeta que se publica

`datos/derivados/entradas/<id-del-escenario>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/`, de una vez, de solo lectura y sin sobrescribir:

| Archivo | Contenido |
|---|---|
| `escenario.sumocfg` | Red, demanda y programa como archivos de la carpeta; inicio 0, fin = calentamiento + medición + drenaje, paso = tick del caso, semilla de SUMO, opciones admitidas. No declara salidas (las fija el corredor) ni rutas absolutas |
| `red.net.xml` o `red.net.xml.gz` | Copia byte a byte de la red del caso, verificada dos veces por su huella |
| `demanda.rou.xml` | Un tipo por clase usada, una ruta por movimiento con vehículos y cada vehículo con su tipo, ruta, hora, carril de salida y velocidad de entrada, ordenados por hora |
| `programa.tll.xml` | El programa derivado de DEV03, copiado tal cual después de comprobar que es del mismo caso, de la misma red y que su archivo tiene la huella de su manifiesto |
| `cohorte.csv` | Un vehículo por fila: ID, movimiento, clase, tipo, ruta, hora, carril, si es cohorte y la huella de sus atributos (incluye la ruta completa y el tipo). Formato de las planillas del equipo |
| `manifiesto.json` | Huellas de cada archivo, del caso, del escenario, de las rutas, de los tipos y de cada ruta; programa y su manifiesto de origen; semillas de demanda y de SUMO; tiempos y ventana de la cohorte; vehículos por movimiento y clase; carril de salida de cada movimiento; salidas requeridas; opciones; limitaciones; hora de creación en UTC |

### Reglas nuevas

| Regla | Qué exige |
|---|---|
| ROUTE-01 | Cada movimiento con vehículos tiene ruta; no hay rutas de movimientos que el caso no tiene |
| ROUTE-02 | Las calles existen y no son tramos internos del cruce |
| ROUTE-03 | Cada calle está conectada con la siguiente |
| ROUTE-04 | La ruta pasa de la calle de entrada del movimiento a una de sus calles de salida |
| ROUTE-05 | Cada clase que circula por el movimiento tiene permiso en cada calle de la ruta y, si sale en la calle de entrada, en su carril |
| TYPE-01 | Un tipo por cada clase del caso, y ninguno de más |
| TYPE-02 | La clase de SUMO es de un vehículo de calle |
| TYPE-03 | Atributos numéricos de una lista y positivos; color con componentes de 0 a 255 |

Además se rechazan con su motivo: una política de frontera no admitida, una opción de SUMO fuera de la lista o con un valor de otro tipo, una semilla de SUMO fuera de 0 a 2 147 483 647, una demanda de más de 64 MB, un caso sin red y un ID de escenario que no sirve como nombre de carpeta.

## Ajustes frente a las decisiones de F0

| Tema | F0 | Lo construido | Por qué |
|---|---|---|---|
| Política de frontera (D11) | Solo `DEMO_EMPTY_START_FIXED_ROUTES` | También `sin-semaforos-vecinos`, la del caso real | Propuesta de F1, aceptada al autorizar F2. En esta etapa las dos significan red vacía al inicio y rutas fijas |
| Carril de salida (D4) | El carril de entrada del movimiento | Ese carril solo si la ruta empieza en la calle de entrada; si empieza antes, SUMO elige el mejor (`best`). Con varios carriles de entrada se usan por turnos | El índice de carril se refiere a la primera calle de la ruta. Las rutas del equipo empiezan varias calles antes del cruce |
| Velocidad de entrada | Sin decidir | `departSpeed="max"` (la mayor velocidad segura) | Es lo que usa la simulación del equipo (R1). Detectado en la inspección |
| Atributos de tipo (D10) | Largo, ancho, separación, aceleración, deceleración, velocidad máxima | Además, separación lateral, velocidad lateral, cambio de subcarril, alineación lateral, forma y color | Las motos de la simulación del equipo usan el modelo de subcarriles; sin esos atributos se perdía su comportamiento |
| Tipos y rutas en un archivo (D1) | Sin decidir | Dentro de `demanda.rou.xml` | SUMO los admite juntos; la carpeta queda con los seis archivos previstos |

## Verificación

- **Pruebas nuevas:** 149 (`test_json_input.py` 17, `test_network_graph.py` 12, `test_demand_inputs.py` 47, `test_prepare.py` 73). Suite completa: **1334 pasan y 5 se saltan** (enlaces simbólicos, que este equipo no permite sin privilegios). Formato, lint, tipos y contratos de referencia sin observaciones (`scripts/check.ps1`).
- **Mutaciones:** 84 fallos introducidos a propósito. En la primera pasada sobrevivieron 6; se cerraron 4 con pruebas (la lista de atributos admitidos, la alineación lateral y el color en el tipo escrito, y la segunda comprobación de la huella de la red). Al cambiar dos reglas durante la inspección se agregaron 3 mutaciones más; una sobrevivió (el error de lectura de la red) y se cerró con otra prueba. Resultado final: **81 detectadas, 2 que no se pueden detectar aquí y 1 mal planteada**. Las dos que quedan son: leer el JSON entero antes de comparar su tamaño (el resultado es el mismo; el límite protege la memoria) y el rechazo de enlaces simbólicos (esa prueba se salta en este equipo).
- **Control con el ejemplo de dos movimientos:** carpeta publicada y ejecutada con el corredor de DEV00 (fin tomado del manifiesto): 160 vehículos cargados e insertados, 160 terminados, 0 teletransportes, 0 choques, 0 avisos.
- **Control con el caso real** (carpetas locales, fuera del repositorio):
  - Entradas: `datos/escenarios/caso-001/ESC-SINT-001.json`, `rutas.json` y `tipos.json`; programa `datos/derivados/programas/caso-001/20261031T041338Z_63437585/`; opciones de la simulación del equipo (`lateral-resolution` 0.8 y `collision.check-junctions`).
  - Carpeta publicada: `datos/derivados/entradas/ESC-SINT-001/20261031T163018Z_ea425f32/`. La red copiada tiene la huella original (`89d4a252…`) y el programa la de DEV03 (`63437585…`).
  - SUMO 1.27.1 con fin 2100 s: **1780 vehículos cargados e insertados, 1780 terminados, 0 teletransportes, 0 choques**. Hubo 4 avisos de SUMO sobre fases sin amarillo o sin verde en las señales 23 y 9. Vienen del programa original de la red (`0`) y el derivado los repite porque es idéntico; no los produce F2.
  - Después de las correcciones de la inspección, el código produce exactamente los mismos archivos que esa carpeta (comparación byte a byte, salvo el manifiesto por la hora).

## Inspección de lo desarrollado

Se releyó el código nuevo contra las decisiones de F0 y se probó con el caso real antes de cerrar. Hallazgos y correcciones:

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | La red real no admite buses en las calles de Los Frutales, y el perfil sintético les daba 4 % de buses en los movimientos rectos (M07, M08, M21, M22). La regla ROUTE-05 lo detectó | En el escenario sintético ese 4 % pasa a autos (86 % autos, 8 % motos, 6 % camiones) |
| 2 | Los accesos menores M10, M18 y M19 son vías de servicio que solo admiten reparto, bicicletas y peatones; el perfil les daba 50 veh/h de autos, motos y camiones | En el escenario sintético su flujo pasa a 0 |
| 3 | La simulación del equipo hace entrar a los vehículos a la mayor velocidad segura; F2 los hacía salir detenidos | `departSpeed="max"` |
| 4 | Las motos de la simulación del equipo usan atributos de subcarriles que la lista de D10 no admitía | Lista ampliada (ajuste de D10) |
| 5 | Un mensaje decía «las rutas no son válidos» | Corregido; lo detectó una prueba |
| 6 | Si los carriles de entrada de un movimiento no estaban en una sola calle, el mensaje mostraba «None» | Mensaje propio que nombra los carriles |
| 7 | Un error del sistema al leer la red no salía como error tipado | Se informa como error de entrada con su motivo |
| 8 | Faltaba probar que, con otro programa de semáforo, los vehículos son exactamente los mismos (protocolo: la demanda se reutiliza entre alternativas) | Prueba nueva: con otro programa, la demanda, la cohorte, la red y la configuración son idénticas byte a byte |

**Efecto en el escenario sintético** (cambios 1 y 2): el total pasa de unos 5490 a **5340 veh/h**. La corrida tiene 1780 vehículos, de ellos 1338 de cohorte (antes 1831 y 1377): 1124 autos, 105 motos, 74 camiones y 35 buses.

## Limitaciones registradas en el manifiesto

1. El carril de salida es la intención del vehículo: SUMO puede cambiarlo antes del cruce. En el caso real todas las rutas del equipo empiezan antes de la calle de entrada, así que **SUMO elige el carril de todos los movimientos**. Los movimientos del mismo acceso que solo se distinguen por carril (por ejemplo, M02 a M05) comparten ruta y se diferencian solo por su identificador.
2. Los vehículos entran a la mayor velocidad segura. Como la red empieza vacía, no traen la cola de las calles anteriores.
3. Un solo tipo de vehículo por clase del caso. La simulación del equipo tiene subtipos (autos y camionetas, camiones ligeros y medianos) que aquí no se representan. Para los camiones se tomó el ligero.

## Qué queda abierto

**Para el Product Owner:**
- Confirmar los dos cambios del perfil sintético: sin buses en Los Frutales y sin tráfico en las vías de servicio M10, M18 y M19.
- Las rutas del caso real son las de la simulación del equipo (R1), y para M10, M18 y M19 la calle de entrada seguida de la de salida. Siguen siendo un supuesto hasta fijar los límites del área de estudio (DEC04).
- Los tipos de vehículo del caso real se tomaron de R1 y son provisionales.

**Del plan:**
- F3: verificación formal con SUMO (QA07 y QA25 por IDs, seguridad de nombres y rutas, originales intactos).
- DEV07 debe tomar el fin de la simulación del manifiesto: el corredor de DEV00 usa hoy su propio límite de 7200 s.
- F4: cierre de DEV06 con la tabla de HU04.

## Estado del repositorio

- Archivos nuevos: los cinco módulos y las cuatro pruebas de la tabla de arriba, y esta acta; `case_network.py` cambia solo para exponer la verificación de la red. Autor `crisroco`, sin línea de coautoría.
- `origin/main` sigue en `9fb7944`. Siguen sin subir los commits de DEV04, DEV05 y DEV06 F0 y F1, más el de esta fase. No se ha hecho push: se sube cuando lo pida el Product Owner.
