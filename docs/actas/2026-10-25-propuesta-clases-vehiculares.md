# Acta 2026-10-25: propuesta de demanda con autos, camionetas, motos y camiones

- **Tipo:** decisión del Product Owner y preparación de R1 (DEV00, HU04)
- **Fecha:** 2026-10-25
- **Origen:** la primera pasada de QA23 sobre R0. El Product Owner observó que la simulación solo tiene autos y buses, y que en el cruce real también circulan camionetas, camiones de carga y motos.
- **Código:** commit `9ae453a` (corrección del conteo de vehículos de la auditoría, hallada al validar la propuesta).

## Decisiones del Product Owner

1. Incluir camionetas, motos y camiones de carga pequeños y medianos.
2. Las cantidades las propone el equipo. Son **parte del total** de cada acceso, no se suman.
3. La mayoría son autos, luego camionetas, luego motos, y el resto camiones.
4. Se mantiene el carril exclusivo de buses que ya existe.
5. Las motos deben comportarse de forma realista (circular entre carriles).
6. Los cambios se hacen en una copia; la carpeta original no se modifica.

## Qué se hizo

La propuesta está en `datos/propuestas/2026-10-25-clases-vehiculares/` (ignorada por git). Es una copia de la simulación original, que es idéntica a R0, con dos archivos cambiados:

- la demanda (`frutales_solo.rou.xml`) reparte cada flujo privado entre cinco tipos de vehículo y conserva el total por hora de cada acceso; los buses no cambian;
- la configuración (`frutales_solo.sumocfg`) activa el modelo de subcarriles de SUMO.

Según ADR09, la composición, las tasas y los resultados detallados quedan en el `LEEME.md` de esa carpeta. La carpeta incluye además el generador de la demanda, para poder reproducirla.

## Decisiones de modelado

| Decisión | Motivo |
|---|---|
| Camionetas como clase `passenger`, con un tipo propio más largo | La clase `delivery` podría usar las vías de servicio que hoy no usa ningún vehículo (comprobado sobre la red) |
| Camiones como clase `truck`, motos como `motorcycle` | Clases propias de SUMO, con los mismos permisos de carril que los autos en esta red |
| Sin cambios en la red | El carril exclusivo de bus (`allow="bus"`) ya excluye a los otros tipos |
| Modelo de subcarriles | Permite que las motos se desplacen dentro del carril y entre carriles |
| Llegadas regulares, como en R0 | Las llegadas aleatorias serían más realistas, pero la auditoría todavía no distingue «cargó menos por azar» de «terminó antes» |

## Validación

| Comprobación | Resultado |
|---|---|
| Totales por acceso | iguales a R0 |
| Vehículos declarados por la auditoría frente a los que carga SUMO | iguales, después de la corrección `9ae453a` |
| Corrida base de 7200 s | `succeeded`, sin teletransportes ni colisiones |
| Vehículos que no son bus en el carril exclusivo | ninguno, medido con la posición de cada vehículo en cada segundo |
| Comportamiento lateral de las motos | se apartan del centro del carril bastante más que los demás tipos |
| Planilla QA23 | muestra las clases nuevas («moto, auto, camión») |
| Carpeta original | sin cambios (hashes iguales a R0) |

## Problemas encontrados durante la validación

1. **SUMO ignora los flujos que no están ordenados por hora de inicio.** La primera versión de la propuesta perdió así la mayoría de los vehículos de los tipos nuevos. La auditoría del proyecto lo detectó (`LOADED_BELOW_DECLARED`) y se corrigió el orden.
2. **La auditoría contaba mal los flujos con intervalos no exactos.** Ver «Corrección del conteo» en el acta de F4. Se corrigió en el código (`9ae453a`).

## Siguientes pasos

1. El Product Owner revisa la propuesta en SUMO-GUI y, si la acepta, copia a su carpeta los tres archivos de la candidata a R1 (red, demanda y configuración; ver «Cambios de red de QA23»).
2. Con el aviso «SUMO listo» y su autorización, F10 hace la recepción oficial R1, y QA23 se repite sobre ella.

La composición es un supuesto provisional, sin aforos. Si el Product Owner obtiene conteos de campo, basta con cambiar las fracciones del generador.

## Cambios de red de QA23 (2026-10-25)

El Product Owner ordenó ejecutar los cambios de red que salieron de su primera pasada de QA23. Se hicieron en otra copia, `datos/propuestas/2026-10-25-clases-y-red-qa23/` (candidata a R1), que parte de la propuesta de clases. La carpeta original no se modificó.

| Tipo de observación | Cambio en la red |
|---|---|
| Giros que no existen en el cruce real | 11 conexiones eliminadas |
| Tramo de servicio que se debe eliminar | tramo eliminado; con él desaparecen los 7 giros que llevaban a él |
| Por Los Frutales no pasan buses | bus prohibido en los carriles de dos entradas y una salida de Los Frutales, sin tocar sus demás permisos |

No se cambiaron dos tipos de observación que no son cambios claros de la red: orígenes con un solo destino y cambio de carril después del cruce. Quedan para decidir.

Los cambios se aplicaron con `netconvert` sobre la red existente, con las mismas opciones con que ya se había corregido antes. Problema encontrado: al quitar conexiones, `netconvert` **borró `minDur` y `maxDur`** de las fases del semáforo actuado y dejó columnas sin uso en su programa. Se corrigió dándole el programa explícito, generado desde el original. La comparación de la red anterior con la nueva muestra:

- solo cambia lo pedido;
- los 35 movimientos que siguen conservan exactamente su secuencia de colores en las 12 fases;
- duraciones, `minDur` y `maxDur` iguales al original.

Efecto lateral aceptado: al cambiar la forma del cruce, cuatro giros pasan de «suave» a normal, con el mismo control.

Validación con una recepción completa en un espacio temporal:

- los movimientos del semáforo pasan de 53 a 35;
- la auditoría no encuentra ninguna ruta afectada;
- la corrida base termina bien, sin teletransportes ni colisiones.

En R1 la planilla QA23 se renumera (M01 a M35). El detalle está en el `LEEME.md` de la copia, junto con los archivos aplicados y la red anterior.

## Rutas agregadas a la candidata a R1 (2026-10-26)

Al revisar la red en netedit, el Product Owner indicó tres movimientos de Javier Prado que no tenían ruta: la derecha de este a oeste y la derecha y la izquierda de oeste a este. Se agregaron como rutas, con las conexiones que ya tiene el semáforo. Javier Prado conserva su total por sentido: los giros salen de él, y los buses siguen solo en recto. Las cantidades son un supuesto, sin aforos.

Validación: las rutas están conectadas para todas las clases, la auditoría no encuentra hallazgos nuevos y, en la corrida, todos sus vehículos entran y llegan. Queda un aviso para el Product Owner: SUMO registra dos frenados de emergencia en el giro a la izquierda de oeste a este.

## Semáforo de tiempo fijo (2026-10-26)

El Product Owner dio los tiempos reales de Javier Prado y decidió:

1. El semáforo pasa a **tiempo fijo**. Antes era actuado y no tenía detectores, que era el punto pendiente DEC06.
2. Las dos entradas de Javier Prado se ponen en verde a la vez, en todos sus carriles.
3. El giro a la izquierda de oeste a este tiene una flecha propia que se enciende después. Mientras tanto, los que giran avanzan y esperan dentro del cruce.
4. En el contexto peruano se gira a la izquierda desde los carriles 1, 2 y 3 de esa entrada; el carril 0 es el de la derecha.
5. Los tiempos de Los Frutales se están tomando en campo. Mientras tanto, el equipo pone unos provisionales.

Los tiempos dados cuadran sin ajustes: los dos sentidos tienen el mismo ciclo y la flecha solo cabe entre el fin del ámbar del sentido contrario y el fin del verde recto. Los supuestos son dos: el ámbar de la flecha y la ausencia de rojo total entre esas dos señales. La espera dentro del cruce se modeló con una segunda señal en el punto de espera de cada giro (`linkIndex2` de SUMO). Según ADR09, los tiempos, el reparto provisional y los resultados por flujo quedan en el `LEEME.md` de la candidata.

| Comprobación | Resultado |
|---|---|
| Cambios en la red | solo las 2 conexiones de giro agregadas y el programa; aristas, nodos y prioridades sin cambios |
| Programa de la red frente al archivo cargado | idéntico |
| Giros a la izquierda de oeste a este | todos cruzan solo con la flecha y antes esperan dentro del cruce |
| Frenados de emergencia en ese giro | desaparecen |
| Recepción completa en un espacio temporal | corrida `succeeded`; el inventario cuenta todas las señales, sin hallazgos |

Efecto que debe conocer el Product Owner, con los tiempos provisionales de Los Frutales de esta primera versión (corregidos en la sección siguiente): Javier Prado mejora y Los Frutales empeora mucho. Con el ciclo fijo, a Los Frutales le queda poco verde para la demanda supuesta de R0; antes el semáforo actuado alargaba sus verdes. Aparecen dos teletransportes por atasco y aumentan los vehículos que no llegan a entrar. Con los tiempos y aforos de campo de Los Frutales, esto puede cambiar.

Vacío encontrado en el código: la tabla de movimientos de F8 (QA23 y QA24) saltaba las conexiones internas y no mostraba las señales de la flecha. Por eso QA24 presentaba los giros a la izquierda como verdes desde la primera fase. El Product Owner autorizó corregirlo y quedó corregido; ver «Corrección: punto de espera dentro del cruce» en el acta de F8.

## Tiempos de Los Frutales y velocidad (2026-10-26)

El Product Owner dio los tiempos de las dos entradas de Los Frutales y decidió, hasta corroborarlo en campo:

1. Las dos entradas empiezan en verde a la vez, en todos sus carriles, y desde el primer segundo se puede ir de frente, a la derecha y a la izquierda.
2. Quien gira a la izquierda no cede el paso, como ocurre en Lima.
3. La velocidad máxima de todas las avenidas es 50 km/h.
4. Los 4 s en que los tiempos de Los Frutales no completan el ciclo de Javier Prado son un todo rojo.

Las entradas menores quedan siempre en rojo, como propuso el equipo: no tienen tiempo propio en el ciclo dado ni demanda en la simulación.

Ajuste del modelo: en el ámbar de oeste a este, el punto de espera del giro a la izquierda sigue en verde. Con ámbar, SUMO no hacía arrancar al vehículo que ya esperaba dentro del cruce, y quedaba atrapado en el camino de Los Frutales.

| Comprobación | Resultado |
|---|---|
| Cambios en la red | solo la velocidad de los tramos que superaban 50 km/h y el programa; programa idéntico al archivo |
| Recepción completa en un espacio temporal | corrida `succeeded`; entran todos los vehículos declarados |
| Ceder o no ceder en el giro a la izquierda | mismos choques dentro del cruce en tres semillas: la decisión no empeora la seguridad |

Efecto: Los Frutales deja de saturarse y Javier Prado pierde algo de lo ganado con la primera versión. Según ADR09, las cifras quedan en el `LEEME.md` de la candidata.

Quedan dos observaciones para el Product Owner:

- **Choques dentro del cruce.** La corrida base no activa la detección completa de choques dentro del cruce (`--collision.check-junctions`). Con ella activada aparecen entre 1 y 3 choques por corrida, que antes no se veían porque la red dejaba sin entrar a casi 300 vehículos.
- **Una moto atascada.** En algunas semillas, una moto que gira a la izquierda queda detenida dentro del cruce, desplazada hacia un lado, y causa la mayoría de los teletransportes. Es un problema del modelo de subcarriles, no del semáforo.

## Detección de choques dentro del cruce (2026-10-27)

El Product Owner corroboró en campo dos decisiones de la sección anterior: las dos entradas de Los Frutales empiezan en verde a la vez, y el giro a la izquierda no cede el paso. Los conductores conocen la zona y cruzan con cuidado de no chocar. Según su conocimiento, en el cruce hay unos 3 o 4 choques al año. Eso equivale a prácticamente ninguno en una corrida de 2 horas, así que todo choque de la simulación es un defecto del modelo.

Decisión: la candidata activa la detección completa de choques dentro del cruce (`collision.check-junctions`).

- **Dónde va.** En `frutales_solo.sumocfg`, no en el runner. La opción cambia la simulación, porque SUMO teletransporta al vehículo que choca, y el diseño técnico pide ejecutar el caso sin modificarlo.
- **Qué no cambia.** R0 queda igual.
- **Qué mostraban las validaciones anteriores.** Las de esta acta que dicen «sin colisiones» se midieron sin esta detección.

Se descartó ajustar los parámetros de conducta en el cruce (`jm*` de SUMO): solo actúan en enlaces que ceden el paso. Además, la revisión uno por uno de los choques mostró que ninguno es un giro a la izquierda contra el tráfico de frente. Las causas encontradas son tres:

1. Enlaces que cambian de carril en diagonal dentro del cruce, entre vehículos del mismo sentido. Es la observación tipo E de QA23 («cambio de carril después del cruce»), pendiente de decisión.
2. Con el modelo de subcarriles, vehículos que van lado a lado en un mismo carril y toman tramos internos que se separan.
3. La moto atascada.

Como diagnóstico se corrió sin subcarriles: los choques casi desaparecen, y el que queda está en un enlace diagonal. El detalle está en el `LEEME.md` de la candidata.

| Comprobación | Resultado |
|---|---|
| La opción se lee desde la configuración | mismos choques y teletransportes que pasándola por línea de comandos |
| Recepción completa en un espacio temporal | corrida `succeeded`, con los hallazgos de colisiones y teletransportes; inventario y auditoría sin hallazgos nuevos |

## Cada carril a su mismo carril (2026-10-27)

Decisión del Product Owner sobre la observación tipo E de QA23 («cambio de carril después del cruce»). En su revisión anotó que en la realidad se puede llegar a cualquier carril de la salida después de cruzar. La red, en cambio, hacía ese cambio dentro del cruce, con enlaces en diagonal entre vehículos que tenían verde al mismo tiempo.

Lo decidido: cada carril cruza a su mismo carril, y el cambio de carril se hace después, en la salida, donde SUMO respeta los espacios entre vehículos. Cambian 8 conexiones en tres accesos:

- **Javier Prado de este a oeste.** Cada carril va a su mismo carril, incluido el del bus. Además, el carril 2 recupera su paso recto: no tenía ninguna conexión desde QA23.
- **Los Frutales de sur a norte.** El carril 1 deja de abrirse hacia dos carriles de la salida.
- **Los Frutales de norte a sur.** La derecha entra al carril más cercano de Javier Prado.

Los giros a la izquierda y las entradas menores no cambian. El detalle está en el `LEEME.md` de la candidata.

| Comprobación | Resultado |
|---|---|
| Cambios en la red | solo esas 8 conexiones; los movimientos que siguen conservan su secuencia de colores en las 9 fases, y el programa de la red es idéntico al archivo |
| Choques dentro del cruce, tres semillas | ninguno, y sin frenados de emergencia (con más semillas sí hay: ver «Revisión del 2026-10-27») |
| Demoras por flujo | ninguno empeora; llegan todos los vehículos |
| Recepción completa en un espacio temporal | corrida `succeeded`, sin hallazgo de colisiones |

En R1, QA23 y QA24 tendrán 35 movimientos, más las 3 señales de la flecha. (Después, 23: ver «Revisión del 2026-10-27».)

Quedan dos puntos para el Product Owner:

- **La moto atascada sigue.** Causa pocos teletransportes por corrida y ningún choque. Se detiene sola, sin nada delante, al final del tramo interno del giro. Cambiar su alineación lateral la destraba, pero genera choques, así que no se aplicó.
- **La salida norte de Los Frutales.** Su primer tramo mide menos de un metro, y su carril derecho solo lleva a una calle lateral. Quien sigue al norte desde ese carril tiene que cambiarse de carril sin espacio para hacerlo. Se probó dejar que ese carril también siga al norte, pero empeora: habilita un giro a la izquierda cuyos vehículos, mientras esperan, invaden el recto de al lado. No se aplicó.

## Revisión del 2026-10-27

Antes de R1, el Product Owner pidió revisar todo lo hecho sobre R0 y autorizó aplicar las correcciones encontradas. El código de R0, sus recepciones y sus pruebas no tenían errores; los hallazgos estaban en la documentación y en la candidata a R1. El detalle está en el `LEEME.md` de la candidata.

### Decisiones del Product Owner

- **La salida norte de Los Frutales.** En la realidad, su carril derecho sigue de frente hacia el norte. La red no lo modela así (ver la sección anterior). Se repitió la prueba de dejarlo seguir: 6, 5 y 5 choques con las semillas 2026, 1 y 2, todos del recto del carril 2 de oeste a este contra el que gira a la izquierda desde el carril 1. La explicación de la sección anterior se confirma. El Product Owner aceptó esta diferencia para R1.
- **La moto atascada.** Aceptada como limitación de R1. No causa choques.

### Observación tipo D de QA23: un solo destino por entrada menor

En R0 el Product Owner anotó que desde cada una de las tres entradas menores solo se puede ir a una salida, a cualquiera de sus carriles, y solo en auto. La red les daba entre 4 y 5 salidas.

- Se quitaron 11 giros de esas entradas. Queda uno por entrada, hacia el carril más cercano de su salida, y el cambio de carril se hace después, como en «Cada carril a su mismo carril».
- Se quitó también el giro de Los Frutales de norte a sur hacia la vía de servicio `758735434#0` (M49 en R0). No está entre las salidas que enumeró el Product Owner, y los demás giros hacia esa vía ya se habían quitado.
- **«Solo autos» no se aplicó.** Cambiar o ampliar el permiso de esos carriles hace que `netconvert` recalcule la forma del cruce y el largo de los tramos que llegan a él, y la simulación empeora (33 teletransportes en una semilla). Fijar la forma del cruce fue peor. Como esas entradas no tienen demanda, el permiso no cambia la simulación.
- **Girar desde cualquier carril** (notas de QA23 en Los Frutales): cada giro se mantiene desde el carril de su lado. Girar desde el otro carril cruzaría en diagonal al que sigue recto.

| Comprobación | Resultado |
|---|---|
| Cambios en la red | solo esas 12 conexiones; carriles, largos, permisos y demás conexiones iguales; los 23 movimientos que siguen conservan su secuencia de colores, y el programa de la red es idéntico al archivo |
| Choques, 13 semillas | 16, unos 1,2 por corrida (la red anterior, 12 con las mismas semillas); la diferencia es del orden de la variación entre semillas |
| Demoras por flujo, 3 semillas | cambian unos pocos segundos, en los dos sentidos; llegan todos los vehículos |
| Recepción completa en un espacio temporal | corrida `succeeded`; QA23 con 23 movimientos y los tipos de vehículo de la demanda |

En R1, QA23 y QA24 tendrán 23 movimientos (M01 a M23), más las 3 señales de la flecha. Los giros a la izquierda de oeste a este pasan a ser M14, M16 y M17.

### Corrección: los choques no desaparecieron

La sección «Cada carril a su mismo carril» registró 0 choques con tres semillas. Con 10 semillas más, esa red tiene 12 choques en 13 corridas, unos 0,9 por corrida. El cambio sí eliminó los choques de los enlaces en diagonal (la causa 1 de «Detección de choques dentro del cruce»). Los que quedan son casi todos de la causa 2: en el carril 1 de Los Frutales de norte a sur, el que sigue recto y el que gira a la izquierda van lado a lado con los subcarriles y se rozan al separarse.

### Otras correcciones

- QA23 nombra los tipos de vehículo de la demanda (por ejemplo, «auto, camioneta») y no solo la clase de SUMO. En R0 decía «auto» también para las camionetas. Ver el acta de F8.
- Las planillas completadas salieron de la primera recepción de R0, que es equivalente a la que indica el acta de F9. Ver el acta de F8.

### Pendiente antes de R1

Los choques en Los Frutales de norte a sur (unos 1,2 por corrida; la referencia de campo es prácticamente 0) no son una limitación aceptada. El Product Owner decide cómo tratarlos.
