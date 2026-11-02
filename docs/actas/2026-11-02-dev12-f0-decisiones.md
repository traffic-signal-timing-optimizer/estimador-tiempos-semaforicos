# Acta 2026-11-02: DEV12 · F0 (decisiones, sin código)

- **Tipo:** fase F0 de DEV12 (HU07; P0, tamaño M). Dependencia: DEV11, cerrada.
- **Autorización:** el Product Owner aprobó el plan (`2026-11-01-planes-dev09-dev11-dev12.md`) y pidió ejecutar las fases de DEV12 después de las de DEV11, una tras otra. Los cambios de la matriz que pedía el plan (QA15 parcial con cierre en DEV16) y los puntos que dejó con propuesta (comandos `splits create / validate` incluidos; proporciones provisionales hasta DEC07) se aplican como se propusieron.
- **Datos:** sintéticos. Ninguna salida se presenta como observada en Lima.
- **Modelo:** Sonnet alcanza. El riesgo es medio (una fuga invalida todo lo posterior sin que nada falle a la vista), así que F1 y F2 se verifican con ensayo de mutaciones, como en DEV10 y DEV11.

## Qué pide la documentación

«Asignar familias completas; validar cobertura, disjunción de grupos e IDs; impedir entrenamiento con test». Archivo propuesto `aprendizaje/splits.py`. Resultado: «Split congelado». Verificación: QA14 y QA15. HU07: un grupo en una sola partición; cada escenario asignado una vez; prueba excluida de ajuste; manifiesto inmutable. Diseño: «agrupar primero por día/familia; todas sus semillas y perturbaciones derivadas permanecen en el mismo grupo; reservar test una vez; crear train/validation sobre grupos de desarrollo; la cantidad de grupos y proporciones son parámetros del piloto; prohibir solapamiento por IDs de escenario, grupos y procedencia real compartida». ADR07 (Propuesta): «aislamiento lógico y comprobaciones de conjuntos obligatorios, aunque el investigador tenga acceso local a los archivos»; un cambio aprendido de los resultados de prueba implica un experimento nuevo.

## Qué ya existe y se reutiliza

| Pieza | Dónde | Uso |
|---|---|---|
| Contrato `split` v1.0 (`split_id`, `policy`, `seed`, `frozen`, `assignments` con `scenario_id`, `group_id`, `partition`) | `schemas/split.schema.json`, `tests/fixtures/split.json` | El archivo del split sigue exactamente este contrato; no se cambia |
| Conjunto de escenarios verificado, con `group_id` por escenario | `datos/scenario_set.py` (DEV11) | Entrada de la asignación |
| Publicación atómica, lectura verificada, huellas, `content_id` | `trazabilidad/*` | Manifiesto del split |
| Revisión del espacio de trabajo | `app/integrity.py` | Se agrega la familia «particiones» |

`aprendizaje/` solo tiene el archivo de inicio: todo lo demás es nuevo.

## Decisiones

| # | Decisión |
|---|---|
| D1 | **Alcance como en el plan.** QA14 completo. QA15 parcial: DEV12 entrega el bloqueo y el caso de prueba (valor atípico solo en la prueba, y que no entra al ajuste); entrenar y comparar el paquete del modelo es de DEV16, donde se cierra. Los comandos `splits create / validate` entran en F3. Cambia la matriz y se anota aquí. |
| D2 | **Dónde vive el código.** `dominio/split.py` (modelo del contrato `split`, política, reglas SPLIT y errores, sin leer archivos); `aprendizaje/splits.py` (asignación y vista de desarrollo, F1 y F2); `aprendizaje/split_store.py` (manifiesto, publicar y leer verificado, F3); `app/split_commands.py` y el grupo `splits` en la CLI (F3). Respeta ADR01: `aprendizaje` puede usar `datos` y `trazabilidad`; `cli` solo importa `app`. |
| D3 | **Unidad de asignación: la familia completa.** El grupo del escenario (`group_id`, que DEV11 pone igual a la familia) va entero a una partición, con todas sus perturbaciones y semillas. Nunca se asigna por fila ni por escenario suelto. |
| D4 | **Política.** Un archivo opcional `--policy` (JSON, `schema_version` 1.0.0) con `policy_id` y las proporciones de grupos para `train`, `validation` y `test` (cada una entre 0 y 1, suma 1). Sin archivo se usan valores **provisionales** (0.6 / 0.2 / 0.2, `family_holdout`) porque DEC07 está pendiente; el manifiesto dice si son provisionales. Como no son un contrato publicado, el archivo de política no tiene esquema en `schemas/` (siguen nueve contratos). |
| D5 | **Asignación determinista.** Con la semilla del comando: se ordenan los grupos por el SHA-256 de `<semilla>\|<política>\|<grupo>`; cuántos van a cada partición sale de las proporciones por mayor resto, con al menos un grupo en cada una (hacen falta 3 grupos como mínimo); los primeros van a `test`, los siguientes a `validation` y el resto a `train`. Misma entrada y semilla dan la misma partición. |
| D6 | **Reglas del split** (todas se informan juntas, con regla, campo y motivo): SPLIT-S01 contrato y tipos; SPLIT-C01 cobertura, cada escenario del conjunto asignado una vez y ninguno desconocido; SPLIT-C02 un grupo en una sola partición (QA14: «intentar mezclar una variante»); SPLIT-C03 el grupo de cada asignación es el del escenario; SPLIT-C04 las tres particiones tienen al menos un grupo; SPLIT-C05 el split publicado está congelado (`frozen`); SPLIT-C06 procedencia compartida: dos escenarios `field_derived` de particiones distintas no comparten fuente. |
| D7 | **Procedencia real compartida.** Hoy no hay datos de campo, así que solo se comprueba (SPLIT-C06) y no se agrupa por procedencia: si una fuente de campo aparece en dos particiones, el split no se crea. Los escenarios sintéticos comparten fuentes de ejemplo por diseño y no cuentan. Queda anotado como límite hasta que existan aforos reales. |
| D8 | **Un solo split por conjunto («reservar la prueba una vez»).** El split se publica en `derivados/particiones/<caso>/<huella16>/`, donde `<huella16>` es el comienzo de la huella de contenido del conjunto de escenarios. Como nunca se sobrescribe, un segundo split del mismo conjunto se rechaza. Cambiar la partición exige un conjunto nuevo (experimento nuevo, ADR07). |
| D9 | **Bloqueo de la fuga (F2).** La parte que ajusta no recibe la prueba: `development_view(split)` entrega solo los identificadores de entrenamiento y de validación (no existe un atributo con los de la prueba). Pedir filas o identificadores de la prueba para ajustar, seleccionar o hacer el refit es un error (`LeakageError`, INPUT_SCHEMA) que dice cuáles se pidieron. Los de la prueba solo salen con la finalidad explícita `final_evaluation`. Es aislamiento lógico y verificable, no una convención. |
| D10 | **Manifiesto inmutable.** `split.json` (el contrato) y `manifiesto.json` (caso, conjunto de escenarios y su huella, política y proporciones, si son provisionales, semilla, fecha, grupos y conteos por partición, huellas) se publican con `publish_files`: solo lectura, nunca sobrescritos, lectura verificada, y `frozen` siempre verdadero. `runs verify` agrega la familia «particiones». |
| D11 | **Comandos (F3).** `splits create --scenarios CARPETA --seed N [--policy ARCHIVO]` y `splits validate --split CARPETA --scenarios CARPETA`. Códigos: 0 correcto; 2 argumentos, conjunto o política inválidos, o un split con problemas (se listan todos); 5 enlace, huella alterada o split ya existente; 1 interno. |
| D12 | **Caso de prueba de QA15 (F4).** Etiquetas sintéticas por escenario con un valor atípico que solo aparece en un escenario de la prueba; se demuestra que las filas de ajuste y su huella no cambian si ese valor se altera, y que intentar incluirlo se bloquea. El paquete del modelo, las transformaciones y la selección (los otros hashes de QA15) son de DEV16. |
| D13 | **Límites que se declaran:** proporciones provisionales hasta DEC07; sin comprobación de procedencia real más allá de SPLIT-C06; con pocos grupos la partición es muy gruesa (con 3 grupos, uno por partición) y la incertidumbre es alta, como advierte el plan de pruebas. |
| D14 | **Pruebas:** unitarias de cada regla, de la asignación (incluida la determinación y la independencia entre ejecuciones), del bloqueo, del split publicado (alteraciones con huellas coherentes), de la CLI y de punta a punta; de seguridad con políticas y splits hostiles; y ensayo de mutaciones en cada fase. |
| D15 | **Modelo:** Sonnet. Si en F1 o F2 apareciera una dificultad que lo supere se avisa; no se prevé. |

## Fases

| Fase | Qué se hace |
|---|---|
| F1 | `dominio/split.py` y `aprendizaje/splits.py`: modelo del contrato, política, reglas SPLIT-C y asignación determinista por familia (QA14) |
| F2 | Bloqueo: vista de desarrollo y errores de fuga; la prueba solo con la finalidad explícita |
| F3 | `aprendizaje/split_store.py`, comandos `splits create / validate`, `runs verify`, README |
| F4 | Caso de prueba de QA15 (valor atípico solo en la prueba) |
| F5 | Cierre: acta, inspección contra la documentación y el caso real, bitácora |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin push.
