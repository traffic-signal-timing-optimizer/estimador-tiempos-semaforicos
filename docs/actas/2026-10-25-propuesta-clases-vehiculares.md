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

1. El Product Owner revisa la propuesta en SUMO-GUI y, si la acepta, copia los dos archivos a su carpeta, junto con los cambios de red que salieron de QA23.
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
