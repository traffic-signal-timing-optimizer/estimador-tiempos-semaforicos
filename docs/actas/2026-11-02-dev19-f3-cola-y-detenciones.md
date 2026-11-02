# Acta 2026-11-02: DEV19 · F3 (FCD, cola y detenciones en la zona)

- **Tipo:** fase F3 de DEV19 (HU13; QA27). Seguida de F2, por pedido del Product Owner.
- **Decisiones que aplica:** D9, D10, D11 y D16 de `2026-11-02-dev19-f0-decisiones.md`.
- **Modelo:** Opus.
- **Datos:** sintéticos; trayectorias escritas a mano. Además, una lectura de prueba de la copia temporal del caso real medida en F0.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `caso/xml_input.py` | `stream_parse`: la lectura en flujo con tope, también en `.gz`, que antes estaba solo en `tripinfo.py`. Ahora la usan el `tripinfo` y la FCD (sin duplicar código) |
| `evaluacion/fcd.py` | Lee la FCD paso por paso y entrega cada paso a quien mide: la memoria no crece con el archivo. Exige raíz `<fcd-export>`, pasos en orden creciente y cada vehículo con `id`, `lane` y `speed` finita y no negativa, una sola vez por paso. Ignora personas y contenedores |
| `evaluacion/metrics.py` | Cola y detenciones, en total y por acceso, con los parámetros del protocolo |

## Definiciones (las del protocolo)

- **Cola:** en cada tick de muestreo dentro del intervalo de medición [inicio, fin) de la cohorte, los vehículos en los carriles de la zona con velocidad ≤ 0.1 m/s. Cuentan todos, también los de calentamiento. Se informa la media en el tiempo (veh), el máximo (veh) y la suma (veh·tick), en total y por acceso.
- **Ceros incluidos:** un tick sin vehículos cuenta 0, y un acceso sin cola aparece con 0.
- **Ticks que faltan:** no se rellenan. La cobertura baja y la cola queda `incomplete`, sin valores.
- **Detención:** de un vehículo de la cohorte, en la zona, en toda la corrida: paso de > 0.1 a ≤ 0.1 m/s entre dos pasos seguidos. Un vehículo que **aparece** detenido en la zona cuenta una detención (regla del estado inicial). Si sale de la zona y vuelve detenido, cuenta otra.
- **Detenciones por vehículo** = total / N solicitados del grupo. Es la media si el grupo terminó y una **cota inferior** si está censurado.
- Los umbrales de cola y de detención son independientes, y el muestreo debe ser un múltiplo entero del paso.
- **Carriles:** los internos del cruce y los que no son de la zona no cuentan. Cada vehículo está en un solo carril por paso, así que nadie se cuenta dos veces.

## QA27 punto por punto

| QA27 pide | Cómo se cumple |
|---|---|
| Trayectorias cortas con velocidad conocida | Cuatro ticks con tres vehículos y velocidades escritas a mano |
| Dos accesos y cola cero | Acceso N con cola 0, 1, 2, 1 (suma 4, media 1, máximo 2); acceso E sin cola (0 en todo) |
| Detenciones | «a» frena y se detiene: 1; «b» aparece detenido: 1; «c» no se detiene: 0. Total 2 de 3 pedidos (0.667 por vehículo) |
| Cobertura | 4 de 4 ticks (100 %). Con un tick menos, 75 % y la cola queda sin valores |
| Unidades coinciden con el cálculo manual | Vehículos, vehículos por tick, s y m/s. Los parámetros usados quedan en `settings` |
| Ceros incluidos | El acceso sin cola da 0, no queda vacío |
| MAE | El MAE (I5) es de los planes, no de la simulación: va en F4 |

## Prueba con el caso real (copia temporal, solo lectura)

Con la corrida de F0 (1780 vehículos, 1338 de cohorte, semilla 100) y un protocolo de prueba con los carriles de entrada del caso:

| Medida | Resultado |
|---|---|
| Demora de la cohorte | Completa: 1338 de 1338 terminaron. Media 100.7 s (100.4 s en ruta y 0.24 s esperando para entrar) |
| Cola en la zona | 900 de 900 ticks (cobertura 100 %); media 14.2 veh, máximo 31 |
| Detenciones | 291 en total, 0.22 por vehículo |
| Acceso con más cola | `1183810724#2`: media 8.8 veh y máximo 27 |

Son cifras sintéticas, de una sola semilla y con un protocolo de prueba. Sirven para comprobar que todo funciona de punta a punta, no como resultados del caso. La corrida formal del caso se hace en F5.

## Verificación

| Qué | Resultado |
|---|---|
| Pruebas nuevas | **45** (QA27, bordes de las definiciones, cobertura y censura, 17 FCD rotas u hostiles, tope también en `.gz`) |
| Suite completa | **4685 pasan, 1 se salta**. Formato, lint, tipos estrictos y reglas de capas sin observaciones |
| Mutaciones | **35**. 29 detectadas a la primera. 3 huecos reales cerrados con pruebas: el máximo total con cola en dos accesos a la vez, un elemento extraño con `time` y la cuenta de ticks con decimales (0.3 / 0.1 da 3.0000000000000004 en binario). 2 mostraron código de más, que se simplificó. 1 es equivalente: con la cola completa, los ticks observados son los esperados |

## Límites

- La zona es la calle de entrada declarada en el caso; la cola que llega a la calle anterior no se ve (DEC04).
- La cola es «operativa» (vehículos a ≤ 0.1 m/s). Su equivalencia con la medición manual se comprueba en campo (documento 03).
- Las detenciones cuentan solo dentro de la zona: una detención antes de llegar a ella no se ve.
