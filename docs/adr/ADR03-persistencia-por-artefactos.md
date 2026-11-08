# ADR03: Persistencia por artefactos inmutables

- **Estado:** Aceptada el 2026-11-08 (DEC09, por delegación del PO)
- **Tipo:** V/P
- **Fecha de registro:** 2026-10-19
- **Fuente:** `documentacion/documentos/01_Diseno_tecnico.md`, sección «Arquitectura y decisiones registradas»

> **Alcance posterior aprobado por el PO el 2026-11-05:** la exclusión de una base relacional en la decisión original quedó superada por HU15/DEV31 (ADR12). Los artefactos inmutables con huellas siguen siendo los originales; PostgreSQL local es una copia de consulta reconstruible y su carga sí usa transacciones. La enmienda del 2026-11-06 sobre huellas en git sigue vigente.

## Decisión

Persistencia por artefactos inmutables en CSV, JSON y XML, con manifiestos y SHA-256. Cada ejecución escribe un directorio nuevo y publica resultados mediante renombrado atómico. La integridad se verifica contra un manifiesto aprobado.

## Motivo

Reproducibilidad y trazabilidad sin base de datos. Un hash guardado junto a un archivo modificable no acredita por sí solo autenticidad.

## Alternativas descartadas

- Base de datos relacional: no se prevén transacciones de base de datos en el alcance.

## Impacto

Afecta a `trazabilidad/` y a todos los módulos que escriben resultados. Una corrección produce un artefacto nuevo; los originales no se sobrescriben.

## Prueba de aceptación

QA09 (dos ejecuciones con mismos insumos producen resultados equivalentes) y QA29 (artefacto modificado bloquea la exportación; sin sobrescritura).

## Enmienda del 2026-11-06 (DEV31 F3): las huellas de lo publicado se guardan en git

Aprobada por el PO el 2026-11-06. Las frases de la decisión original que dicen «sin base de datos» se leen como historia de la propuesta v1.0; la nota de alcance posterior de arriba registra la excepción aprobada. La regularización formal se hizo en DEV31 F7, junto con DEC09.

- **Los archivos siguen siendo la fuente.** La base PostgreSQL de DEV31 es una copia consolidada que se regenera desde ellos (decisión B1 del acta de F0); ningún proceso de cálculo la lee.
- **Huellas en git:** `python -m semaforo bd verificar --huellas docs/bd/huellas.json` escribe la huella de cada archivo **raíz** que conoce la base (cada manifiesto y cada archivo suelto, como el caso o un protocolo) y la huella de contenido de toda la base. La huella de un manifiesto fija la de todos los archivos que declara, así que ese archivo alcanza para comprobar todo lo publicado. Confirmado en git y subido a GitHub, da una fecha externa que el administrador de la laptop no puede cambiar. Este punto responde a la observación de este ADR: «un hash guardado junto a un archivo modificable no acredita por sí solo autenticidad».
- **Cuándo:** después de cada carga de la base y en cada hito del procedimiento (protocolo, partición y modelo congelados, apertura de la prueba). El push lo pide el PO.
- **Hitos:** `bd hito` publica el hito como carpeta de solo lectura (`datos/derivados/hitos/<hito_id>`) con la huella de su acta, que tiene que estar confirmada en git. Así el hito también sale de un archivo y la base se puede regenerar con él.
- **Prueba de aceptación:** QA36. La base regenerada desde los mismos archivos da la misma huella de contenido (`bd verificar --regenerar`), y un archivo raíz que cambió hace fallar `bd verificar` (código 5).

## Precisiones de DEC09 (2026-11-08)

Análisis y motivo: `docs/actas/2026-11-08-dev31-f7-dec09.md`. La regularización que dejó pendiente la enmienda del 2026-11-06 queda hecha aquí y en ADR12.

1. **Formatos.** Además de CSV, JSON y XML, se admiten XML comprimidos (`fcd.xml.gz` desde DEV31 F2, unas 10 veces más livianos). Las 3 corridas de DEV00 y las anteriores a F2 conservan su formato.
2. **Original y copia.** Los archivos con huella son el original. La base es una copia de consulta que se regenera desde ellos (ADR12). Ningún cálculo lee la base.
3. **Crecimiento.** La estimación de F0 es de unos 12 GB de archivos para DEV16 y unos 42 GB para todo el proyecto, con 423 GB libres en D:. Si el espacio llegara a ser un problema, se decide con otro ADR (por ejemplo, archivar lo antiguo). Los originales no se borran en silencio.
4. **Pruebas pendientes.** QA09 y QA29 se cumplieron en lo que toca a corridas y manifiestos. La exportación completa de QA29 llega con DEV21 y DEV27.
