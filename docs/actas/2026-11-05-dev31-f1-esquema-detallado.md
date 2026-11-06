Escrito para: el Product Owner (aprobación del esquema y de dos cambios al diseño de F0) y el equipo técnico (F2 a F8 de DEV31).

# DEV31 F1: esquema detallado de la base de datos

- **Fecha:** 2026-11-05
- **Tarea:** DEV31 (historia propuesta HU15). Orden de fases: sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`.
- **Estado:** hecho y **pendiente de tu revisión**. Sin PostgreSQL, sin cambios en `documentacion/`, en el código del producto (`src/`) ni en `datos/`.
- **Modelo:** Opus.

## Qué se entregó

| Archivo | Qué es |
|---|---|
| `docs/bd/esquema.toml` | **Fuente única del diseño.** Cada tabla con todas sus columnas: tipo, si puede quedar vacía, unidad, descripción, de qué archivo y campo sale, y su regla. También las claves, relaciones, reglas, índices, cegado, usuarios, funciones y vistas. De aquí salen el diccionario y, en F3, las migraciones SQL |
| `docs/bd/diccionario.md` | **Diccionario completo**, generado desde el esquema. Todas las columnas de todas las tablas, un diagrama por esquema con todas sus columnas, un diagrama general y la lista de todas las relaciones. Cumple la regla de mostrar todos los campos |
| `scripts/bd_esquema.py` | Verifica el esquema y regenera el diccionario. Con `--comprobar` falla si el diccionario quedó desactualizado; con `--html` escribe la versión para el navegador |

**Cifras:** 54 tablas aprobadas en F0 y 2 propuestas nuevas. En total suman 864 columnas: 755 propias y 109 comunes (`carga_id` y `artefacto_id`). Además, 112 relaciones entre tablas, 7 diagramas, 11 vistas, 7 funciones o disparadores y 4 usuarios.

**Estado de las fuentes:**
- 24 tablas leen archivos que ya existen.
- 9 dependen de un formato que ya existe pero todavía sin datos, o con columnas que llegan en F2.
- 23 tienen fuente pendiente: aprendizaje, evaluación, calibración y los hitos. Sus columnas salen de los contratos (`schemas/`) y de los documentos 01 y 03. Se confirmarán cuando DEV16 a DEV26 publiquen sus archivos.

## Cómo se verificó

- **El verificador revisa:**
  - nombres válidos y sin repetir, y tipos conocidos;
  - claves primarias que nunca quedan vacías;
  - que cada relación apunte a una clave primaria o única, con el mismo tipo y con su obligatoriedad coherente;
  - que las relaciones uno a uno usen toda la clave primaria;
  - que el cegado de cada tabla esté bien declarado;
  - que las 54 tablas aprobadas coincidan **exactamente** con el catálogo de la sección 5.4 del acta de F0.
- **Resultado:** esquema correcto.
- **Ensayo de daño a propósito:** **14 de 14** errores detectados (tipo distinto en una relación, relación a una columna que no es clave, clave primaria vacía, tipo desconocido, obligatoriedad incoherente, tabla propuesta pasada a aprobada, tabla sin clave, cegado por un padre no cegado, raíz de cegado vacía, tabla referida inexistente, columna repetida, nombre inválido, uno a uno mal declarado y columna sin origen). El guion está en la carpeta de trabajo de la sesión (`danio_esquema.py`).
- **Estilo:** `ruff check` y `ruff format` sin observaciones en `scripts/bd_esquema.py`.
- **Diagramas:** el más grande tiene 11 813 caracteres. GitHub dibuja hasta 50 000.
- **Diccionario al día:** `scripts/bd_esquema.py --comprobar` lo confirma.

## Dos cambios al diseño de F0 que necesitan tu aprobación

### 1. El cegado de la prueba deja de guardar la zona en cada fila

F0 (decisión B4) decía que cada fila llevaría su zona, desarrollo o prueba. Al detallarlo apareció un defecto. Las filas no se modifican (B2). Si un escenario se carga antes de que exista su partición, quedaría marcado como desarrollo para siempre, y su prueba quedaría a la vista.

**Lo que propongo:**
- **Zona deducida:** la zona se deduce de la partición congelada y de los hitos, en vez de guardarse. Un escenario asignado a test queda oculto mientras su partición no tenga el hito de apertura. Todo lo que cuelga de él (corridas, vehículos, búsquedas, etiquetas, comparaciones) hereda esa visibilidad. La propia base lo aplica con seguridad por filas.
- **Visibilidad automática:** al cargar la partición o abrir la prueba, la visibilidad cambia sola, sin modificar ningún dato.
- **Regla de carga:** no se carga un escenario sin partición congelada, salvo que se autorice como «preliminar». La autorización queda registrada en la carga. Un preliminar no puede pasar después a prueba: la base lo rechaza y lo registra como incidencia.

El principio de F0 no cambia: la prueba queda oculta hasta su apertura y lo hace cumplir la base. Cambia cómo se logra.

### 2. Dos tablas nuevas propuestas (pasarían de 54 a 56)

| Tabla | Por qué | Si no se aprueba |
|---|---|---|
| `simulacion.plan_tramos` | La duración de cada tramo de un plan en filas. Permite consultar, por ejemplo, el t5 de todos los planes ganadores, exige que el tramo exista en el caso y sirve para cruces con otra cantidad de tramos | Las duraciones quedan como lista dentro de `planes.duraciones_s`. Funciona, pero no se puede comprobar el tramo contra el caso |
| `caso.reportes_calidad` | El resumen de cada reporte de calidad de aforos (cobertura por movimiento, huecos, faltantes y exclusiones). Es parte de I1 y el archivo ya existe (`resumen.json`) | La cobertura de los aforos no tendría lugar en la base |

## Otros ajustes del detalle

Estos ajustes no cambian el diseño.

**Lo que cambia con el tiempo pasa a ser un hito.** Por la regla de solo agregar, el congelamiento del protocolo, la partición y el modelo, y la apertura de la prueba, se registran en `control.hitos`. Ya no son columnas que se modifican. El estado del experimento se deduce de sus hitos.

**Solo se cargan particiones congeladas.** La base exige además que cada escenario esté en una sola partición, y que cada semilla esté en una sola etapa del protocolo.

**Una etiqueta de prueba no puede entrar a un conjunto de entrenamiento.** Lo impiden una regla de la base y un disparador.

**La clase de la regla C** (limpia, incidente aislado o colapso) va en `candidato_semillas`, no en `resultados_corrida`. Depende de la regla de la búsqueda, no de la corrida.

**Los valores codificados se guardan en inglés, como en los archivos.** Por ejemplo, el estado de una corrida se guarda como succeeded y no como «exitosa». El diccionario los traduce.

**Correcciones al borrador del 2026-11-05.** Ese borrador (la primera página del diccionario) tenía columnas que no salen de ningún archivo, y las quité:
- `giro` en movimientos;
- `descripcion` en tipos de vehículo y grupos de verde;
- `fecha_vigencia` en el plan vigente;
- detenciones por movimiento;
- `origen` en planes;
- `zona` en varias tablas.

**Cómo se guarda la cola segundo a segundo.** Queda como una fila por segundo, leída siempre a través de una vista. Se confirma midiendo con las 133 corridas en F4 (carga de lo existente).

## Hallazgos

1. **El contrato de respuesta del modelo solo registra los errores, no las reglas cumplidas**, aunque el documento 01 pide reglas satisfechas e incumplidas. Por eso `consulta_reglas` guarda solo las incumplidas. Hay que decidirlo en DEV18.
2. **Ningún manifiesto registra el equipo (procesador y memoria)**, aunque la tesis lo pide junto a las mediciones de tiempo (I7). La columna `entornos.equipo` queda vacía. Propongo que F2 lo agregue junto con el commit del código.
3. **DEV17 debe publicar el paquete del modelo una sola vez** y registrar su congelamiento como hito. Si vuelve a publicar el mismo modelo con otro estado, la base lo rechaza como conflicto. Lo mismo vale para un protocolo congelado: necesita otro identificador que su borrador, o publicarse una sola vez.
4. **El acceso no puede ser una tabla.** Para los carriles de la zona que no pertenecen a un movimiento, el código usa el nombre de la calle. Por eso `acceso` es texto sin relación.
5. **Las réplicas de la auditoría A06 están fuera de `datos/`.** Solo se cargarán las réplicas cuyas dos corridas estén en `datos/`.
6. **Las corridas que no son de ninguna búsqueda** (DEV00, DEV07 y DEV19) llevan la etapa `diagnostic`.
7. **F0 pedía sumar a la fase de compresión del FCD (hoy F2) la publicación de las métricas de cada corrida** (`metricas.json`, incluida la cola segundo a segundo). Lo tomo como aprobado con tu aprobación de F0. Si no es así, avísame: sin eso, la carga tendría que recalcular cada archivo de posiciones.

## Lo que pido al PO

1. ¿Apruebas el esquema detallado (`docs/bd/diccionario.md`)?
2. ¿Apruebas el cambio del cegado (zona deducida y regla del preliminar)?
3. ¿Apruebas las dos tablas nuevas, `plan_tramos` y `reportes_calidad`?
4. ¿Sumo a F2 el registro del equipo (procesador y memoria) en los manifiestos?
5. ¿Ejecuto F2 (compresión del FCD, commit y equipo en los manifiestos, y métricas publicadas)? Recomiendo Sonnet.
