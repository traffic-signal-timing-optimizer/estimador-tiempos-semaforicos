# Acta 2026-10-31: DEV06 · F1 (escenario y cohorte de vehículos)

- **Tipo:** fase F1 de DEV06 (HU04; P0, tamaño M). Dependencia: F0 de DEV06.
- **Autorización:** el Product Owner pidió ejecutar F1 («Ejecuta F1»).
- **Alcance de la fase:** el modelo tipado del escenario (D16) y la generación de la cohorte (D5 a D9 y D17). No escribe archivos de SUMO ni ejecuta SUMO: eso es F2 y F3. Datos sintéticos. No toca código del modelo.

## Qué se construyó

| Archivo | Qué contiene |
|---|---|
| `src/semaforo/dominio/scenario.py` | Modelo `Scenario` (con `Request` y `DemandRow`) que sigue el contrato `schemas/scenario.schema.json`; `parse_scenario`, `scenario_issues`, `accept_scenario`; errores `ScenarioInvalidError` (código `INPUT_SCHEMA`) |
| `src/semaforo/simulacion/cohort.py` | `generate_cohort(scenario, case, max_vehicles)`: lista exacta de vehículos con identificador, movimiento, clase, hora de salida y marca de cohorte; conteos pedidos por movimiento y clase; `CohortError` |
| `tests/unit/test_scenario.py` | 84 pruebas: contrato, estructura y consistencia |
| `tests/unit/test_cohort.py` | 66 pruebas: cantidades, reproducibilidad, horas, calentamiento, identificadores, límites y seguridad |

El modelo del escenario no lee archivos ni lanza procesos (ADR01). La cohorte tampoco: recibe un escenario y un caso ya leídos y devuelve la lista.

### Reglas del escenario

| Regla | Qué exige |
|---|---|
| SCEN-S01 a S03 | Estructura del contrato v1.0, identificadores sin espacios ni caracteres invisibles, versión `MAYOR.MENOR.PARCHE` (mismas ideas que CASE-S01 a S03) |
| SCEN-C01 | Escenario y solicitud son del mismo caso y versión que el caso; el origen del escenario (`synthetic` o `field_derived`) corresponde al de su solicitud (`synthetic` o `field`) |
| SCEN-C02 | Una fila de demanda por cada movimiento del caso, una sola, y ninguna de un movimiento que el caso no tiene. Una fila ausente no es un cero |
| SCEN-C03 | La composición usa clases del caso, cada proporción está entre 0 y 1 y suman 1 (tolerancia de 1e-9). Solo puede faltar si el flujo es cero. Una clase que no se nombra vale 0 |
| SCEN-C04 | El flujo está dentro del dominio de flujos del movimiento |
| SCEN-C05 | La ventana de observación tiene instantes ISO 8601 con zona horaria y el fin es posterior al inicio; calentamiento, medición y drenaje son múltiplos del tick del caso |
| SCEN-C06 | La política de frontera del escenario es la del caso |

Todos los problemas se informan juntos, cada uno con su regla, su campo y su motivo (máximo 100 y un último que cuenta los demás), igual que en el caso.

### Cómo se genera la cohorte

- **Cuántos.** Por movimiento: flujo × tiempo ÷ 3600, redondeado al entero más cercano (la mitad sube). Se calcula con fracciones exactas, tomando los decimales como los escribió quien dio el dato (1.2 veh/h durante 1500 s son exactamente 0.5 vehículos y suben a 1; en coma flotante habrían bajado a 0). El reparto entre clases es por el mayor resto, así que la suma es exacta; en un empate gana la clase de menor identificador.
- **Cuándo salen.** Horas uniformes al azar dentro de la ventana, llevadas hacia abajo al tick del caso. Cada movimiento y cada ventana tienen su propia semilla, derivada con SHA-256 de la semilla de la demanda, el movimiento y la ventana.
- **Calentamiento.** Se genera demanda de 0 a `warmup_s`; esos vehículos no son cohorte (`in_cohort = falso`). La cohorte son los que salen en `[warmup_s, warmup_s + measure_s)`.
- **Identificadores.** `<movimiento>.<clase>.<n>` y, en el calentamiento, `<movimiento>.cal.<clase>.<n>`, con `n` desde 1 en el orden de salida.
- **Límite.** Más de 200 000 vehículos (calentamiento incluido) se rechaza antes de generar nada, con el número pedido en el mensaje.
- **Seguridad.** Movimientos y clases solo con letras, números, guion bajo y guion; otros se rechazan antes de generar.

## Ajustes frente a las decisiones de F0

| Tema | F0 | Lo construido | Por qué |
|---|---|---|---|
| Origen (D16) | «El escenario es del mismo caso, versión y origen» | El origen del escenario se compara con el de **su solicitud**, no con el del caso | Al preparar el escenario sintético del caso real se vio el error: el caso-001 es de campo y la demanda es sintética, así que la regla original la habría rechazado. El origen del escenario es el de la demanda. El modelo de referencia de la documentación (`tools/contracts/modelos_contrato.py`) tampoco compara orígenes con el caso |
| Redondeo de la hora (D6) | «Redondeadas al tick» | Hacia abajo | Con redondeo al más cercano, una hora podía quedar exactamente en el final de la ventana y caer en la ventana siguiente |
| Semilla (D6) | De la semilla y el movimiento | De la semilla, el movimiento y la ventana (calentamiento o medición) | Cambiar el calentamiento ya no cambia los vehículos de la cohorte; la medición queda igual |
| Empates | Sin definir | Gana el menor identificador de clase | Resultado independiente del orden en que el caso lista las clases |
| Identificador del calentamiento (D8) | `cal` sin posición | `<movimiento>.cal.<clase>.<n>` | El punto separa sin ambigüedad porque los nombres no pueden llevarlo |

## Verificación

- **Contrato:** el modelo coincide con `schemas/scenario.schema.json` salvo los textos de documentación; los tres escenarios del repositorio (`scenario.json`, `scenario_test.json`, `scenario_validation.json`) se aceptan contra el caso de ejemplo.
- **Pruebas nuevas:** 150. Suite completa: **1186 pasan y 4 se saltan** (enlaces simbólicos, que este equipo no permite sin privilegios). Formato, lint, tipos y los contratos de referencia sin observaciones (`scripts/check.ps1`).
- **Mutaciones:** 62 fallos introducidos a propósito. En la primera pasada sobrevivieron 5; cuatro eran huecos reales y se cerraron con pruebas: la tolerancia de la suma de proporciones aceptaba hasta 0.01 de error; el dominio de flujos no probaba el ruido de coma flotante en los bordes; la ventana del calentamiento podía ser un tick más larga; y una rama sin efecto se eliminó del código. Resultado final: **60 detectadas, 1 equivalente y 1 omitida** por haber quitado su código. El equivalente es dividir por la suma de las proporciones: no cambia la cantidad por clase salvo en casos patológicos, pero garantiza que las partes sumen exactamente el total, así que se conserva.
- **Ejemplo con el caso real** (carpeta de trabajo local, fuera del repositorio): se generó `datos/escenarios/caso-001/ESC-SINT-001.json` con el perfil sintético de F0 (calentamiento 300 s, medición 900 s, drenaje 900 s, semilla 100) y se comprobó:
  - el escenario es válido contra el caso-001;
  - **1831 vehículos** en total, de ellos **1377 de cohorte** (5490 veh/h × 900 s ÷ 3600 son unos 1372; la diferencia viene del redondeo por movimiento);
  - cohorte por clase: 1151 autos, 108 motos, 77 camiones, 41 buses;
  - los movimientos de mayor flujo (por ejemplo M02 a M05 y M12, M13, M15) piden 130 cada uno; los giros a la izquierda de Javier Prado (M14, M16, M17), 48 cada uno; Los Frutales sur→norte, entre 8 y 15;
  - la misma entrada da exactamente la misma lista.

## Hallazgo para F2

La política de frontera del caso-001 es `sin-semaforos-vecinos`. La decisión D11 dice que solo se admite `DEMO_EMPTY_START_FIXED_ROUTES`, y la regla SCEN-C06 exige que el escenario use la del caso. Si se mantiene D11 tal cual, F2 rechazaría el caso real. **Propuesta para F2:** admitir las dos políticas, porque en DEV06 significan lo mismo (red vacía al inicio y rutas fijas sin recalcular), y rechazar cualquier otra. La política real definitiva depende de los límites del área de estudio (DEC04).

## Qué queda abierto

**Para el Product Owner:**
- Confirmar o cambiar las cifras del perfil sintético (acta de F0). Se editan en `datos/escenarios/caso-001/ESC-SINT-001.json` sin tocar código.
- Límites del área de estudio (DEC04) y parámetros reales de los vehículos (tamaños, aceleración).
- Confirmar el punto del hallazgo de arriba (dos políticas de frontera admitidas) cuando empiece F2.

**Del plan:**
- F2: entradas de SUMO (tipos, rutas, demanda, programa, configuración y manifiesto), publicadas en carpeta nueva. Agrega a la lista de F1 las rutas, el tipo y la huella por fila.
- F3: verificación con SUMO, QA07 y QA25 por IDs, seguridad de nombres y rutas.
- F4: cierre de DEV06 con la tabla de HU04.

## Estado del repositorio

- Archivos nuevos: `src/semaforo/dominio/scenario.py`, `src/semaforo/simulacion/cohort.py`, `tests/unit/test_scenario.py`, `tests/unit/test_cohort.py` y esta acta. Autor `crisroco`, sin línea de coautoría.
- `origin/main` sigue en `9fb7944`. Siguen sin subir los commits de DEV04, DEV05 y DEV06 F0, más el de esta fase. No se ha hecho push: se sube cuando lo pida el Product Owner.
