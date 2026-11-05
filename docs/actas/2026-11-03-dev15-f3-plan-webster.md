Escrito para: el Product Owner (qué plan da Webster en Frutales) y el equipo técnico (regla de traducción y verificación).

# DEV15 F3: los verdes de Webster como plan de tramos

> **Enmienda del 2026-11-04 (auditoría A05).** Las direcciones de Frutales estaban invertidas en este documento. En el caso, la entrada del sur (`frutales_sur`, de sur a norte) solo tiene verde en t5, y la del norte (`frutales_norte`, de norte a sur) lo tiene en t5, t6 y t7. Se corrigió el texto. Las cifras no cambian: el cálculo usa los identificadores de carril.

- **Fecha:** 2026-11-03
- **Plan y decisiones:** `2026-11-03-plan-dev15.md`, actas de F0 a F2 de DEV15
- **Historias:** HU08 y HU12. QA17, parte de la traducción.
- **Datos:** pruebas con datos sintéticos; el caso-001 real solo se leyó.

## Qué se hizo, en simple

F2 calculaba cuánto verde necesita cada carril. F3 convierte eso en un **plan de semáforo de verdad**, con la duración de cada tramo t1 a t9 en segundos enteros.

Después el plan se revisa con las mismas reglas del caso que usan la búsqueda y el modelo (DEV13). Si el plan no cabe en esas reglas, el resultado es «no aplicable» con el motivo. **Nunca se corrige en silencio**: subir o bajar un tramo para que cumpla ya no sería Webster.

## La regla de traducción (`webster-solapes-v1`)

1. **Tramos fijos** (ámbares y todo rojo): quedan como están.
2. **Carril del recorrido crítico con un solo tramo variable**, como Javier Prado este→oeste en t1: ese tramo recibe el verde de Webster del carril, menos los fijos que tenga dentro.
3. **Carril del recorrido crítico con varios tramos variables**, como Frutales norte→sur en t5, t6 (fijo) y t7:
   - cada tramo parte de su mínimo, o de lo que pida un carril que se atiende solo dentro de él (Frutales sur→norte, que solo tiene verde en t5);
   - lo que sobra va al tramo que atienden menos carriles (t7). Si empatan, va al último.
4. **Carriles fuera del recorrido crítico**, como Javier Prado oeste→este en t1, t2 y t3: se comprueba que el plan les dé el verde que piden. Si no se lo da, no aplica.
5. **Redondeo:** cada tramo variable se lleva al tick de 1 s más cercano (la mitad, hacia arriba). El ciclo del plan puede diferir en algunos décimos del ciclo de Webster; se informan los dos.
6. **Revisión:** el plan redondeado pasa por `check_plan`, que comprueba el ciclo, los límites de cada tramo y de cada grupo de verde, y el resto de las reglas del caso. Si incumple alguna, no aplica, y se informan las reglas incumplidas con el plan propuesto.

### Motivos nuevos de «no aplicable»

| Código | Cuándo |
|---|---|
| `path_green_too_short` | el verde de Webster de un carril crítico no alcanza para el mínimo de sus tramos (por ejemplo, la flecha pide 12,9 s y su tramo exige 15 s) |
| `lane_not_served` | un carril que no está en el recorrido crítico recibe menos verde del que Webster le pide |
| `path_without_variable_slot` | un carril crítico solo tiene tramos fijos y su verde no se puede ajustar |
| `plan_infeasible` | el plan redondeado incumple una regla del caso |

### Limitación declarada

El sobrante de un carril crítico va al tramo que atienden menos carriles. No se busca otro reparto que atienda mejor a un carril que comparte solo una parte de esos tramos. Si eso deja a un carril sin su verde, el resultado es «no aplicable» (hay una prueba para ese caso). Es una regla simple y predecible, y la debe revisar el especialista (DEC08).

## Resultado para Frutales (ESC-SINT-001, solo lectura)

| Saturación (veh/h por carril) | Ciclo de Webster | Plan | Estado |
|---|---|---|---|
| 1 500 | 189,2 s | t1 108, t3 26, t5 25, t7 6 (fijos 24): **189 s** | **aplicable**: cumple todas las reglas del caso |
| **1 800** (D2) | 106,6 s | — | no aplicable: ciclo por debajo de 120 s |
| 1 900 | 95,6 s | — | no aplicable: ciclo por debajo de 120 s |

**Lectura:**

- Con la saturación elegida, Webster sigue fuera para Frutales (ya lo dijo F2).
- Con 1 500, sí da un plan válido, y se parece al vigente en dónde pone el tiempo: mucho verde para Javier Prado (t1 de 108 s frente a los 82 s vigentes) y Frutales cerca de sus mínimos.
- En t5 quedan 25 s, el mínimo del tramo: Webster pedía menos para Frutales sur→norte. El sobrante de Frutales norte→sur fue a t7, como dice la regla.
- No se compara con medidas de SUMO: eso es F5 (control) y DEV20 (comparación).

## Casos calculados a mano

| Caso | Cuenta | Comprobado |
|---|---|---|
| Dos fases (demostración) | 27,810 → 28 y 20,857 → 21; ciclo 57 s (Webster: 56,667 s) | igual |
| Forma del caso-001 | t1 = 50,94 → 51; t3 = 12,90 → 13; t5 = 6,79 → 7 (lo que pide S); t7 = 12,66 − 6,79 = 5,87 → 6; ciclo 101 s | igual |
| Flecha con mínimo de 15 s | pide 12,9 s | `path_green_too_short`, sin plan |
| Carril que comparte solo un tramo | recibe 3,08 s y pide 6,25 s | `lane_not_served` |
| Grupo NS con tope de 25 s | el plan pide 28 s | `plan_infeasible`, con el plan y la regla incumplida |
| Carril crítico solo en un tramo fijo | verde no ajustable | `path_without_variable_slot` |
| Ciclo de Webster fuera de rango | 100,5 s con mínimo de 120 | sigue como `cycle_out_of_bounds`, sin plan |

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/baselines.py` | `WebsterPlan` y `webster_plan`; el cálculo de F2 pasa a fracciones exactas internas para que la traducción no arrastre redondeos |
| `tests/unit/test_baselines.py` | 64 pruebas (10 nuevas de F3) |

## Verificación

- **Pruebas:** 64 pasan.
- **Mutaciones de F3:** se dañó el código 18 veces a propósito.
  - Antes de empezar, se comprobó que las pruebas pasan sin daños.
  - En la primera pasada se detectaron 15 de 17.
  - Las 2 que sobrevivieron eran reglas de reparto sin prueba propia:
    - lo que pide un carril interno va al *primer* tramo de su atención;
    - si los tramos empatan, el sobrante va al *último*.
  - Se cerraron con 2 pruebas calculadas a mano, y ahora se detectan las 17.
  - Una más, el reparto del verde «sin dividir por Y», se rehízo sobre el código nuevo y también se detecta.
  - Resultado: 18 de 18.
- **Mutaciones de F2 de nuevo:** se repitieron después del cambio a fracciones exactas. Se detectan 40 de 41; la restante es la equivalente ya conocida (la poda de Pareto).
- **Puerta completa** (`scripts/check.ps1`): ruff, formato y pyright estricto, sin observaciones. 5022 pruebas pasan y 1 se salta, porque solo corre fuera de Windows. Contratos 43/43; ningún archivo oculto.

## Siguiente

F4: publicar los comparadores en `datos/derivados/comparadores/<caso>/<fecha>_<huella>/`, con manifiesto, solo lectura y `runs verify`. Además, que Webster (si es aplicable y factible) y el plan vigente entren a la búsqueda de DEV14 como candidatos auxiliares. Complejidad media, riesgo medio (toca código cerrado de DEV14), con Sonnet.
