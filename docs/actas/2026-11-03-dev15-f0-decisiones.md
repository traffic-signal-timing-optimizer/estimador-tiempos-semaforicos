Escrito para: el Product Owner (qué se decidió y qué cambió) y el equipo técnico (valores para F1 a F6).

# DEV15 F0: decisiones de los comparadores

> **Enmienda del 2026-11-04 (auditoría A05).** Las direcciones de Frutales estaban invertidas en este documento. En el caso, la entrada del sur (`frutales_sur`, de sur a norte) solo tiene verde en t5, y la del norte (`frutales_norte`, de norte a sur) lo tiene en t5, t6 y t7. Se corrigió el texto. Las cifras no cambian: el cálculo usa los identificadores de carril.

> **Enmienda del 2026-11-05 (cierre de DEV15, F6).** Tres puntos de este acta cambiaron después y reemplazan lo que dice arriba: **D4** (L = 24 s) lo reemplazó F2-2 por **L = 19 s**, la pérdida de los tramos fijos que ningún recorrido crítico usa en verde; **los parámetros** `parametros-v1.json` pasaron a `parametros-v2.json` (F2-5); y la sensibilidad de **D2** se hizo con 1 500, 1 800 y 1 900, sin el 1 200 que mencionaba el plan. Detalle en `2026-11-03-dev15-f2-nucleo-webster.md` y en `2026-11-05-dev15-cierre.md`.

- **Fecha:** 2026-11-03
- **Plan:** `docs/actas/2026-11-03-plan-dev15.md`
- **Delegación:** el Product Owner pidió que las decisiones D1 a D8 las tome el equipo técnico, y respondió dos preguntas (abajo).
- **Parámetros:** `configs/webster/parametros-v1.json` (versión `webster-parametros-v1`, estado provisional).
- **Estado:** decidido. Este acta reemplaza las propuestas D1 a D8 del plan donde difieren.

## Respuestas del Product Owner

1. **¿El semáforo real cambia de plan por hora o por día?** No. Es siempre el mismo, de 206 s. **Cambia la decisión D7:** no hay variantes horarias que registrar.
2. **¿Quién es el especialista de tránsito y cuándo puede revisar los parámetros?** Todavía no hay especialista. **DEC08 queda abierta**, y el resultado de DEV15 se marca provisional hasta que alguien la cierre. No bloquea el avance.

## Corrección de un cálculo anterior

En el plan dije que, con valores típicos, el ciclo de Webster saldría cerca de 93 s. **Esa cifra no es válida.** La saqué sumando flujos sin separar las fases ni tomar el carril crítico de cada una.

Lo recalculé con el flujo del carril más cargado en cada tramo variable del escenario ESC-SINT-001 y saturación de 1 800 veh/h por carril:

| Tramo | Carril crítico (veh/h) | y |
|---|---|---|
| t1 (Javier Prado, este→oeste y oeste→este recto) | 750 | 0,417 |
| t3 (Javier Prado, oeste→este) | 750 | 0,417 |
| t5 (Frutales, los dos sentidos) | 260 | 0,144 |
| t7 (Frutales, norte→sur) | 260 | 0,144 |
| **Suma** | | **Y ≈ 1,12** |

**Lectura:** Y está por encima de 1. Webster no es aplicable para este escenario con esta saturación. Hay un problema de conteo: los carriles de Javier Prado aparecen en t1 y en t3, así que se cuentan dos veces. Si cada acceso se cuenta una sola vez, Y ≈ 0,98. Aun así queda al límite. **En ambas cuentas, Webster sale no aplicable o en el borde.**

Consecuencia: la regla de F1 para contar las fases (qué se cuenta una vez y qué no) decide la aplicabilidad. Por eso se fija en F1 antes de calcular nada.

> **Corrección hecha en F1 (2026-11-03).** La suma por tramo de esta tabla cuenta dos veces los carriles que siguen en verde de un tramo al siguiente. Con la regla de F1, el camino crítico, **Y = 0,686** para ESC-SINT-001 con 1 800 veh/h por carril y las equivalencias de D3 (0,823 con 1 500; 0,650 con 1 900). Y queda por debajo de 1, así que Webster **no** queda descartado por Y. Las frases de D2 y D6 que dicen lo contrario quedan reemplazadas. La aplicabilidad depende ahora del tiempo perdido, que se decide en F2. Detalle en `2026-11-03-dev15-f1-estructura.md`.

## Decisiones

**D1. Validación del especialista (DEC08).** Abierta, sin especialista asignado. Todo el resultado de DEV15 lleva la marca `provisional` y la comparación del caso no se presenta como definitiva hasta que el especialista revise. La marca va en `parametros-v1.json` y en cada comparador publicado.

**D2. Flujo de saturación: 1 800 veh/h por carril**, en `parametros-v1.json`. Se hará una tabla de sensibilidad con 1 500, 1 800 y 1 900 en F5. Con 1 900, Y sigue por encima de 1, así que la conclusión de no aplicabilidad no cambia dentro de ese rango.

**D3. Equivalencia de vehículos:** auto 1,0; moto 0,5; camión 2,0; bus 2,0. Provisional. Se aplica al flujo por carril antes de calcular Y.

**D4. Tiempo perdido L = 24 s**, la suma de los tiempos fijos del caso (cuatro ámbares de 5 s y un todo rojo de 4 s). Provisional y pendiente del especialista. Esta es la pérdida que se usa en la fórmula.

**D5. Fases con solape: adaptación `webster-solapes-v1`.** Javier Prado y Frutales tienen verdes que se solapan en varios tramos, y Webster clásico no define el reparto en ese caso. La adaptación se identifica con su propio nombre y versión, y no se llama Webster puro. **Regla de conteo (nueva):** cada grupo de carriles que comparte verde en un tramo cuenta una vez. Esta regla es la que decide Y, así que se escribe en F1 con su prueba antes de usarla.

**D6. Fuera de dominio = «no aplicable».** Si Y ≥ 1, o si el ciclo calculado queda fuera de 120 a 240 s, o un verde queda fuera de los límites de su tramo, el resultado es «no aplicable» con el motivo. **No se recorta ni se corrige.** Con los datos actuales es probable que Webster salga no aplicable para ESC-SINT-001: eso es un resultado válido y hay que reportarlo como tal.

**D7. Plan vigente como dato observado.** Se registra con su fuente (el programa del semáforo de la simulación original, `datos/derivados/programas/caso-001/20261031T041338Z_63437585`), con ciclo 206 s, plan fijo todo el día y confirmado por el Product Owner el 2026-11-03. **No hay variantes horarias.**

**D8. Dónde se guarda y cómo entra a la búsqueda.**
- Los comparadores se publican en `datos/derivados/comparadores/<caso>/<fecha>_<huella>/`, de solo lectura, con manifiesto y revisados por `runs verify`.
- El plan vigente y Webster, si es aplicable y factible, entran a la búsqueda de DEV14 como candidatos auxiliares que no consumen el presupuesto B.
- Un Webster no aplicable no entra como candidato. Se registra el motivo.

## Qué se toca en F1

- Estructura del cruce para Webster: qué movimientos tienen verde en cada tramo y qué carril manda en cada grupo.
- Regla de conteo de D5, con su prueba a mano.
- Modelo de aplicabilidad: «aplicable» o «no aplicable» con motivo.
- El plan vigente como dato observado, con su fuente y fecha.

## Lo que no se hace aquí

- Ningún código. Este acta fija valores y reglas.
- Sensibilidad (F5), publicación (F4) y calibración con SUMO.
- Un «Webster ajustado» como quinta referencia. Solo se agregaría si el investigador lo pide.

## Siguiente

F1, con modelo Opus según el plan, porque la regla de conteo de D5 decide la aplicabilidad.
