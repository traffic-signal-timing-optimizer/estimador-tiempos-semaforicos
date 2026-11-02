# Acta 2026-11-02: DEV12 · F1 (asignación de familias completas y reglas de la partición)

- **Tipo:** fase F1 de DEV12 (HU07). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D2 a D7 de F0.
- **Datos:** sintéticos.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/dominio/split.py` | Modelo estricto del contrato `split` v1.0 (`Split`, `Assignment`), la política de proporciones (`SplitPolicy`, `Proportions`), `parse_split`, `parse_policy`, `accept_split`, `split_issues` y `SplitInvalidError` |
| `src/semaforo/aprendizaje/splits.py` | `partition_counts`, `assign_groups`, `create_split` y la política provisional (`PROVISIONAL_POLICY`) |
| `src/semaforo/dominio/scenario_spec.py` | Exporta `SafeId` para validar el nombre de la política |
| `tests/unit/test_split.py`, `tests/unit/test_splits.py` | 139 pruebas |
| `tests/scenario_tools.py` | `families_spec` y `scenarios_of`, para armar conjuntos con varias familias |

El modelo coincide con `schemas/split.schema.json` (una prueba compara la estructura del modelo con el contrato publicado); el contrato no cambió.

## Reglas

| Regla | Qué comprueba |
|---|---|
| SPLIT-S01 / S02 | Contrato completo, sin campos desconocidos, tipos exactos; identificadores sin espacios en los extremos ni caracteres de control o invisibles |
| SPLIT-C01 | Cada escenario del conjunto asignado una vez; ninguno desconocido |
| SPLIT-C02 | Un grupo en una sola partición (QA14: «intentar mezclar una variante») |
| SPLIT-C03 | El grupo de la asignación es el del escenario |
| SPLIT-C04 | Las tres particiones tienen al menos un grupo |
| SPLIT-C05 | La partición está congelada |
| SPLIT-C06 | Una fuente de campo no aparece en dos particiones (los escenarios sintéticos comparten su fuente de ejemplo por diseño y no cuentan) |
| SPLIT-P01 | Proporciones de la política entre 0 y 1 (sin incluirlos) y suma 1 |

Todos los problemas se informan juntos, cada uno con su regla, campo y motivo, en orden fijo; se cortan en 100. El error tiene código INPUT_SCHEMA (salida 2). Los nombres de las particiones en los mensajes van siempre en el orden entrenamiento, validación, prueba.

## Cómo se asigna

- **Cuántos grupos a cada parte.** Mayor resto sobre la cantidad de grupos, con las fracciones exactas de lo que se escribió (0.05 es cinco centésimos, no su aproximación binaria), y al menos un grupo en cada parte. Hacen falta tres grupos como mínimo. Con las proporciones provisionales 0.6 / 0.2 / 0.2: 3 grupos dan 1/1/1, 5 dan 3/1/1, 10 dan 6/2/2 y 20 dan 12/4/4.
- **Cuáles.** Los grupos se ordenan por el SHA-256 de `<semilla>|<política>|<grupo>`: los primeros van a prueba, los siguientes a validación y el resto a entrenamiento. No depende del orden en que lleguen los escenarios.
- **Familia completa.** Todos los escenarios de un grupo (todas sus perturbaciones y semillas) heredan la partición de su grupo. La partición creada es siempre `frozen`, y antes de devolverla se revisan todas las reglas (incluida la fuente de campo compartida).

## Verificación

- **Pruebas:** 139 nuevas. Suite completa: **2773 pasan, 1 se salta** (una prueba que solo corre fuera de Windows). Formato, lint, tipos, contratos y reglas de capas sin observaciones.
- **QA14 en esta fase:** mezclar una variante de una familia en otra partición se detecta (SPLIT-C02); un escenario repetido, sin asignar o desconocido se detecta (SPLIT-C01); un grupo equivocado (SPLIT-C03); una parte sin grupos (SPLIT-C04); una partición sin congelar (SPLIT-C05); una fuente de campo compartida (SPLIT-C06).
- **Valores fijos** (de la primera ejecución): con 10 familias `FAM_01`…`FAM_10`, la política provisional y la semilla 7, prueba son `FAM_03` y `FAM_08`, validación `FAM_05` y `FAM_10`, y entrenamiento las otras seis. Una prueba rehace con `hashlib` el orden documentado, así que la fórmula queda fijada además de los valores.
- **Mutaciones:** 48 cambios a propósito en las reglas, los bordes del reparto, el orden y los mensajes. **44 se detectaron de inmediato y 4 no.** Tres eran huecos reales (que el reparto use las fracciones exactas, que la prueba tenga su propia cantidad de grupos y no la de validación, y que tres familias justas sí se puedan partir) y se cerraron con pruebas; la cuarta (el orden en que se juntan los grupos) era equivalente, porque la asignación ordena por huella, y se simplificó el código. Las 48 quedan detectadas.
- **Rendimiento:** 100 familias y 2000 escenarios se particionan en menos de un segundo.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Con fracciones binarias, 0.05 / 0.15 / 0.8 de 28 grupos darían 1/4/23 en lugar del 2/4/22 exacto (un empate de restos se rompía por el ruido numérico) | Se usan las fracciones exactas de lo escrito; una prueba lo fija con ese caso |
| 2 | El nombre de la política reutiliza la regla de nombres seguros de la especificación, que se llama SPEC-S02 | En los errores de la partición sale como SPLIT-S02 |
| 3 | El orden de las particiones en un mensaje dependía de qué escenario aparecía primero | Se fija en entrenamiento, validación, prueba |
| 4 | Dos de mis valores esperados al escribir las pruebas estaban mal (uno de un reparto, otro inventado sin ejecutar) | Se verificó a mano el reparto (8 grupos, 0.45 / 0.25 / 0.3: 3.6, 2.0 y 2.4 dan 4/2/2) y los valores fijos salen de la ejecución, como anotan las pruebas |
| 5 | Ninguna dependencia nueva; `schemas/` sin cambios (siguen nueve contratos) | — |

## Límites

- Las proporciones son provisionales hasta que se decida DEC07; cuando se pasa un archivo de política (F3) se tratan como las del Product Owner.
- Con pocos grupos la partición es muy gruesa: con 3 grupos, uno por parte.
- La procedencia real compartida solo se comprueba (SPLIT-C06), no se agrupa: si una fuente de campo cayera en dos partes, el split no se crea.

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
