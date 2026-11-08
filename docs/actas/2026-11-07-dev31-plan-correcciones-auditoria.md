Escrito para: el Product Owner (decisiones y aprobación) y el equipo técnico y el auditor (ejecución y verificación).

# DEV31: análisis y plan de correcciones de las auditorías del 6 y 7 de noviembre (versión 3.4)

- **Fecha:** 2026-11-07
- **Tarea:** DEV31 (historia HU15). Se inserta **antes de F5** (panel estático), como etapa de correcciones «F4c». Orden general de fases: sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`.
- **Estado actualizado al 2026-11-07:** plan aprobado por el PO; C0 y C1 cerradas, incluida la corrección posterior de P9. C2 y C3 no se han ejecutado. Cada etapa nueva empieza solo con orden expresa del PO (ACU-21); D11 se decide en P7.
- **Fuentes:** `docs/auditorias/2026-11-06-auditoria-seguimiento-postgresql.md`, `docs/auditorias/2026-11-07-auditoria-seguimiento-dev31.md`, la corroboración del 2026-11-07 (sección 2) y las dos revisiones del PO (sección 1.1 y sección 3).
- **Versiones anteriores:** v1 a v3.3 de este mismo documento. La v3.4 reemplaza a las anteriores; los acuerdos de la sección 3 vienen de ellas.
- **Modelo con que se preparó:** Haiku 5.5.

## 1. Resumen para el PO

**Qué pasaba al corte de la auditoría.** Las dos auditorías dejaron 10 observaciones abiertas (B01 a B10). Las comprobé con pruebas y no solo leyendo el código: **todas eran reales en ese corte**. Ninguna cambió una cifra de tus datos. Las 130 corridas estaban completas y coincidían con los archivos. Fallaban las **herramientas de control**: en algunos casos podían decir «todo en orden» cuando no lo estaba. El avance posterior de C0 y C1 está resumido arriba; C2 y C3 siguen pendientes.

**Por qué aparecieron.** Casi todas salen de seis causas de fondo (sección 4). Si se corrigen solo los síntomas, la próxima auditoría encontrará el mismo problema en otra tabla. Por eso el plan corrige las causas.

**Plan aprobado.** Cuatro etapas antes de F5:

| Etapa | Qué se hace | Cambia la base |
|---|---|---|
| C0 | Tus decisiones, y comprobaciones **solo de lectura** de red y de permisos | No |
| C1 | Controles nuevos sin cambiar el esquema: cobertura en los dos sentidos, decisiones como archivos verificables, verificación con candado compartido, catálogo de reglas instaladas, respaldos con versión, comando de reconstrucción seguro | No |
| C2 | Diseño corregido y **una sola reconstrucción** en los diez pasos P0 a P9 con puertas (sección 6.2). Otorga al rol del panel acceso solo a vistas aprobadas | Sí |
| C3 | Pruebas por observación, barrido de cegado en base desechable, ensayo de daño, evidencia reproducible y acta | No |

**Esfuerzo:** cinco o seis sesiones. **Riesgo:** medio en C2, concentrado en el cegado y en el cambio de base.

**Medidas de protección de los datos:** (1) los procedimientos solo leen `datos/` y agregan carpetas nuevas; no modifican las existentes. (2) La base vigente se conserva con otro nombre y no se borra sin tu confirmación. (3) El cambio de nombre se prueba con reversión antes de hacerse. (4) Hay respaldo con ficha, verificado antes de cualquier cambio. **Riesgo residual:** un fallo no previsto durante el cambio, o un error al confirmar un borrado. Estas medidas lo reducen; no lo eliminan.

**Meta para la próxima auditoría:** ninguna observación alta; solo observaciones bajas o riesgos aceptados y escritos.

**Evidencia posterior al plan:** C0 y C1 se cerraron el 2026-11-07. La decisión D7 sobre las tres corridas de DEV00 ya se publicó; la bitácora registró 143 unidades publicadas, 140 cargadas y 3 con decisión. En C1.11 se añadió la comparación de versión del esquema, contenido y reglas, y la reversión cuando P9 encuentra una diferencia o `verify()` lanza una excepción. La puerta completa posterior pasó con 5408 pruebas y 43/43 contratos. Véanse las actas de C1, de las tres huellas y de la corrección P9. Las tablas de diagnóstico de este plan conservan el corte de la auditoría inicial; esta nota registra lo resuelto después.

### 1.1 Qué cambió en cada versión

| Versión | Qué se agregó o corrigió |
|---|---|
| v1 | Diagnóstico, causas, matriz y plan inicial |
| v2 | Revisión 1 del PO: validar la base nueva antes del cambio de nombre; exclusiones que sobreviven a la reconstrucción; cegado de archivos compartidos y rol del panel; congelación exacta de la selección; verificación de reglas instaladas; contratos de arreglos y huella del protocolo; red con prueba de aislamiento; `bd verificar` solo de lectura; estimación revisada |
| v3 | Revisión 2 del PO, aceptada: dos controles distintos para el cambio de esquema; pruebas de cegado en base desechable con el mismo catálogo; prueba de duraciones exclusivas recuperada; archivos de alcance no comprobado ocultos; protocolo exacto de la selección; concurrencia con candado compartido; identidad de decisión por ruta y huella; rol del panel en paso aparte. Además, corrijo errores míos (sección 5) |
| v3.1 | Ajustes de la revisión 3 del PO: fichas de respaldo con estado por campo (ACU-22) y eliminación de la frase de riesgo cero, reemplazada por medidas de protección y riesgo residual (ACU-23). Estimación sin cambios |
| v3.2 | `bd probar-respaldo` recibe `--respaldo <ruta>` y verifica cualquier respaldo, no solo el más reciente (ACU-24). Criterios de aceptación para los dos respaldos antiguos. Estimación sin cambios |
| v3.3 | Revisión 5 del PO, aplicada: la huella se recalcula sobre las tablas restauradas y se compara con una referencia registrada antes de la restauración (no con el valor guardado en `control.cargas`). Ficha de respaldos con referencia y mecanismo de instantánea (C1.8). Procedimiento de seis pasos de `bd probar-respaldo` (C3.5). Criterios de aceptación de B10 (6.5). Paso P5 con condición previa al respaldo. Decisiones D13 y D14 propuestas por el equipo, pendientes de aprobación. Estimación sin cambios |
| v3.4 | Decisiones D2 a D14 aprobadas por el PO el 2026-11-07, incluidas D13 y D14. Estado del plan actualizado. Ninguna etapa se ejecuta sin orden expresa. Estimación sin cambios |

## 2. Qué se comprobó (evidencia del 2026-11-07)

| # | Observación | Qué hice | Resultado |
|---|---|---|---|
| B01 | La conciliación aprueba una base vacía | Concilié contra una base temporal vacía | `equal`, 0 archivos, 0 corridas, con y sin recálculo. Además, `bd cargar` termina con éxito aunque queden unidades pendientes o no cargables (`load_exit_code` solo mira los rechazos) |
| B02 | El lector ve datos auxiliares de la prueba | En una copia puse ESC-SINT-001 como «prueba» y consulté como lector | Ve 0 corridas y 0 etiquetas, pero **sí ve 21 planes, 189 tramos y 2 618 archivos con sus rutas**. La política de `evaluacion.diferencias` mira solo el lado A (`03_seguridad.sql:181`) |
| B03 | Los hitos pueden mezclar experimentos | Revisé la estructura | El disparador de congelar el modelo exige «algún protocolo congelado» (`02_reglas.sql:103`). La apertura exige el protocolo del experimento congelado (`02_reglas.sql:118`), pero nada lo liga a la selección del modelo. `aprendizaje.seleccion` admite protocolo vacío y varias selecciones por modelo (`01_tablas.sql:1944`) |
| B04 | Protocolo de la corrida y de las métricas | Consulté la base real | Búsqueda 63/63 y finalistas 39/39 coinciden. Las 28 de diagnóstico tienen el protocolo de las métricas y ninguno propio. Ninguna regla lo exige |
| B05 | El recálculo no ve escenarios generados | Revisé el código | `load_context` solo indexa `datos/escenarios`; `_recompute` usa `[...]` directo (error `KeyError`) y solo captura `DomainError` |
| B06 | La huella de git no se usa | Comparé la base con `docs/bd/huellas.json` | Coinciden, pero ningún comando lo hace por sí solo |
| B07 | PostgreSQL escucha en la red | Revisé puertos y `pg_hba.conf` | Escucha en `0.0.0.0` **y en `[::]` (IPv6)**. `pg_hba.conf` solo admite conexiones desde 127.0.0.1 y ::1. Falta confirmar con `SHOW hba_file` que es el archivo que usa el servicio (C0.2) |
| B08 | Accesos con cola y sin cohorte | Revisé el cargador | Siguen fuera de `resultados_acceso` |
| B09 | Los arreglos de cola no tienen reglas de valores | En una copia inserté datos malos | Acepta negativos y textos. Una consulta que lee la columna falla. La conciliación dice `equal` con un texto dentro y con dos valores intercambiados en la ventana; la huella de contenido **sí** cambia |
| B10 | Los respaldos son del diseño anterior | Listé su contenido y probé uno nuevo | Los dos tienen `cola_segundo`. Un respaldo nuevo de la base actual (8,4 MB) se restauró con la misma huella |

**Hallazgos nuevos que la auditoría no mencionó:**

| # | Hallazgo | Impacto |
|---|---|---|
| N1 | `control.replicas` apunta a dos corridas y **no está cegada** | Medio, cuando haya réplicas de la prueba (DEV27) |
| N2 | De las 34 tablas «sin cegado», 3 apuntan a tablas cegadas (`control.replicas`, `experimento.asignaciones`, `aprendizaje.conjunto_etiquetas`) y ninguna lleva escrita la razón | Bajo |
| N3 | El dueño de la base (`semaforo_admin`) puede apagar los disparadores de «solo agregar»: lo hice en una copia | Bajo: rol de confianza, pero hoy no hay forma automática de detectarlo |
| N4 | La reconstrucción de la base del cambio de cola se hizo con un guion temporal, igual que los ensayos de daño de F2 a F4 (A06) | Medio para la reproducibilidad |
| N5 | `_record_conflict` (`motor.py:248-257`) solo evita duplicar conflictos **sin decisión**. Una vez decidido un conflicto, la siguiente carga del mismo archivo lo vuelve a registrar como pendiente | Medio: sin corregirlo, las 3 corridas de DEV00 reaparecerían como pendientes en cada carga |
| N6 | `pg_try_advisory_lock` (`motor.py:817`) es exclusivo. La verificación y la conciliación no lo toman, así que pueden leer una base que cambia a mitad de camino | Medio para la verificación con carga en paralelo |

## 3. Acuerdos registrados

Esta sección recoge todo lo acordado con el PO en las dos revisiones y las ideas que el PO aprobó. Cada acuerdo indica dónde se implementa. Si un acuerdo cambia, se cambia aquí y se anota en la sección 1.1, para no volver a discutirlo.

| ID | Acuerdo | Origen | Dónde se implementa |
|---|---|---|---|
| ACU-01 | El cambio de esquema tiene **dos controles distintos**: (a) la base vigente contra git; (b) la base candidata por conciliación, regeneración y restauración. Solo con ambos se aprueba la huella nueva | Revisión 2, punto 1 | C1.6, C2.7 pasos P0 a P7 |
| ACU-02 | La base candidata se crea con **nombre temporal**. Antes del cambio de nombre se validan cobertura, métricas, permisos y respaldo. El cambio tiene reversión probada | Revisión 1, punto 1 | C1.11, C2.7 |
| ACU-03 | Las pruebas de cegado y de seguridad se ejecutan en una **base desechable** con el mismo esquema, los mismos permisos y el mismo catálogo de reglas (comparado por huella). La candidata solo recibe consultas de solo lectura y el cotejo de las 130 corridas | Revisión 2, punto 2 | C2.7 paso P6, C3 |
| ACU-04 | La prueba de duraciones de planes exclusivos de prueba se recupera en el barrido de cegado | Revisión 2, punto 3 | C3.2 |
| ACU-05 | Un archivo de alcance desconocido, o marcado «por escenarios» sin enlaces válidos, queda **oculto hasta clasificarlo**. Abrir una prueba libera solo los archivos cuyo alcance está comprobado | Revisión 2, punto 3 | C2.6 (c) |
| ACU-06 | El panel usa un **rol propio** que solo lee **vistas aprobadas**. Las vistas leen con permisos del dueño y aplican el cegado dentro. Cada vista se revisa aparte | Revisión 1, punto 3, aceptado | C2.6 (g), F5 |
| ACU-07 | La selección congelada se liga así: el hito de modelo fija `seleccion_id` y su huella; el protocolo de la selección debe estar **congelado antes del modelo** y ser **el mismo** que declara el experimento al abrir; el protocolo es obligatorio; una selección por modelo | Revisión 1, punto 4; revisión 2, punto 4 | C2.5 |
| ACU-08 | Sobre la apertura: si D3b es «sí», cada partición tiene un solo experimento final y la apertura libera esa partición. Si D3b es «no», cada apertura libera solo su experimento, y el cegado pasa de por partición a por experimento | Revisión 2, punto 4 | C2.5, C2.6 |
| ACU-09 | Las exclusiones son **decisiones en archivo**, con identidad por **ruta y huella**. Una decisión no cubre un archivo modificado: ese archivo queda pendiente y admite una decisión nueva. `_record_conflict` no vuelve a abrir un conflicto ya decidido | Revisión 1, punto 2; revisión 2, punto 5 | C1.5, N5 |
| ACU-10 | Concurrencia: la verificación y la conciliación toman el candado de sesión en **modo compartido**; la carga toma el exclusivo. La verificación compara el `carga_id` de la última carga al inicio y al final. Una carga en curso (o en estado `running`) da *no concluyente* | Revisión 2, punto 5 | C1.6, C1.7, N6 |
| ACU-11 | La huella de referencia incluye las reglas instaladas: disparadores activos, políticas, seguridad por filas, permisos, funciones y vistas. Desactivar un disparador sin tocar datos debe fallar | Revisión 1, punto 5 | C1.10 |
| ACU-12 | Los arreglos de cola se escriben por la ruta normal de carga, no con matrices en `unnest`. Pruebas con series de distinta longitud, nulos y tiempos no finitos | Revisión 1, punto 6 | C2.1 |
| ACU-13 | El manifiesto de métricas pasa a 1.1.0 con la huella del protocolo. `metricas.json` (2.1.0) no cambia. Las 130 publicaciones actuales siguen legibles | Revisión 1, punto 6; D6 y D10 | C2.4 |
| ACU-14 | La red se trata en dos pasos: primero solo lectura y prueba de aislamiento (C0.2 a C0.4); después el cambio de `listen_addresses`, con reinicio del servicio y pasos exactos | Revisión 1, D4 | C0, D4 |
| ACU-15 | La **verificación es de solo lectura**. La creación y la restauración de bases temporales van en comandos separados (`bd probar-respaldo`, `bd reconstruir`) | Revisión 1, cierre | C1.6, C1.8, C1.11, C3.5 |
| ACU-16 | **La creación del rol del panel** es un paso aparte, que cambia la base y depende de tu decisión D8. No va junto con las comprobaciones de solo lectura | Revisión 2, último punto | C0.1 a C0.4 frente a C0.5 |
| ACU-17 | `bd reconstruir` exige la carpeta del repositorio, porque sin las actas no se cargan hitos ni decisiones | Propuesta de mi parte, aceptada | C1.11 |
| ACU-18 | `bd verificar` distingue una referencia de **otra versión del esquema** (*no concluyente*) de una diferencia (*difiere*) | Propuesta de mi parte, aceptada | C1.6 |
| ACU-19 | La conciliación incremental queda para F6 | Revisión 1, cierre | Sección 6.4 |
| ACU-20 | Modelos por etapa: C1 Sonnet, C2 Opus, C3 Sonnet. Estimación de cinco o seis sesiones | Revisión 1, cierre | Sección 7 |
| ACU-21 | Ninguna etapa se ejecuta sin orden expresa del PO, y cada una cierra con su acta | Principio del proyecto | Sección 6 |
| ACU-22 | Las fichas de los respaldos separan lo verificado de lo declarado: cada campo tiene un estado, y lo no comprobado se marca como tal (no se atribuye) | Revisión 3 del PO, punto 1 | C1.8, C3.5 |
| ACU-23 | Ningún texto del plan afirma que los datos no corren riesgo. Se describen las medidas de protección y el riesgo residual | Revisión 3 del PO, punto 2 | Sección 1, sección 6.2 y sección 7 |
| ACU-24 | Verificación de un respaldo específico: `bd probar-respaldo --respaldo <ruta>` registra por separado la integridad del archivo, el resultado de la restauración y la coincidencia del contenido. El contenido se recalcula sobre las tablas de la base temporal y se compara con una referencia aplicable a esa copia. El resultado se escribe junto al respaldo y se conserva la ficha original | Revisión 4 y revisión 5 del PO | C1.8, C3.5 |

## 4. Causas de fondo

| Causa | Observaciones que explica | En palabras simples |
|---|---|---|
| **R1. Se verifica solo lo que la base ya conoce, y solo con conteos** | B01, B05, B09 | El inspector revisa los papeles de la carpeta, pero no tiene una lista de lo que debería haber, y cuenta hojas en vez de leerlas |
| **R2. El cegado se declara tabla por tabla, sin regla de completitud** | B02, N1, N2 | Cada puerta tiene su llave, pero nadie revisa que no quede una ventana abierta |
| **R3. Algunas reglas solo las cumple el cargador, no la base** | B03, B04, B09 | Si el cargador se equivoca, o alguien escribe a mano, la base lo acepta |
| **R4. Hay referencias guardadas que no se usan ni dicen qué protegen** | B06, B10, N3 | Hay una foto de cómo debía estar todo (la huella) y una copia de seguridad, pero nadie las compara de forma automática y la copia no dice de qué versión es |
| **R5. Procedimientos fuera del repositorio** | A06, N4 | Algunos pasos se hicieron con guiones temporales: otra persona no podría repetirlos |
| **R6. Controles que se leen mientras cambian** | N5, N6 | Un control que no toma un candado puede leer una base a medio cambiar, y una decisión que no se recuerda vuelve a abrirse |

## 5. Mis errores corregidos en este plan

Los dejo escritos para que no vuelvan a aparecer:

1. Escribí que DEV26 exige un experimento final por partición. No lo dice. Es la decisión **D3b**, tuya.
2. Escribí «métricas 1.1» para el manifiesto. Los números de versión son: `metricas.json` 2.1.0 y manifiesto 1.0.0.
3. En la versión 1 C2.7 pedía verificar la base nueva contra la huella de git del esquema anterior. Eso no puede dar «coincide».
4. En la versión 2 quité la prueba de duraciones de planes exclusivos de prueba (ACU-04 la recupera).
5. Afirmé que C1.6 cerraba N3. No lo cierra solo: hace falta el catálogo de reglas (ACU-11).
6. Dije que la prueba de cegado podía correr sobre la base candidata. Como la base es de solo agregar y la regla de preliminar impide pasar ESC-SINT-001 a prueba, no puede (ACU-03).
7. En la v2 dije que `validar_hito` no liga la selección. Sí liga el protocolo del experimento; lo que falta es ligarlo a la selección del modelo (ACU-07).

## 6. Etapas y tareas

### C0. Decisiones y comprobaciones de solo lectura

**Estado: cerrada el 2026-11-07.** Resultados:
- **Acta documental de cierre:** `docs/actas/2026-11-07-dev31-f4c-c0-cierre-documental.md`; registra las comprobaciones previas y sus límites, sin repetir consultas.
- **C0.1:** decisiones D1 a D15 aprobadas o aceptadas por el PO (D15 como riesgo aceptado).
- **C0.2:** revisión de la configuración por los archivos del servidor (`postgresql.conf`, `postgresql.auto.conf`, `pg_hba.conf`) y del servicio. Posteriormente `SHOW hba_file` respondió como `semaforo_lectura`, pero ese rol no pudo leer `pg_hba_file_rules`. Sigue pendiente la comprobación en vivo de las reglas con un rol autorizado; es opcional para el cierre de C0 y no debe confundirse con una confirmación ya hecha.
- **C0.3:** rechazo confirmado desde 192.168.1.36, dos direcciones IPv6 públicas y el nombre del equipo; `localhost` sí pide clave. Firewall sin reglas de entrada para 5432.
- **C0.4:** confirmado por el PO: Power BI y Python usan `localhost`.
- **C0.5:** rol `semaforo_panel` creado por el PO como `postgres`; verificado sin privilegios de administrador, sin pertenencias, con clave aceptada por el servidor y sin acceso a `semaforo` (esperado hasta C2).

**Pendiente sin etapa asignada:** el cambio de `listen_addresses` a `localhost` (D4, aprobada). Requiere reinicio del servicio y no está numerado en el plan; se incorporará como C0.6 cuando el PO lo ordene.

**Quién:** el PO, con comandos de solo lectura. **Riesgo:** bajo. **Esfuerzo:** corta.

- **C0.1 Decisiones D1 a D14** (sección 10).
- **C0.2 Configuración de red**, como administrador `postgres` y solo lectura: `SHOW hba_file`, `SHOW listen_addresses` y el contenido de `pg_hba_file_rules`. Se confirma que el archivo es el que usa el servicio y que no hay reglas que admitan otros equipos. Si `pg_hba_file_rules` no es legible para ese rol, se registra como *no verificado* y se consulta de otra forma.
- **C0.3 Prueba de aislamiento**, desde la misma laptop: conexión a la IP de red en vez de `localhost`. PostgreSQL debe rechazarla. Demuestra el aislamiento del lado de PostgreSQL; el firewall de Windows queda fuera.
- **C0.4 Otros proyectos:** confirmar cómo se conectan (directamente en la laptop, Docker o WSL). Si llegan desde otra dirección, el cambio de D4 los afectaría y se ajusta antes.
- **C0.5 Rol del panel `semaforo_panel`** (cambia la base; **solo con tu orden D8**). Lo crea una sola vez el administrador `postgres`, que ejecutas tú. Según el diseño, `semaforo_admin` no puede crear roles; se confirma con una consulta de solo lectura antes de pedir nada. La contraseña se genera en el equipo y se guarda fuera del repositorio.

### C1. Controles nuevos, sin cambiar el esquema

**Estado actualizado:** C1 cerrada el 2026-11-07. Después se reforzó C1.11 para comparar tres huellas y revertir también si P9 lanza una excepción. Las descripciones siguientes son los criterios del plan; la evidencia está en las actas de C1 y de ambas correcciones.

**Modelo:** Sonnet. **Riesgo:** bajo. **Esfuerzo:** dos sesiones.

| Tarea | Corrige | Qué se hace | Criterio de aceptación |
|---|---|---|---|
| **C1.1 Catálogo de fuentes** | B05, R1 | Un módulo enumera lo publicado en `datos/` por familia: casos, protocolos, escenarios escritos a mano y generados, conjuntos, particiones, corridas, métricas, búsquedas, etiquetas, comparadores, hitos y decisiones. Lo usan el cargador, `bd metricas` y `bd conciliar` | Un escenario generado se mide y se concilia sin error |
| **C1.2 Errores aislados por corrida** | B05 | Un manifiesto ilegible, un protocolo ausente o una carpeta incompleta da «no verificada: motivo» para esa corrida, y el lote sigue. `bd metricas` verifica una carpeta existente antes de darla por «ya publicada» | Una prueba por caso. El informe cuenta las corridas sin verificar |
| **C1.3 Cobertura en los dos sentidos** | B01 | `bd conciliar` parte del catálogo (C1.1), no de la base. Informa faltantes, sobrantes, excluidas con decisión, excluidas pendientes y archivos con alcance sin comprobar (C2.6). Con una base vacía el resultado es **incompleta** | Base vacía: *incompleta*, con todo lo publicado como faltante. Base real: *coincide*, 130 cargadas y 3 excluidas con decisión |
| **C1.4 Códigos de salida honestos** | B01 | `bd cargar` y `bd conciliar` salen con código distinto de 0 si hay pendientes o no cargables sin decisión | Pruebas por cada código |
| **C1.5 Decisiones en archivo** | B01, N5, ACU-09 | `bd decidir` escribe `datos/derivados/decisiones/<id>/decision.json` y su manifiesto. Contiene: la **ruta y la huella** del archivo excluido, el motivo, y el acta confirmada en git. `bd cargar` carga la decisión como unidad: marca el conflicto de esa ruta y huella como decidido (la base ya permite decidir un conflicto una sola vez). `_record_conflict` deja de volver a abrir conflictos decididos (N5). Una decisión de una huella vieja no se aplica al archivo modificado: el archivo queda pendiente | Tras reconstruir: 130 cargadas y 3 excluidas con decisión. Un archivo modificado con decisión vieja queda *pendiente*. Una decisión nueva para la versión nueva se acepta. Una segunda decisión sobre la misma ruta y huella se rechaza. Pruebas por cada caso |
| **C1.6 Verificación de solo lectura contra la referencia** | B06, N3, N6, ACU-01, ACU-10, ACU-18 | `bd verificar` toma el candado de sesión **compartido**. Si hay carga en curso, o un conflicto de versión, el resultado es *no concluyente*. Lee la base en una sola transacción de solo lectura y compara el `carga_id` de la última carga al inicio y al final: si cambió, *no concluyente*. Compara con la huella del último commit de `docs/bd/huellas.json` (o la indicada). Si la referencia es de **otra versión del esquema**, *no concluyente*, no *difiere*. Compara la huella de contenido, filas por tabla, archivos raíz y el catálogo de reglas (C1.10). No crea ni borra nada | Alteración del dueño detectada como *difiere*. Carga en paralelo: *no concluyente*. Referencia de otra versión: *no concluyente* |
| **C1.7 Conciliación en una instantánea** | B06, N6 | Lo mismo para `bd conciliar`, con candado compartido. La conciliación incremental queda para F6 | Prueba con carga en paralelo |
| **C1.8 Ficha y referencia de cada respaldo** | B10, ACU-15, ACU-22, ACU-24 | Para los respaldos nuevos, `bd respaldar` registra en la ficha: la versión del esquema; la huella del contenido **del mismo estado de la base que se exportó**; el `carga_id` cuando corresponda; el commit; y el sha256 del `.dump`. Mecanismo: la huella y el volcado se toman con la misma instantánea de lectura (transacción de solo lectura y `pg_dump --snapshot`), para que la ficha corresponda exactamente a lo exportado. La ficha sirve de referencia para la restauración de prueba. Para los dos respaldos antiguos, los archivos se conservan en sus ubicaciones y la ficha registra qué campos pudieron comprobarse. La huella histórica de `control.cargas` puede usarse como referencia solo si corresponde al estado que se quiso respaldar y se identifica la carga de origen; si esa relación no se puede establecer, el resultado de contenido queda *no comprobado*, aunque la restauración termine bien. La versión y la huella mencionadas en la v3.2 para esas copias son valores esperados hasta verificarlas individualmente. Cada campo tiene un estado (*verificado*, *declarado*, *no comprobado* o *desconocido*); ninguno afirma más de lo leído o restaurado | Ficha generada; ningún campo afirma más de lo verificado. Pruebas en C3.5 |
| **C1.9 Estado de la red** | B07, ACU-14 | `bd verificar --red` informa `listen_addresses`, `hba_file` y las reglas de `pg_hba.conf`, en solo lectura. Si el rol no puede leer las reglas, el resultado es *no verificado: lo consulta el administrador*, sin inventarlo | Con un archivo de reglas de ejemplo (analizador) y en la laptop real (C0.2) |
| **C1.10 Catálogo de reglas instaladas** | N3, B02, ACU-11 | La huella de referencia incluye: disparadores y si están activos, seguridad por filas, políticas, permisos por rol, definiciones de funciones y vistas, y los `GRANT`. `bd verificar` las compara | Regresión: **desactivar un disparador sin tocar datos debe fallar**; cambiar una política debe fallar |
| **C1.11 `bd reconstruir` seguro** | A06, N4, B10, ACU-02, ACU-17 | Exige la carpeta del repositorio. Crea la base candidata con **nombre temporal** y la llena con el proceso de la sección 6.2 (P0 a P9). Cambia el nombre solo si coinciden la versión del esquema, la huella de contenido y la huella de reglas aprobadas por el PO (D11). La base vigente pasa a `semaforo_anterior_<fecha>` y **no se borra** sin tu confirmación (D12). Si falla el cambio de nombre o la verificación P9, intenta revertir. Si también falla la reversión, informa que el estado de las bases debe comprobarse. Nunca toca otras bases | Pruebas con bases temporales: fallo del segundo cambio, diferencia o excepción en P9, y fallo adicional de la reversión |
| **C1.12 Guiones versionados** | A06, N4 | Los ensayos de daño de F2 a F4 pasan a `scripts/mutaciones/` con su índice | Están en el repositorio y se pueden repetir |

### C2. Diseño corregido, con una sola reconstrucción

**Modelo:** Opus (seguridad e integridad). **Riesgo:** medio. **Esfuerzo:** dos sesiones.

| Tarea | Corrige | Qué se hace | Criterio de aceptación |
|---|---|---|---|
| **C2.1 Cola con arreglos nativos** | B09, ACU-12 | `integer[]` para vehículos, `double precision[]` para tiempos y `boolean[]` para la ventana. Reglas declaradas: sin nulos, sin negativos, sin valores no finitos. Un disparador exige tiempos estrictamente crecientes y el mismo largo en los tres arreglos. En Python, `QueueSeries` exige lo mismo. La carga escribe cada serie por su ruta normal, sin matrices en `unnest`. Hay que extender el vocabulario de tipos del diseño y el cargador | Pruebas por la ruta normal: dos corridas de longitud distinta; un nulo, `NaN`, infinito, negativo o texto se rechaza; la vista sigue dando 1 911 000 filas |
| **C2.2 Conciliación por contenido** | B09, B01 | Cada arreglo se compara exacto con `metricas.json`. Se compara por clave el contenido de `resultados_acceso`, `resultados_movimiento`, vehículos (identificador, cohorte, movimiento y demora recalculada) y eventos | Dos valores intercambiados y un valor cambiado se informan como *difiere* |
| **C2.3 Todos los accesos medidos** | B08 | `resultados_acceso` tiene una fila por cada acceso de la zona. Las columnas de cohorte quedan vacías sin vehículos de la cohorte, y `con_cohorte` lo dice. Una regla impide mezclar «sin cohorte» con valores de demora | Los 3 accesos aparecen con su cola y sin demora |
| **C2.4 Protocolo ligado a las métricas** | B04, ACU-13 | `manifiesto.json` de métricas pasa a versión **1.1.0**, con la huella del protocolo. `metricas.json` (2.1.0) no cambia. El cargador y la conciliación comprueban la huella. Las 130 publicaciones actuales (manifiesto 1.0.0) siguen legibles y se marcan «sin huella registrada». Regla: en búsqueda, finalistas y final, el protocolo de las métricas es el de la corrida | Una corrida de búsqueda con métricas de otro protocolo se rechaza. Una huella distinta se informa. Las 130 actuales se leen sin cambios |
| **C2.5 Selección congelada** | B03, ACU-07, ACU-08 | (a) El hito de congelar el modelo fija `seleccion_id` y la huella de la selección. (b) La selección exige protocolo no nulo, y ese protocolo debe estar **congelado antes del modelo**. (c) Una selección por modelo (índice único sobre el modelo ganador). (d) La apertura exige la **misma** selección fijada en el hito, y comprueba que su partición, protocolo y modelo coinciden con los del experimento. (e) Si D3b es «sí», una partición tiene un solo experimento final; si es «no», la apertura libera solo su experimento (ACU-08). (f) Un hito de selección registrado después del congelado del modelo no cambia nada: el modelo y el experimento siguen apuntando a la selección fijada | Pruebas: otra selección registrada después de congelar el modelo (se rechaza al abrir); modelo de otra partición; protocolo ajeno ya congelado; selección sin protocolo; selección congelada después del modelo; apertura válida |
| **C2.6 Cegado completo** | B02, N1, N2, R2, ACU-04, ACU-05, ACU-06 | (a) Regla del diseño: toda tabla con relación hacia una tabla cegada debe estar cegada o tener escrito `visible_porque`. Lo exige `bd_esquema.py` y la puerta de calidad. (b) `simulacion.planes` y `plan_tramos` se ven solo si algún uso visible los menciona: corrida, candidato, etiqueta, comparador, consulta, comparación o plan observado. La regla se genera desde las relaciones. (c) **Alcance de archivos:** `control.artefactos` gana `alcance` (`global`, `escenarios`, `desconocido`) y la tabla de enlace `control.archivo_escenarios`. Un archivo es visible si es `global`, o si es `escenarios` y **todos** sus escenarios son visibles. Queda **oculto hasta abrir la prueba** si es `desconocido`, si es `escenarios` sin enlaces válidos, o si mezcla escenarios de desarrollo y de prueba (D9). Abrir una prueba libera solo los archivos cuyo alcance está comprobado. (d) `control.replicas` se ciega por sus dos corridas. (e) `evaluacion.diferencias` se ve solo si el lector ve **los dos lados** (hoy solo mira el A). (f) `experimento.asignaciones`, `control.escenarios_cegados` y `control.hitos` siguen visibles, con la razón escrita (ADR07). (g) **Rol `semaforo_panel`** (C0.5): sin permiso sobre tablas; solo sobre vistas aprobadas. Cada vista aprobada se revisa como superficie propia | Ver C3.2 y las pruebas de consulta directa denegada y de archivo mixto |
| **C2.7 Reconstrucción única** | todas, ACU-01, ACU-02, ACU-03 | Con `bd reconstruir` (C1.11), siguiendo la secuencia de la sección 6.2 | Todo en *coincide*. Ningún cambio de nombre sin las puertas aprobadas |

### 6.2. Proceso de la reconstrucción (C2.7)

Cada paso tiene una puerta. Hasta P7, si falla, se detiene sin cambiar el nombre de la base vigente. P8 y P9 intentan revertir cualquier cambio de nombre fallido; si también falla la reversión, se informa el estado incierto y se comprueba antes de continuar. No se promete que la base vigente nunca cambie durante esos dos pasos.

| Paso | Qué se hace | Puerta |
|---|---|---|
| **P0** | `bd verificar` sobre la **base vigente** contra git (C1.6) | La vigente coincide con su referencia de git. Si *difiere*, se detiene |
| **P1** | Crear la **candidata** con nombre temporal (`semaforo_candidata_<fecha>`), con el esquema corregido, los mismos permisos y `bd cargar --base` | Esquema y permisos verificados |
| **P2** | Cargar lo existente en la candidata, con repositorio | Sin rechazos. Excluidas con decisión: 3 |
| **P3** | Conciliación por contenido de la candidata (C2.2) y cobertura (C1.3) | 130 cargadas, 3 excluidas con decisión, 0 *difiere* |
| **P4** | Regenerar una segunda candidata con el mismo proceso | Misma huella (QA36) |
| **P5** | Registrar la versión y la huella de la candidata **antes** de generar su respaldo, para que la referencia corresponda al estado que se exporta. Respaldar; restaurar ese respaldo en una base temporal; recalcular la huella a partir de sus tablas | P5 pasa solo si el sha256 del archivo coincide, la restauración termina bien y la versión y la huella recalculada coinciden con la referencia registrada antes del respaldo. *No comprobado* detiene el proceso antes del cambio de nombre |
| **P6** | **Pruebas de cegado y seguridad** de C3.1 y C3.2, en una **base desechable** con el mismo esquema, permisos y catálogo (comparado por huella). Sobre la candidata, solo consultas de solo lectura | Todas las pruebas pasan |
| **P7** | Calcular y presentar al PO la versión del esquema, la huella de contenido y la huella de reglas de la candidata | **D11**: el PO aprueba esos tres valores solo si P0 a P6 pasan |
| **P8** | Cambio de nombre con reversión: vigente → `semaforo_anterior_<fecha>`; candidata → `semaforo`. Si el segundo paso falla, se revierte. La reversión se prueba antes en la base desechable | El cambio queda confirmado y la vigente conservada |
| **P9** | Verificación posterior de la base nueva contra los tres valores aprobados en P7. Si hay diferencia o la verificación lanza una excepción, se intenta restaurar la base anterior; si la reversión falla, se informa el estado por comprobar. Tras una coincidencia se escribe `docs/bd/huellas.json` como commit aparte | Coinciden esquema, contenido y reglas |

### C3. Pruebas, evidencia y cierre

**Modelo:** Sonnet. **Riesgo:** bajo. **Esfuerzo:** una o dos sesiones. Las pruebas de C3.1 y C3.2 que insertan datos se ejecutan **en bases desechables** (`semaforo_pruebas_*`), nunca en la candidata ni en la base vigente.

- **C3.1 Una prueba por observación** que reproduce el escenario del auditor: base vacía (B01); ESC-SINT-001 cegado con planes y archivos (B02); modelo de otra partición, protocolo ajeno y selección posterior (B03); métricas de otro protocolo (B04); escenario generado y manifiesto ilegible (B05); alteración del dueño con carga en paralelo (B06, N3); reglas de red de ejemplo (B07); acceso sin cohorte (B08); negativo, texto, intercambio y valor cambiado en la cola (B09); respaldo de otra versión (B10); réplica de una corrida de prueba (N1); conflicto decidido que vuelve a aparecer (N5); carga y verificación en paralelo (N6). **Pruebas nuevas de la revisión:** consulta directa denegada al rol del panel; archivo mixto; archivo de alcance desconocido; diferencia con un lado cegado; decisión antigua con archivo modificado; reglas instaladas (desactivar un disparador sin tocar datos); `bd reconstruir` sin carpeta de repositorio rechazado; referencia de otra versión (*no concluyente*).
- **C3.2 Barrido de cegado genérico.** Todos los identificadores del escenario de prueba (escenario, corridas, búsqueda, archivos) llevan una marca. Se recorren **todas** las tablas y vistas, columna por columna, como lector y como `semaforo_panel`. La prueba falla si la marca aparece fuera de las columnas justificadas. Además, **las duraciones de los planes exclusivos de la prueba** no pueden aparecer en ninguna vista, aunque no aparezca su identificador (ACU-04). Al abrir la prueba con sus hitos, todo aparece. Las tablas futuras entran solas al barrido.
- **C3.3 Ensayo de daño versionado** sobre todos los controles nuevos (meta: 100 % detectado; lo que sobreviva se explica o se cierra con una prueba).
- **C3.4 Puerta de calidad completa** con PostgreSQL.
- **C3.5 Evidencia, en tres comandos:**
  - `bd verificar`: solo lectura, sin crear bases (C1.6).
  - `bd probar-respaldo --respaldo <ruta>`: verifica un respaldo específico con el procedimiento de seis pasos de abajo. Crea una base temporal y la borra al terminar. No toca la base vigente ni otra base. Escribe su resultado en un archivo de verificación al lado del respaldo; la ficha original no se reescribe.
  - `bd evidencia`: une ambos con cobertura, conciliación, barrido y red, en `datos/reportes/bd/<fecha>/`, con manifiesto y huellas. Lo puede volver a ejecutar el auditor.
**Procedimiento de `bd probar-respaldo`** (C3.5):

1. **Seleccionar el archivo.** Usar la ruta indicada con `--respaldo`. Si se omite, seleccionar el respaldo más reciente de la versión vigente.
2. **Comprobar el archivo.** Calcular el SHA-256 del `.dump` y compararlo con su `.sha256`. Si falta la referencia o el valor difiere, detener la prueba antes de restaurar y registrar el motivo.
3. **Restaurar en una base temporal.** Si la restauración falla, registrar «restauración fallida» y el motivo. El procedimiento elimina únicamente la base temporal que creó.
4. **Identificar el esquema y recalcular la huella.** Obtener la versión instalada en la base temporal. Calcular la huella leyendo sus tablas, con el catálogo, el orden y las exclusiones que correspondan a esa versión. Si el verificador no puede reproducir el cálculo para ese esquema, registrar «contenido no comprobado» y su causa.
5. **Comparar con la referencia del respaldo.** Para una copia nueva, usar la ficha generada al respaldar. Para una copia histórica, usar la referencia asociada a esa copia cuando pueda identificarse. Una versión antigua puede obtener «coincide» al compararse con su propia referencia. Si la versión restaurada o la huella recalculada difieren de las esperadas para esa copia, registrar «difiere» e indicar qué campo cambió. Si falta una referencia válida, registrar «contenido no comprobado».
6. **Guardar la evidencia.** Registrar la ruta, la fecha, el commit del verificador, el resultado del SHA-256 del archivo, el resultado de la restauración, la versión detectada, la huella calculada, la huella esperada y su procedencia. Mantener separados los resultados de archivo, restauración y contenido.

- **C3.6 Acta**, matriz de la sección 8 completada con evidencia, `CONTEXTO.md`, memoria y commit. El push y la nueva auditoría, a pedido del PO.

### 6.3 Después de C3

- **F5 (panel)** se conecta con `semaforo_panel` y lee solo vistas aprobadas. Muestra procedencia, cobertura, métricas ausentes, accesos sin cohorte y archivos con alcance pendiente (QA37).
- **F6 (ensayos de cierre)** mide a escala de DEV16: carga, conciliación completa, conciliación incremental (solo lo cargado desde la última verificación) y tiempo de las reglas de cegado.

### 6.4 Conciliación incremental

Queda para F6 (ACU-19). Dos reglas desde ahora, para no rehacer el diseño: la incremental nunca reemplaza a la completa, y cada verificación incremental registra desde qué `carga_id` cubre.

### 6.5 Criterios de aceptación para cerrar B10

| Caso | Resultado esperado |
|---|---|
| Respaldo de la candidata con su ficha | Archivo íntegro, restauración exitosa y contenido coincidente. P5 pasa. |
| Cada uno de los dos respaldos antiguos, elegido por ruta | Resultado individual, con la versión detectada y la fuente de la referencia documentadas. |
| Respaldo histórico restaurado sin una referencia válida | Restauración exitosa y contenido «no comprobado». |
| Archivo cuyo SHA-256 difiere del registrado | La prueba se detiene antes de restaurar. |
| Copia de prueba que se restaura pero tiene una fila cambiada y conserva la referencia de contenido original | El recálculo detecta «difiere», aunque la restauración haya terminado correctamente. Este caso comprueba que el comando lee las tablas. |

## 7. Esfuerzo, riesgo y modelo

| Etapa | Complejidad | Riesgo | Esfuerzo | Modelo |
|---|---|---|---|---|
| C0 | Baja | Bajo | Corta, con el PO | — |
| C1 | Media-alta | Bajo | Dos sesiones | Sonnet |
| C2 | Alta | Medio | Dos sesiones | Opus |
| C3 | Media | Bajo | Una o dos sesiones | Sonnet |

**Total estimado:** cinco o seis sesiones.

**Riesgos de ejecución y cómo se cubren:**
- **Vistas aprobadas con permisos del dueño** pueden dejar ver más de lo debido si se diseñan mal. Cada vista se revisa, y C3.2 la prueba como `semaforo_panel`.
- **Cegado por uso y por alcance** puede hacer lentas las consultas con DEV16. Se mide en F6, y hay un índice por cada relación.
- **Arreglos en la ruta normal de carga** tocan el cargador. Lo cubren las pruebas con series de distinta longitud y el ensayo de daño.
- **Candado compartido** puede demorar una verificación si hay una carga larga. Se informa como *no concluyente*, no se espera en silencio.
- **Reconstrucción:** las medidas de protección de la sección 1 reducen el riesgo, pero no lo eliminan. El riesgo residual es un fallo no previsto durante el cambio o un error al confirmar un borrado (D12).
- **Otros proyectos con PostgreSQL:** si alguno llega desde otra dirección, el cambio de D4 lo afectaría. Se confirma antes en C0.4.

## 8. Matriz de trazabilidad

| Observación | Causa | Tareas | Prueba de regresión | Criterio QA |
|---|---|---|---|---|
| B01 | R1 | C1.1, C1.3, C1.4, C1.5, C2.2 | base vacía, corrida omitida, decisiones con y sin archivo modificado | QA33 |
| B02 | R2 | C2.6, C1.10 | barrido de cegado como lector y como panel; consulta directa denegada | QA35 |
| B03 | R3 | C2.5 | selección posterior, modelo de otra partición, protocolo ajeno, selección sin protocolo | QA35 |
| B04 | R3 | C2.4 | métricas de otro protocolo y huella distinta | QA33 |
| B05 | R1 | C1.1, C1.2 | escenario generado, manifiesto ilegible, carpeta incompleta | QA33 |
| B06 | R4 | C1.6, C1.7 | alteración del dueño y carga en paralelo | QA36 |
| B07 | — | C0, C1.9 | reglas de red de ejemplo y laptop real | QA34 |
| B08 | R6 | C2.3 | acceso sin cohorte | QA33, QA37 |
| B09 | R1, R3 | C2.1, C2.2 | negativo, texto, nulo, no finito, distinta longitud, intercambio | QA33 |
| B10 | R4 | C1.8, C1.11 | respaldo de otra versión y restauración probada | QA36 |
| N1, N2 | R2 | C2.6 | barrido de cegado | QA35 |
| N3 | R4 | C1.10, C1.6 | desactivar disparador sin tocar datos | QA34, QA36 |
| N4, A06 | R5 | C1.11, C1.12 | `bd reconstruir` con reversión | QA36 |
| N5 | R6 | C1.5 | conflicto decidido que no vuelve a aparecer | QA33 |
| N6 | R6 | C1.6, C1.7 | carga y verificación en paralelo | QA36 |

## 9. Riesgos residuales que quedarían aceptados y escritos

1. **Los nombres de los escenarios de prueba son visibles** (ADR07). No revelan datos.
2. **El dueño de la base es de confianza.** Puede cambiar el esquema; no se impide, pero se **detecta** con `bd verificar` contra la huella de git (C1.6 y C1.10).
3. **Los conteos de filas por carga** (`control.cargas`) muestran cuántas filas se cargaron, incluidas las de prueba, pero no su contenido.
4. **Tres carpetas históricas de formato desconocido** de DEV00 (`f3-pruebas`, `f4-pruebas`, `R0-provisional`) se dejan como están y documentadas.
5. **Tiempos a escala de DEV16** estimados hasta F6.
6. **La red**, según lo que decidas en D4 y lo que confirme C0.2 y C0.3.
7. **Acceso público de los roles del proyecto a otras bases** (N7, D15): aceptado por el PO, porque la laptop es de uso único y siempre se conecta en redes cerradas donde el PO es el único conectado.

## 10. Decisiones del PO

**Estado al 2026-11-07:** el PO aprobó D1 a D14 con la recomendación indicada en cada fila. D8 y D12 tienen un efecto posterior: D8 se ejecuta solo en C0.5 y D12 mantiene la base anterior hasta que F5 esté verificado. Aprobar una decisión no equivale a ordenar una etapa.

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| D1 | ¿Se aprueba la v3.3 y su ejecución en el orden C0 a C3? | Sí, completo / solo C1 / otro orden | **Sí**, con tu orden expresa en cada etapa (ACU-21) |
| D2 | B02: qué ve el lector de los escenarios de prueba | (a) solo los nombres; se ocultan planes, archivos, réplicas y diferencias / (b) dejarlo como está | **(a)**. Lo exige QA35 y respeta ADR07 |
| D3 | B03: cómo se liga el modelo a su protocolo | (a) por la selección, con `seleccion_id` fijado en el hito, protocolo obligatorio y congelado antes del modelo / (b) agregar el protocolo a los conjuntos | **(a)** |
| D3b | ¿Un solo experimento final por partición? | Sí / no | **Sí**. Es tu decisión: DEV26 separa la prueba, pero no fija esta restricción. Si respondes «no», la apertura libera por experimento y el cegado cambia (ACU-08) |
| D4 | B07: la red | (a) cambiar `listen_addresses` a `localhost`, después de C0.2 a C0.4 / (b) dejarlo y registrar la excepción | **(a)**. Requiere reiniciar el servicio un momento, y te doy los pasos exactos. Si prefieres (b), queda como riesgo aceptado |
| D5 | B09: cómo se guarda la cola | (a) arreglos nativos de PostgreSQL / (b) JSON con reglas de valores | **(a)**. El tipo impide textos, las reglas se declaran en el diseño y la vista es más simple. Cuesta extender el cargador |
| D6 | B04: huella del protocolo | Sí (manifiesto de métricas 1.1.0) / no | **Sí**. Las 130 actuales se leen sin cambios |
| D7 | Las 3 corridas de DEV00 | «riesgo aceptado» como decisión verificable (archivo con acta y huella) / dejarlas pendientes | **Riesgo aceptado**, como decisión verificable (C1.5) |
| D8 | Rol del panel `semaforo_panel` | Crearlo una vez como `postgres` (tú), en el paso C0.5 / no tener rol de panel | **Crearlo**, en su paso propio. El panel no tiene permisos de tabla |
| D9 | Archivos que mezclan escenarios de desarrollo y de prueba | (a) ocultos hasta abrir la prueba / (b) visibles con sus nombres | **(a)** |
| D10 | Versión del manifiesto de métricas | 1.1.0 con huella del protocolo / no cambiar versión | **1.1.0**, sin tocar `metricas.json` |
| D11 | Versión del esquema, huella de contenido y huella de reglas de la candidata (P7) | Aprobar después de P0 a P6 / no aprobar | **Aprobar los tres valores** solo si P0 a P6 pasan. Es el punto en que se decide la base nueva |
| D12 | Borrar la base anterior `semaforo_anterior_<fecha>` | Después de tu confirmación, en una fecha posterior / conservarla | **Conservarla** hasta que F5 esté verificado; luego borrarla con tu confirmación |
| D13 | Aprobada por el PO (2026-11-07): el algoritmo de la huella queda versionado en la ficha y en `huellas.json` (`algoritmo_huella`). Si no coincide, la respuesta es *contenido no comprobado: algoritmo distinto* | (a) versionarlo / (b) no versionarlo | **(a)**. El algoritmo no cambió desde F3 (`verificacion.py`, commit `d66b723`). Versionarlo evita que una reforma futura convierta una huella válida en *difiere* |
| D14 | Aprobada por el PO (2026-11-07): una huella histórica de `control.cargas` solo sirve como referencia si la última carga de la base restaurada está completada, tiene huella registrada y no tiene cargas posteriores | (a) esa regla / (b) aceptar cualquier carga anterior | **(a)**. Sin esa regla, una huella antigua podría atribuirse a un respaldo que no corresponde |
| D15 | **Riesgo aceptado por el PO (2026-11-07)** (hallazgo N7): los roles del proyecto conservan el acceso público por defecto a las bases BankData, postgres, restaurant_manager, tickers_report_db y trading_predict. No se cambia nada | (a) quitar el acceso público a esas bases / (b) aceptar el riesgo | **(b), aceptado.** Motivo del PO: la laptop es de uso único y siempre se conecta en redes cerradas donde el PO es el único conectado. Sin permisos dentro de esas bases, hoy no hay datos expuestos. Se revisa si cambia el uso de la laptop o aparece otro usuario |

## 11. Fuera de este plan, con su fase

- **DEC06 regla C** en el código de selección (requisito antes de producir etiquetas en DEV16).
- **Documento 01, matrices y validador de contratos** con HU15 y QA32 a QA37, y **DEC09/ADR12**: F7.
- **Word y tesis v2.6**: F8.
- **A07** (ADR01 a ADR08 como propuestas) y **A08** (cierre formal de DEV04).
- Validación de aforos y de Webster (**DEC08**), geometría de Javier Prado y **DEC07**.
