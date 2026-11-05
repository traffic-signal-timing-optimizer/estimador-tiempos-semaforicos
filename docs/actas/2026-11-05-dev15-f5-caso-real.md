Escrito para: el Product Owner y el investigador (qué dice Webster del caso real y qué hay que decidir) y el equipo técnico (sensibilidad, control con SUMO, seguridad, mutaciones e inspección).

# DEV15 F5: comparadores del caso real, sensibilidad y control con SUMO

- **Fecha:** 2026-11-05
- **Historia y pruebas:** HU08 y HU12; QA17
- **Plan:** `2026-11-03-plan-dev15.md`, fila F5; decisión D2 de F0 (saturaciones 1 500, 1 800 y 1 900)
- **Datos:** caso-001 (de campo) con demanda **sintética**: `ESC-SINT-001` y 9 escenarios armados a partir de él. Nada de esto es un aforo.
- **Modelo:** Opus, como pedía el plan

## En simple

1. **Webster casi nunca aplica en Frutales con estos supuestos de demanda.** De 30 cálculos (10 escenarios × 3 saturaciones) aplica **uno solo**: `ESC-SINT-001` con 1 500 autos por hora y carril. En los demás no aplica, y se dice por qué, sin inventar un plan:
   - **Poca demanda:** el ciclo de Webster sale menor que los 120 s que admite el caso.
   - **Demanda media:** el ciclo cabe, pero el verde que le toca a **Frutales de norte a sur** (tramos t5, t6 y t7) es menor que los **35 s mínimos** del caso. Por ejemplo, 23,1 s.
   - **Mucha demanda con 1 500:** el ciclo pasa de los 240 s que admite el caso.
2. **El resultado depende mucho de la saturación**, que sigue provisional (DEC08, sin especialista). Con 1 800, que es el valor base, no aplica en ningún escenario.
3. **El plan de Webster que sí aplica corre en SUMO**: las 3 corridas terminan bien. Es un control de que funciona, **no una comparación**.
4. **El plan vigente** (82/45/45/10 s, ciclo 206 s) cumple las reglas del caso en todos los escenarios. No cambia con la demanda.
5. Los comparadores reales de `ESC-SINT-001` quedaron publicados en `datos/`, marcados como **evidencia sintética** y **parámetros provisionales**.

## Qué se hizo

### Código (sirve para cualquier cruce)

- `saturation_sensitivity(...)` en `referencias/comparators.py`: repite Webster de un escenario con cada saturación de la lista de sensibilidad de los parámetros. Solo cambia la saturación; una saturación repetida se calcula una vez, en orden. Rechaza un escenario o unos parámetros de otro caso, aun con la lista vacía.
- **Tope de 20 saturaciones** en los parámetros (`MAX_SENSITIVITY`). Sin tope, un archivo con miles de valores haría miles de cálculos.

### Procedimientos versionados (para no repetir lo de A06)

- `scripts/dev15_f5_aplicabilidad.py`: arma el conjunto sintético, calcula plan vigente, Webster y sensibilidad para cada escenario, y escribe `aplicabilidad.json` y `aplicabilidad.md`. Con `--publicar`, publica los comparadores de `ESC-SINT-001` en `datos/`.
- `scripts/dev15_f5_control_sumo.py`: compila el plan de Webster con 1 500, lo simula con 3 semillas y lo mide con el protocolo del piloto.
- `scripts/mutaciones/dev15_f5.py`: el ensayo de daños de esta fase.

### El conjunto de escenarios sintéticos

Es un supuesto del equipo, no un aforo. Tres familias escalan cada flujo de `ESC-SINT-001` dentro de un rango y conservan su composición. Los movimientos sin flujo (M10, M18, M19) siguen sin flujo. Son 3 variantes por familia y semilla maestra 2026.

| Familia | Factor sobre ESC-SINT-001 | Flujo total (veh/h) |
|---|---|---|
| BAJA | 0,55 a 0,70 | 3 245 a 3 464 |
| MEDIA | 0,85 a 1,00 | 4 910 a 4 937 |
| ALTA | 1,00 a 1,15 | 5 743 a 5 839 |
| `ESC-SINT-001` | 1 | 5 340 |

## Resultados

### Aplicabilidad por saturación

| Escenario | Flujo (veh/h) | 1 500 | 1 800 (base) | 1 900 |
|---|---:|---|---|---|
| `ESC-SINT-001` | 5 340 | **aplica**: C0 189,2 s, plan 108/26/25/6, ciclo 189 s | ciclo corto (106,6 s) | ciclo corto (95,6 s) |
| BAJA (3) | 3 245 a 3 464 | ciclo corto (66 a 70 s) | ciclo corto (57 a 59 s) | ciclo corto (55 a 57 s) |
| MEDIA (3) | 4 910 a 4 937 | verde de Frutales N→S bajo el mínimo (C0 127 a 147 s) | ciclo corto (87 a 94 s) | ciclo corto (80 a 86 s) |
| ALTA (3) | 5 743 a 5 839 | ciclo largo (290 a 328 s) | verde de Frutales N→S bajo el mínimo (C0 127 a 133 s) | ciclo corto (111 a 115 s) |

| Saturación | Aplica | No aplica |
|---:|---:|---:|
| 1 500 | 1 | 9 |
| 1 800 | 0 | 10 |
| 1 900 | 0 | 10 |

El tiempo perdido (L) fue de 19 s en todos los casos. «Ciclo corto» y «ciclo largo» son el motivo `cycle_out_of_bounds`; «verde bajo el mínimo» es `path_green_too_short`.

`ESC-SINT-001` reproduce las cifras de F3 y de la auditoría (Y de 0,823, 0,686 y 0,650).

### Control con SUMO del plan de Webster (1 500, `ESC-SINT-001`)

Plan 108/5/26/5/25/5/6/5/4 s, ciclo 189 s. Se midió con el protocolo del piloto de DEV14 (SUMO 1.27.1). Al lado va, solo como contexto, lo que midió el piloto con el plan vigente y las mismas semillas.

| Semilla | Webster: estado | Webster: demora (s/veh) | Webster: problemas | Plan vigente en el piloto |
|---:|---|---:|---|---|
| 1001 | terminó bien | — | 1 teletransporte, 1 choque | 10 teletransportes |
| 1002 | terminó bien | 57,9 | ninguno | 110,9 s/veh, limpia |
| 1003 | terminó bien | — | 1 teletransporte | 96,8 s/veh, limpia |

**Lo que esto dice:** el plan de Webster corre. **Lo que no dice:** que sea mejor ni peor.
- Son 3 semillas y solo 1 limpia. Los choques de este caso cambian mucho de una semilla a otra: hacen falta 13, como en el piloto.
- La saturación de 1 500 es provisional.
- La demanda es supuesta.
- Con la regla estricta del piloto (DEC06), este plan no sería elegible.

Comparar de verdad es trabajo de DEV20.

### Comparadores publicados

`datos/derivados/comparadores/caso-001/20261105T141416Z_24543b7d/`, de solo lectura:
- Plan vigente: cumple.
- Webster con 1 800: no aplica (ciclo corto).
- Parámetros `webster-parametros-v2`: provisionales.
- Origen: caso de campo, demanda sintética, **evidencia sintética**.

`runs verify` sobre `datos/` da 291 íntegras (una más que antes), 0 alteradas y las mismas 3 antiguas sin formato reconocido.

El conjunto sintético, sus 9 comparadores, el informe y el control con SUMO quedaron fuera del repositorio y de `datos/`, en `D:\UPC\2026_01\Proyecto_de_investigacion_1\desarrollo\replicas-piloto\` (`dev15-f5-aplicabilidad` y `dev15-f5-control-sumo`). `runs verify` sobre esa carpeta da 10 íntegras.

## Seguridad

`tests/security/test_dev15.py`, 29 pruebas. Pasan todas en este equipo, incluidas las de enlaces simbólicos.

- **Parámetros hostiles:** saturación NaN, infinita, negativa, cero, booleana o como texto; sensibilidad con NaN, negativa o con 10 000 valores; equivalencias negativas o infinitas; «aprobado» sin especialista; otra regla de pérdidas; aplicabilidad incompleta; campos desconocidos. Todos se rechazan con un error de dominio y un mensaje corto.
- Un nombre de caso de un millón de caracteres da un mensaje corto.
- Un archivo de parámetros sobre el límite se rechaza antes de leerlo. Un archivo que no es un objeto se rechaza, y un enlace no se sigue.
- Un programa vigente cambiado después de publicarse se nota por su huella.
- **Comparadores publicados:** un archivo anidado 100 000 niveles o que no es JSON se rechaza sin que el programa caiga. Un manifiesto que nombra archivos fuera de la carpeta se rechaza. Un enlace dentro de la carpeta, o la carpeta como enlace, no se sigue. Los archivos publicados quedan de solo lectura.

## Mutaciones

`scripts/mutaciones/dev15_f5.py`: 11 daños sobre la sensibilidad y su tope (orden, repetidas, primera saturación, saturación sin cambiar, fila mal rotulada, escenario o parámetros de otro caso, tope corrido o quitado).

- Primera pasada: 10 daños y 1 sobrevivió. La regla de «parámetros de otro caso» ya la cubre Webster por dentro, salvo con la lista vacía.
- Se agregaron las pruebas con lista vacía y el daño del escenario. Resultado final: **11 de 11 detectados.**

## Inspección contra la documentación y el caso real

| Qué pide | Dónde | Estado |
|---|---|---|
| Cargar el plan observado con su fuente | DEV15 (doc 02) | Cumplido (F1 y F4); confirmado por el PO |
| Webster con grupos críticos, dominio y traducción validada | DEV15 | Cumplido con `webster-solapes-v1`; **la traducción está revisada por el equipo, no por un especialista** |
| No aplicable sin inventar valores | DEV15, HU12 | Cumplido: 29 de 30 cálculos no aplican y ninguno se recorta ni se reemplaza |
| QA17: cálculo a mano, Y ≥ 1 y datos ausentes | doc 03 | Cubierto en F2 y F3; F5 agrega la sensibilidad |
| Aprobación de especialista para el caso | DEV15 | **Pendiente (DEC08)**: no hay especialista |
| Una cifra sintética nunca como de campo | A03 | Cumplido en los comparadores publicados |
| Nada de Frutales en el código | visión del proyecto | Cumplido en lo nuevo. Los guiones `scripts/dev15_f5_*` nombran el caso, como `piloto_dev14.py` |
| Sensibilidad con 1 200 | plan DEV15, D2 | **No se hizo:** la decisión D2 de F0 fijó 1 500, 1 800 y 1 900. Se puede agregar a la lista de los parámetros |

**Hallazgo para decidir (DEC08 y DEV20):** con los parámetros base, Webster no aplica en ningún escenario del caso. En DEV20, Webster aparecerá como «no aplicable» casi siempre, y eso se informa: no se reemplaza (HU12). Lo que más lo cambia es la saturación. Medirla en SUMO o con un especialista podría cambiar la conclusión.

## Verificación

- **Pruebas:** 38 nuevas: 9 de la sensibilidad y 29 de seguridad.
- **Mutaciones de F5:** 11 de 11 detectadas, tras cerrar 1 sobreviviente.
- **Caso real:** los 10 escenarios calculados; los comparadores publicados se leen íntegros; `runs verify` da 291 íntegras en `datos/` y 10 en la carpeta de trabajo.
- **Control con SUMO:** 3 de 3 corridas terminaron bien.
- **Puerta completa** (`scripts/check.ps1`): ruff, formato y pyright estricto, sin observaciones. **5181 pruebas pasan y 1 se salta** (solo corre fuera de Windows; antes 5143). Contratos 43/43; ningún archivo oculto; ruff 0.17.1 en ambos lados.

## Archivos

| Archivo | Contenido |
|---|---|
| `src/semaforo/referencias/comparators.py` | `SensitivityRow`, `saturation_sensitivity` |
| `src/semaforo/referencias/baselines.py` | `MAX_SENSITIVITY` = 20 |
| `scripts/dev15_f5_aplicabilidad.py` | informe de aplicabilidad y publicación |
| `scripts/dev15_f5_control_sumo.py` | control con SUMO del plan de Webster |
| `scripts/mutaciones/dev15_f5.py` | ensayo de daños de F5 |
| `tests/unit/test_comparators.py` | 9 pruebas de la sensibilidad |
| `tests/security/test_dev15.py` | 29 pruebas de seguridad |

## Siguiente

**F6: cierre de DEV15** (acta de cierre, `CONTEXTO.md` y commit). Complejidad baja; Haiku alcanza.
