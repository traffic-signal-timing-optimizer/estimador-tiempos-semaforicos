# Acta 2026-10-31: DEV06 · F0 (decisiones de la corrida aislada)

- **Tipo:** fase F0 de DEV06 (HU04; P0, tamaño M). Dependencias: DEV03 y DEV04, cerradas en local.
- **Autorización:** el Product Owner aprobó el plan por fases de DEV06 y pidió ejecutar F0 («ok ejecuta F0»), con datos sintéticos y el orden de flujos que dio el 2026-10-31.
- **Alcance de F0:** solo decisiones por escrito. No hay código ni archivos de datos. DEV06 no toca código del modelo: el primer código del modelo es DEV16.

## Qué pide la documentación

- `02_Requisitos_y_plan.md`, DEV06: «Materializar rutas, tipos y plan fijo en run_dir; declarar cohorte y fronteras; configurar outputs requeridos». Archivo propuesto: `simulacion/prepare.py`. Resultado: «Entradas SUMO con manifiesto». Verificación: QA07 y QA25.
- HU04: «Red existente preservada; demanda/plan/semilla/versiones registrados; exit code y outputs comprobados; fallos sin métricas».
- `03_Pruebas_y_operacion.md`, protocolo: una cohorte de vehículos solicitados, con ID, movimiento, tipo, ruta y hora de salida programada; la demanda materializada se reutiliza entre alternativas; se registran los hashes de rutas y de los atributos individuales; calentamiento, estado inicial, intervalo de medición y drenaje comunes.
- QA25: cohorte con vehículos terminados, inconclusos y no insertados; el número pedido se conserva y ningún caso se excluye sin registro.
- QA07 (ejecutar y comprobar archivos y versiones), QA09 (réplicas) y QA10 (seguridad de rutas y archivos) se ejercitan parcialmente en F3; el resto es de DEV07 y DEV08.

## Qué se reutiliza

- El programa derivado de DEV03 (`compile_program`) y la tabla de movimientos (`network_map`).
- El corredor de SUMO de DEV00 (`run_simulation`): recibe una carpeta fuente y un `.sumocfg` relativo, y fija por su cuenta las salidas `tripinfo` (con vehículos inconclusos) y `statistics`.
- `publish_files` para publicar carpetas sin dejarlas a medias.
- El contrato `schemas/scenario.schema.json` y su fixture; hoy no tiene modelo tipado.

## Decisiones

| # | Tema | Decisión | Por qué |
|---|---|---|---|
| D1 | Carpeta de la corrida | `datos/derivados/entradas/<id-del-escenario>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/`, publicada de una vez y sin sobrescribir. Autosuficiente: lleva `escenario.sumocfg`, la red copiada (verificada por huella), `demanda.rou.xml`, `programa.tll.xml`, `cohorte.csv` y `manifiesto.json`. Sirve como carpeta fuente de `run_simulation` | Una corrida aislada no depende de archivos fuera de su carpeta. Mismo patrón que el programa derivado y el reporte de calidad |
| D2 | Relación con DEV07 | DEV06 no ejecuta SUMO en producción. F3 lo ejecuta solo para verificar, con el corredor existente. DEV07 deberá tomar el fin de simulación del manifiesto (hoy `RunLimits` tiene un límite provisional propio) | Separar preparar de ejecutar, como pide el plan |
| D3 | Rutas | Entrada explícita `rutas.json`, `{movimiento: [calles]}`. Se valida que las calles existan, que las consecutivas estén conectadas en la red y que la ruta contenga el paso desde la calle de entrada del movimiento a una de sus calles de salida. Se exige ruta para todo movimiento con flujo mayor que cero. No se inventan rutas | Las rutas largas del cruce real dependen de DEC04 (límites del área), todavía abierta. Para el ejemplo sintético, la ruta es la calle de entrada seguida de la de salida |
| D4 | Carril de entrada | Cada vehículo sale en el carril de entrada de su movimiento (`departLane`). SUMO puede cambiarlo antes del cruce, porque no se fuerza | **Limitación registrada:** el movimiento es la intención del vehículo; el carril con que cruza la línea de parada no queda garantizado |
| D5 | Cuántos vehículos | Por movimiento: `N = flujo × tiempo de medición ÷ 3600`, redondeado al entero más cercano; el reparto entre clases usa el método del mayor resto, así que la suma es exacta. Una clase con proporción 0 tiene 0 vehículos. El flujo cero no lleva composición | «El N solicitado se conserva» (QA25) |
| D6 | Cuándo salen | Horas uniformes al azar dentro de la ventana, redondeadas al tick del caso. La semilla de cada movimiento sale de `SHA-256(semilla, movimiento)`: agregar un movimiento no cambia los de los demás | Reproducible e independiente entre movimientos |
| D7 | Calentamiento | La demanda se genera también antes de la medición (`flujo × calentamiento ÷ 3600`, de 0 a `calentamiento`). Esos vehículos se simulan pero no son cohorte (`en_cohorte = no`). La cohorte son los que salen en `[calentamiento, calentamiento + medición)` | Arranque con la red vacía y llenado antes de medir |
| D8 | Vehículos uno por uno | Se escriben como `<vehicle>`, no como `<flow>`, ordenados por hora de salida (SUMO lo exige). ID `<movimiento>.<clase>.<n>` (los del calentamiento con `cal`) | La misma lista exacta se reutiliza entre alternativas de semáforo |
| D9 | IDs seguros | Movimiento y clase solo con letras, números, guion bajo y guion; otros se rechazan. El XML se escribe con la biblioteca estándar (escapado automático); los nombres de archivo son fijos | QA10: nada de caracteres peligrosos en los archivos de SUMO |
| D10 | Tipos de vehículo | Entrada explícita `tipos.json`, `{clase: {vClass, atributos}}`. Todas las clases del caso necesitan tipo; solo atributos de una lista (largo, ancho, separación mínima, aceleración, deceleración, velocidad máxima) y numéricos | Los parámetros de los vehículos del cruce real son supuestos del equipo, sin aforos: se marcan provisionales |
| D11 | Frontera | Solo se admite la política `DEMO_EMPTY_START_FIXED_ROUTES`: red vacía al inicio y rutas fijas, sin recalcularlas. Otro identificador se rechaza | La política real de Frutales se define con DEC04 |
| D12 | Semillas | Se registran por separado la semilla de la demanda y la de SUMO. Por defecto la de SUMO es igual a la de la demanda | Cierra el criterio de HU04 pendiente desde DEV03 |
| D13 | Salidas requeridas | `tripinfo` con vehículos inconclusos y `statistics`, los mismos del corredor. El manifiesto las lista. Colas y trayectorias (plan de instrumentación) son de DEV19 | Evita duplicar lo que ya hace DEV00 |
| D14 | Opciones de SUMO | Paso de simulación = tick del caso; fin = calentamiento + medición + drenaje máximo. Opciones adicionales solo de una lista (`lateral-resolution`, `collision.check-junctions`); por defecto ninguna. Se registran en el manifiesto | Los cruces con motos usan subcarriles; la lista evita opciones arbitrarias |
| D15 | Programa de semáforo | Se recibe el programa derivado de DEV03 y se copia tal cual; el manifiesto registra su huella. La demanda se materializa una vez por escenario y se reutiliza entre alternativas | Las alternativas se comparan con exactamente los mismos vehículos |
| D16 | Escenario tipado | Se crea el modelo `Scenario` (`dominio/scenario.py`) con prueba de contrato contra su esquema. Reglas: el escenario es del mismo caso, versión y origen; todos los movimientos del caso tienen fila de demanda (una ausencia no es un cero); las clases de la composición existen en el caso y suman 1; la composición solo es nula si el flujo es cero | Hoy el contrato existe pero nada lo valida |
| D17 | Límites | Máximo de vehículos por cohorte y de tamaño de archivo, con error claro al superarlos (valor provisional: 200 000 vehículos) | Evita corridas que agoten el equipo |
| D18 | Manifiesto | Huellas de cada archivo, del caso (forma canónica), de la red, del escenario, de rutas y tipos; semillas; fin de simulación; N total y por movimiento y clase; salidas requeridas; política de frontera; hora de creación en UTC | Cubre «demanda, plan, semilla y versiones registrados» |
| D19 | Cohorte | `cohorte.csv` con ID, movimiento, clase, tipo, ruta, hora de salida, si es cohorte y una huella por fila. Formato de las planillas del equipo (`;`, BOM, fin de línea de Windows). El manifiesto guarda la huella de cada ruta | Cumple «hashes de rutas y atributos individuales» |
| D20 | QA25 | F3 incluye una función mínima que cruza los IDs de la cohorte con los viajes de SUMO y clasifica cada vehículo como terminado, inconcluso o no insertado. Las métricas (demora, colas) son de DEV19 | La prueba de QA25 se hace sobre los IDs; las métricas no entran en DEV06 |

## Perfil de demanda sintético (supuesto, no medido)

Está basado en el orden de flujos que dio el Product Owner: Javier Prado en los dos sentidos con el mayor flujo; el giro a la izquierda es importante pero menor que el recto; Los Frutales norte→sur, moderado; sur→norte, el menor. **No son conteos.** Las cifras son un supuesto del equipo, calculadas para que ningún acceso supere su capacidad con los verdes actuales.

Capacidad de referencia: carriles × 1800 veh/h por carril × (verde ÷ 206 s). Los 1800 veh/h por carril son un valor de referencia, sin tiempo perdido por arranque.

| Acceso | Movimientos y flujo (veh/h) | Total | Capacidad de referencia | Ocupación |
|---|---|---|---|---|
| Javier Prado este→oeste (4 carriles, verde 82 s) | M01 derecha 230; M02, M03, M04, M05 recto 520 cada uno | 2310 | 2866 | 0.81 |
| Javier Prado oeste→este, recto y derecha (3 carriles, verde 132 s) | M11 derecha 230; M12, M13, M15 recto 520 cada uno | 1790 | 3460 | 0.52 |
| Javier Prado oeste→este, giro a la izquierda (3 carriles, flecha 45 s) | M14, M16, M17 izquierda 190 cada uno | 570 | 1180 | 0.48 |
| Los Frutales norte→sur (2 carriles, verde 60 s) | M20 derecha 60; M21, M22 recto 160 cada uno; M23 izquierda 100 | 480 | 1049 | 0.46 |
| Los Frutales sur→norte (2 carriles, verde 45 s) | M06 derecha 30; M07, M08 recto 60 cada uno; M09 izquierda 40 | 190 | 786 | 0.24 |
| Accesos menores (solo giro a la derecha) | M10, M18, M19: 50 cada uno | 150 | — | — |

Javier Prado oeste→este suma 2360 veh/h entre recto, derecha e izquierda; el giro a la izquierda (570) es el 24 % de ese acceso.

Composición provisional, por movimiento:

- Rectos: auto (`passenger`) 82 %, moto 8 %, camión 6 %, bus 4 %.
- Giros a la derecha y a la izquierda: auto 88 %, moto 8 %, camión 4 %, sin buses.

Es la misma lógica de la demanda de R1 (autos mayoritarios, motos y camiones minoritarios, buses solo en recto), también sin aforos. En una hora, el perfil genera unos 5490 vehículos; en una medición de 900 s, unos 1370.

## Fases siguientes

| Fase | Qué se hace | Criterio de cierre |
|---|---|---|
| F1 | Modelo del escenario y reglas (D16); generación de la cohorte (D5 a D9, D17, D19): mismos insumos y semilla dan la misma lista; N exacto | Cohorte exacta y reproducible; escenario del fixture válido; contrato verificado |
| F2 | Entradas de SUMO: tipos, rutas, demanda, programa, configuración y manifiesto, publicados en carpeta nueva (D1 a D4, D10 a D15, D18) | Archivos publicados con huellas correctas; carpeta apta para `run_simulation` |
| F3 | Verificación con SUMO sobre el fixture, conciliación de IDs (D20), seguridad de nombres y rutas, mutaciones | QA07 y QA25 pasan; originales intactos; mutaciones detectadas |
| F4 | Cierre de DEV06 | Acta y tabla de cumplimiento de HU04 |

## Qué queda para el Product Owner

1. **Confirmar o cambiar las cifras del perfil sintético** (tabla anterior). Se pueden ajustar sin tocar el código.
2. **Límites del área de estudio (DEC04)**: sin ellos, las rutas del cruce real quedan como un supuesto mínimo (entrada y salida del cruce).
3. **Parámetros reales de los vehículos** (tamaños, aceleración): provisionales hasta contar con datos.

## Estado

- Sin código, sin archivos de datos y sin commits de código en esta fase. Este acta es el único cambio.
