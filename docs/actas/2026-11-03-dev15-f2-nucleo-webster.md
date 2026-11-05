Escrito para: el Product Owner (qué sale de Webster en Frutales) y el equipo técnico (reglas, cálculo y verificación).

# DEV15 F2: núcleo de Webster (ciclo y verdes)

> **Enmienda del 2026-11-04 (auditoría A05).** Las direcciones de Frutales estaban invertidas en este documento. En el caso, la entrada del sur (`frutales_sur`, de sur a norte) solo tiene verde en t5, y la del norte (`frutales_norte`, de norte a sur) lo tiene en t5, t6 y t7. Se corrigió el texto. Las cifras no cambian: el cálculo usa los identificadores de carril.

- **Fecha:** 2026-11-03
- **Plan y decisiones:** `2026-11-03-plan-dev15.md`, `2026-11-03-dev15-f0-decisiones.md` y `2026-11-03-dev15-f1-estructura.md`
- **Historias:** HU08 y HU12. QA17 (cálculo a mano y no aplicables).
- **Datos:** pruebas con datos sintéticos; el caso-001 real solo se leyó.

## Qué se hizo, en simple

La herramienta ya calcula, para un escenario, **el ciclo que recomienda Webster y el verde que necesita cada carril**. Si la receta no sirve, lo dice con el motivo:

- si falta un dato;
- si el cruce está saturado (Y llega a 1);
- si no hay demanda;
- si el ciclo que da queda fuera de lo que admite el caso (120 a 240 s en Frutales).

En ningún caso inventa ni recorta un número.

Todavía no convierte esos verdes en un plan de tramos t1 a t9: eso es F3.

## Decisiones de F2

**F2-1. La regla de conteo queda completa (D5).** Webster calcula el ciclo con un par de cifras de un *recorrido* del ciclo: la suma de relaciones de flujo (Y) y el tiempo perdido (L). Se fija:

- Un recorrido pasa por **todos** los tramos. Cada tramo variable lo atiende uno de sus carriles. Cada tramo fijo lo atiende uno de ellos o se pierde.
- Manda el recorrido que **exige el ciclo más largo**, C0 = (1,5 L + 5) / (1 − Y). No basta el de mayor Y: un recorrido con algo menos de Y pero más tiempo perdido puede pedir más ciclo. Hay una prueba para ese caso.
- En F1 la regla elegía el de mayor Y. En Frutales da el mismo recorrido; en otros cruces podría no darlo.

**F2-2. El tiempo perdido sale del recorrido, no es fijo (revisa D4).**
- L es la suma de los tramos fijos (ámbares y todo rojo) que ningún carril del recorrido usa en verde.
- En Frutales, t2 y t6 son ámbar para un sentido, pero el otro sigue en verde. En el recorrido crítico, t6 es verde para Frutales norte→sur, así que no se pierde.
- Resultado: **L = 19 s** (t2, t4, t8 y t9), y no los 24 s fijos de F0.
- Contar t6 como perdido sería contar como perdido un verde que se usa.
- Lo debe confirmar el especialista.

**F2-3. Los límites del ciclo salen del caso.** El archivo de parámetros ya no los repite, para que no haya dos fuentes del mismo dato.

**F2-4. Reparto del verde.** El verde efectivo (C0 − L) se reparte en proporción a la relación de flujo de cada carril, de modo que todos los carriles del recorrido crítico quedan con el mismo grado de saturación. Se informa el verde que pide cada carril con flujo, también los que no están en el recorrido crítico, para que F3 compruebe que el plan los atiende.

**F2-5. Parámetros v2.** `configs/webster/parametros-v2.json` reemplaza a `v1`:
- sale el L fijo de 24 s y entra la regla `intergreens_outside_critical_path`;
- salen los límites del ciclo, que se toman del caso;
- el límite de Y (`y_must_be_below`) no puede pasar de 1.

El resto queda igual: 1 800 veh/h por carril, las equivalencias, el plan vigente y el estado provisional sin especialista. `v1` queda en el historial de git.

## Resultado para Frutales (ESC-SINT-001, solo lectura)

| Saturación (veh/h por carril) | Y | L | Ciclo de Webster | Estado |
|---|---|---|---|---|
| 1 500 | 0,823 | 19 s | **189,2 s** | aplicable |
| **1 800** (D2) | 0,686 | 19 s | **106,6 s** | **no aplicable**: por debajo del mínimo de 120 s |
| 1 900 | 0,650 | 19 s | **95,6 s** | no aplicable: por debajo del mínimo |

En los tres casos manda el mismo recorrido crítico:
- Javier Prado este→oeste, carril 0 (t1);
- Javier Prado oeste→este, carril 3, la flecha (t3);
- Frutales norte→sur, carril 1 (t5 a t7).

**Lectura:**

- Con la saturación elegida, Webster recomienda un ciclo de unos 107 s, más corto que el mínimo del caso. Según D6 queda **«no aplicable»**, con la cifra a la vista. Ese resultado es válido y se reporta tal cual (HU12).
- Con una saturación de 1 500, Webster daría unos 189 s y un plan posible: es muy sensible a ese dato, que hoy es un supuesto. Por eso es importante la tabla de sensibilidad de F5 y que el especialista valide la saturación.
- Como referencia, el mejor plan del piloto de DEV14 tenía un ciclo de 176 s.

## Casos calculados a mano (QA17)

| Caso | Cuenta | Comprobado |
|---|---|---|
| Fórmula sola | (1,5 × 10 + 5) / (1 − 0,5) = 40 s | igual, exacto |
| Dos fases (demostración), y = 0,4 y 0,3 | L = 8; C0 = 17 / 0,3 = 56,667 s; verdes de 27,810 y 20,857 s | igual |
| Forma del caso-001, límites 60 a 240 s | Y = 2/3, L = 19, C0 = 100,5 s; verdes y × 122,25 s | igual; los del recorrido crítico suman C0 − L |
| La misma forma, límites 120 a 240 s | C0 = 100,5 s fuera de rango | «no aplicable», con la cifra y sin recorte |
| Recorrido con menos Y y más pérdida | 36,4 s frente a 10 s | gana el que exige más ciclo |
| Y = 1 | saturado | «no aplicable» |
| Límite de Y = 0,6 con Y = 0,7 | saturado según los parámetros | «no aplicable» |
| Sin demanda (Y = 0) | sin ciclo | «no aplicable» |
| Un tramo variable sin carril | ningún recorrido cubre el ciclo | «no aplicable» |
| Falta un flujo | dato ausente | «no aplicable», sin ciclo |

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/baselines.py` | Recorridos que cubren el ciclo y frontera de Pareto (Y y L); `webster_cycle`; `webster_timing` con ciclo, verdes y límites del caso |
| `configs/webster/parametros-v2.json` | Parámetros v2 (reemplaza a v1) |
| `tests/unit/test_baselines.py` | 54 pruebas (12 nuevas y las de F1 ajustadas a tramos fijos y a v2) |

## Verificación

- **Pruebas:** 54 pasan.
- **Mutaciones:** 42 daños a propósito: las 22 de F1 que siguen valiendo y 20 nuevas de F2.
  - Antes de empezar, se comprobó que las pruebas pasan sin daños.
  - En la primera pasada se detectaron 40 de 42.
  - **«Sin tope de ciclo»** era un hueco real: ninguna prueba tenía un ciclo por encima del máximo. Se cerró con una prueba (Y = 0,9 y C0 = 170 s con un máximo de 100), y ahora se detecta.
  - **«Sin Pareto»** (no podar los recorridos) es equivalente: el resultado no cambia, porque igual se elige el máximo. La poda solo evita que el cálculo crezca sin control en cruces más grandes. No se detecta por diseño.
  - Resultado: 41 de 42 detectadas y 1 equivalente.
- **Puerta completa** (`scripts/check.ps1`): ruff, formato y pyright estricto, sin observaciones. 5012 pruebas pasan y 1 se salta, porque solo corre fuera de Windows. Contratos 43/43; ningún archivo oculto.

## Siguiente

F3: traducir los verdes a un plan de tramos. Lleva los ticks de 1 s y los límites de cada tramo, y la comprobación con las reglas del caso (DEV13), sin corrección silenciosa. Con la saturación de 1 800, Frutales ya sale «no aplicable» antes de F3, así que la traducción se probará con casos sintéticos y con la sensibilidad de 1 500. Complejidad alta, riesgo alto, con Opus.
