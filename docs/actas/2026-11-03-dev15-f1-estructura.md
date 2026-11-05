Escrito para: el Product Owner (qué se hizo y qué cambió) y el equipo técnico (reglas y verificación).

# DEV15 F1: plan vigente, estructura del cruce y regla de conteo de Webster

> **Enmienda del 2026-11-04 (auditoría A05).** Las direcciones de Frutales estaban invertidas en este documento. En el caso, la entrada del sur (`frutales_sur`, de sur a norte) solo tiene verde en t5, y la del norte (`frutales_norte`, de norte a sur) lo tiene en t5, t6 y t7. Se corrigió el texto. Las cifras no cambian: el cálculo usa los identificadores de carril.

- **Fecha:** 2026-11-03
- **Plan y decisiones:** `2026-11-03-plan-dev15.md` y `2026-11-03-dev15-f0-decisiones.md`
- **Historias:** HU08 y HU12. QA17, primera parte.
- **Datos:** pruebas con datos sintéticos (caso de demostración y casos armados a mano con la forma del caso-001). El caso-001 real se usó solo para leer.

## Qué se hizo, en simple

1. **Los parámetros de Webster se leen y se revisan.** Si algo no cuadra, por ejemplo una saturación de cero o una pérdida negativa, se rechazan. Mientras no los apruebe un especialista quedan marcados como **provisionales**.
2. **El plan vigente se lee como dato observado.** Se toma del programa publicado (cuya integridad se comprueba), con su fuente, su ciclo y su confirmación. Se revisa con las reglas del caso. Si incumple alguna, se guarda igual con las reglas incumplidas: es lo que se observó y no se corrige.
3. **La herramienta sabe en qué tramos tiene verde cada carril.** Distingue el verde con prioridad (`G`) del verde que debe ceder el paso (`g`).
4. **La regla de conteo de Webster quedó escrita y probada a mano.** Es el *camino crítico*. Con ella Webster sabe cuánto verde mínimo necesita el cruce sin contar dos veces el mismo verde.

Todavía no se calcula el ciclo de Webster: eso es F2.

## La regla de conteo (D5, `webster-solapes-v1`)

- **Grupos:** cada carril de entrada con flujo es un grupo. Su flujo es la suma de los movimientos que lo usan, en autos equivalentes (D3). Su relación de flujo es y = flujo / saturación (D2).
- **Atención:** un carril se atiende en los tramos seguidos donde alguno de sus movimientos tiene `G`. Esos tramos incluyen los fijos: por ejemplo, Javier Prado oeste→este sigue en verde en t2 mientras el otro sentido tiene ámbar.
- **Y (camino crítico):** es la mayor suma de relaciones de flujo entre carriles cuya atención no comparte ningún tramo. Es el mínimo de verde que el ciclo necesita. Si dos carriles tienen verde en el mismo tramo, ese verde los atiende a la vez y no se cuenta dos veces.
- **Webster no aplica** si un carril con flujo cumple alguna de estas condiciones:
  - nunca recibe verde;
  - solo recibe verde que cede el paso (la fórmula no sabe dimensionarlo);
  - su atención está partida en tramos no seguidos;
  - su atención cruza el fin del ciclo (esta versión no lo admite).
- **Datos faltantes:** un movimiento sin flujo en el escenario, o con flujo pero sin composición, o una clase sin equivalencia, también deja a Webster «no aplicable». **No se inventa ningún valor.**

### Simplificaciones declaradas

- La atención se mira por carril. Un giro que comparte carril con un movimiento recto cuenta con la atención de ese recto.
- El verde que cede el paso (`g`) no cuenta como capacidad.
- Un movimiento con varios carriles reparte su flujo por igual entre ellos.

Todo esto lo debe revisar el especialista (DEC08).

## Corrección de lo dicho en F0

F0 decía que Y ≈ 1,12 y que Webster probablemente no aplicaba. **No es así.** Aquella suma contaba dos veces los carriles de Javier Prado oeste→este (en t1 y en t3) y los de Frutales norte→sur (en t5 y en t7). Con la regla de conteo, para ESC-SINT-001:

| Saturación (veh/h por carril) | Y | Camino crítico |
|---|---|---|
| 1 500 | 0,823 | JP este→oeste carril 0 (t1) + JP oeste→este carril 3, la flecha (t3) + Frutales norte→sur carril 1 (t5–t7) |
| **1 800** (D2) | **0,686** | el mismo |
| 1 900 | 0,650 | el mismo |

Y queda por debajo de 1 en los tres casos, así que **Webster sigue en juego**. Ahora la aplicabilidad depende del ciclo, que se calcula en F2, y en especial del **tiempo perdido**. Con Y = 0,686:

- Con L = 24 s (D4), el ciclo de Webster sería unos **131 s**, dentro de 120 a 240 s: aplicable.
- Si el tiempo perdido se cuenta según el camino crítico, L = 19 s. En t6 Frutales norte→sur sigue en verde, así que ese tramo no se pierde para ese camino. El ciclo bajaría a unos **107 s**, fuera del rango: no aplicable.

Son cifras de anticipo para dimensionar F2; no son resultados. **D4 se revisa en F2.** Esto confirma por qué la documentación pide que el especialista valide las pérdidas.

## El caso-001 real (solo lectura)

- **Plan vigente:** 82 / 5 / 45 / 5 / 45 / 5 / 10 / 5 / 4 s, ciclo 206 s. Cumple todas las reglas del caso.
- **Carriles:**
  - 12 carriles con flujo, todos con atención en tramos seguidos.
  - 3 carriles sin flujo y sin verde (M10, M18 y M19), que no cuentan.
  - El carril 3 de Javier Prado oeste→este (la flecha) cede el paso en t1 y t2 y tiene prioridad en t3.

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/baselines.py` | `WebsterParameters` y `read_parameters`; `ObservedPlan` y `read_current_plan`; `crossing_structure`; `webster_inputs` con el camino crítico |
| `tests/unit/test_baselines.py` | 43 pruebas: parámetros, plan vigente, estructura, camino crítico calculado a mano con la forma del caso-001, y casos de no aplicable |
| `docs/actas/2026-11-03-dev15-f0-decisiones.md` | nota de corrección de Y |

## Verificación

- **Pruebas:** 43 nuevas. El camino crítico se comprueba contra cuentas a mano: 1 200/1 800 = 2/3 con la forma del caso-001, y 1 010/1 800 cuando cambia el ganador. Otra prueba comprueba que un verde compartido no se cuenta dos veces.
- **Mutaciones:** se rompió el código 30 veces a propósito.
  - Antes de empezar, se comprobó que las pruebas pasan sin daños.
  - 29 de 30 se detectaron en la primera pasada.
  - La que sobrevivió fue un carril compartido entre un movimiento con prioridad y otro que cede el paso en el mismo tramo, que se informaba también como «cede». No cambiaba la aplicabilidad, pero sí el dato informado. Se cerró con una prueba, y ahora se detectan **30 de 30**.
  - Antes del ensayo se agregaron 2 pruebas por huecos vistos al leer el código: una clase sin participación no necesita equivalencia, y un programa con tramos de otro caso se rechaza.
- **Puerta completa** (`scripts/check.ps1`): ruff, formato y pyright estricto, sin observaciones. 5001 pruebas pasan y 1 se salta, porque solo corre fuera de Windows. Contratos 43/43; ningún archivo oculto. La prueba de arquitectura confirma que `referencias` no importa `app` ni `cli`.

## Siguiente

F2: núcleo de Webster. Calcula el ciclo y el reparto del verde con casos a mano (QA17), incluidos Y ≥ 1 y datos ausentes. Ahí se revisa D4 (tiempo perdido por camino crítico o fijo de 24 s). Complejidad media-alta, esfuerzo medio, riesgo medio-alto, con Opus.
