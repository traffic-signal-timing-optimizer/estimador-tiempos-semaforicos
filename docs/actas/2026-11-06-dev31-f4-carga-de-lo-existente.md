Escrito para: el Product Owner (revisión de F4) y el equipo técnico (F5 a F8 de DEV31).

# DEV31 F4: carga de lo existente, conciliación y cegado con datos reales

- **Fecha:** 2026-11-06
- **Tarea:** DEV31 (historia propuesta HU15). Orden de fases: sección 13 de `docs/actas/2026-11-05-plan-base-de-datos.md`.
- **Estado:** hecho y **pendiente de tu revisión**. La base `semaforo` ya tiene los datos existentes. En `datos/` solo se **agregaron** carpetas nuevas de solo lectura con las métricas que faltaban (`derivados/metricas`): las 133 corridas no se tocaron. `documentacion/` no se tocó.
- **Modelo:** Sonnet. **Complejidad:** media. **Riesgo:** bajo. **Esfuerzo:** una sesión.

## Qué se hizo

### 1. Métricas que faltaban (`bd metricas`, comando nuevo)

Las 133 corridas son anteriores a F2 y no tenían `metricas.json`. El comando las calcula con el código oficial (`evaluate_run`) y las publica como carpetas **nuevas** de solo lectura. Las 130 corridas con entradas de DEV06 quedaron medidas, en 50 MB:

| Grupo | Corridas | Protocolo con que se midió | Cómo se eligió |
|---|---|---|---|
| Piloto de DEV14 | 102 | `CASO001_DEV14_PILOTO` | Es el protocolo de la búsqueda que las usó (sale de su traza) |
| Sueltas de DEV19, zona de 7 calles | 14 | `CASO001_DEV19_BORRADOR` | Es el único protocolo con exactamente esa zona |
| Sueltas de DEV19, zona de 21 calles | 14 | `CASO001_DEV19_BORRADOR_APROXIMACION` | Dos protocolos tienen esa zona; elegí el que el cierre de DEV19 documenta para esas corridas |
| Corridas de DEV00 | 3 | — | No tienen escenario ni entradas de DEV06: no se pueden medir ni cargar |

**Corrección a lo que dije en F3:** las 28 sueltas **sí se pueden medir**. En F3 las probé con el protocolo equivocado (el del piloto, que exige carriles que sus carpetas no registraron).

**Regla del protocolo para una corrida suelta:** el protocolo cuya zona coincide *exactamente* con la que registró la corrida. Si hay varios, hay que nombrarlo con `--protocolo`; si no, la corrida se deja sin medir y se dice por qué. Los dos protocolos de 21 calles miden exactamente igual (solo cambian la búsqueda y las semillas), así que esa elección **no cambia ninguna cifra**.

### 2. Carga real de la base (`bd cargar --preliminar --sueltas`)

Autorizaciones que diste: el escenario ESC-SINT-001 se cargó **como preliminar** y las 28 sueltas **no se dejaron fuera**.

| Qué | Cifra |
|---|---|
| Archivos leídos / cargados / rechazados | 2 696 / 2 615 / 0 |
| Corridas | **130**: 63 de búsqueda, 39 de finalistas y 28 de diagnóstico |
| Vehículos | 231 400 |
| Cola segundo a segundo | 1 911 000 filas |
| Resultados por acceso / por movimiento | 520 / 2 600 |
| Búsqueda del piloto | 1 búsqueda, 21 candidatos, 102 resultados por semilla y 1 etiqueta («sin referencia») |
| Caso, protocolos, escenario, comparadores | 1 caso, 3 protocolos con 41 semillas, 1 escenario preliminar y 1 publicación de comparadores |
| No cargables | 3 (las corridas de DEV00), registradas con su motivo en `control.conflictos` |
| Tamaño de la base | 669 MB. Huella de contenido: `05caa0be…3e3f` |

### 3. Conciliación con los archivos (`bd conciliar`, comando nuevo; QA33)

Compara la base con los archivos por otro camino que el cargador:

1. cada archivo íntegro que conoce la base existe, pesa lo mismo y da la misma huella;
2. los conteos de cada corrida (vehículos, vehículos de la cohorte, eventos del registro de SUMO, filas de cola, de accesos y de movimientos, y los vehículos en cola de la ventana de medición);
3. **vuelve a calcular las métricas de cada corrida desde sus archivos** y compara cada columna de métricas con la base.

**Resultado con tus datos: 2 615 archivos, 130 corridas recalculadas, 0 diferencias.**

### 4. Verificación y respaldo

| Comprobación | Resultado |
|---|---|
| `bd verificar --regenerar` (QA36) | La base regenerada desde los archivos en otra base temporal dio **la misma huella**. 268 archivos raíz revisados, 0 cambiaron |
| `docs/bd/huellas.json` (ADR03) | 49 KB, 333 líneas: la huella de cada archivo raíz y la de contenido de la base. **Listo para confirmar en git**; la fecha externa la da el push, que pides tú |
| `bd respaldar` | `D:\respaldos\semaforo\20261106T231427Z.dump` (14 MB) con su `.sha256` al lado |

### 5. Cegado con datos reales (QA35)

En `datos/` todavía no hay una partición publicada. Lo ensayé en una base temporal (ya borrada): asigné ESC-SINT-001 a «prueba» y cargué todo lo demás. En las **14 tablas** y las **5 vistas** con datos de prueba, quien carga ve todo (por ejemplo 231 400 vehículos y 1 911 000 filas de cola) y **quien solo lee ve cero**. Abrir la prueba con datos reales no se pudo ensayar: exige un protocolo, una partición y un modelo congelados que todavía no existen; ese orden se prueba con datos sintéticos desde F3.

## Cómo se verificó

- **Puerta de calidad:** `ruff` y `pyright` limpios; esquema al día; **5 315 pruebas pasan** (1 omitida, solo para sistemas que no son Windows; 16 más que en F3); contratos **43/43**; ningún archivo de código oculto a git.
- **Pruebas nuevas:** 6 sin base de datos (elección del protocolo y qué corridas se pueden medir) y 10 con corridas reales de SUMO (publicar métricas; coincidencia de la base con los archivos; y un archivo cambiado con el mismo tamaño, una marca de cohorte cambiada, un evento de más, una serie de cola republicada distinta y una carpeta de métricas alterada).
- **Ensayo de daño a propósito:** **13 roturas, 13 detectadas**. La primera vez solo se detectaron 7: seis comprobaciones no tenían ninguna prueba que las notara (huella del archivo, vehículos de la cohorte, eventos, filas de cola, protocolo de la búsqueda y corridas fallidas). Agregué las seis pruebas y ahora se detectan. El guion está en la carpeta de trabajo de la sesión (`f4_danio.py`).
- **Un ajuste de código:** si una carpeta de métricas está alterada, la conciliación lo informa en vez de detenerse.
- **Temporales:** borré la copia de ensayo de F3 (2,5 GB), todas las bases temporales y los archivos de ensayo.

## Lo que se encontró

1. **La cola segundo a segundo pesa 4 veces más de lo estimado en F0.** Medido con tus datos: 4,3 MB por corrida (561 MB en total, con sus índices) frente a 1 MB estimado. Para las 4 692 corridas de DEV16 serían unos **20 GB** solo de cola (el total de la base, unos 26 GB), no los 5 GB estimados. La causa es que cada fila repite dos textos largos (la carga y el archivo de origen). F0 dijo que esto se decidía ahora, con datos reales, y lo medí con la alternativa:

   | Forma de guardarla | Peso con las 130 corridas | Serie de un acceso de una corrida | Un resumen de cada una de las 130 corridas |
   |---|---|---|---|
   | Una fila por segundo (hoy) | 561,6 MB | 1,7 ms | 957 ms (cola media de la ventana) |
   | Un arreglo por acceso | **1,9 MB** (292 veces menos) | 0,4 ms | 211 ms (cola máxima) |

   Los dos resúmenes no son el mismo cálculo, así que la comparación de tiempos es aproximada; la del peso, no. Las tablas de la alternativa fueron temporales y ya no existen.

   El espacio no es el problema (D: tiene 422 GB), pero pesa en la carga, el respaldo y las consultas. Mi recomendación es cambiar a **un arreglo por acceso**. Como el panel y las consultas leen siempre la vista `vistas.cola_por_segundo`, que mostraría lo mismo, ninguna consulta cambia. Es un cambio al esquema aprobado en F1, así que lo decides tú. **Pregunta 2.**
2. **Las métricas publicadas llevan el código con cambios sin confirmar.** Su manifiesto dice commit `d66b723` con `code_modified: true`, porque las calculé con el código de F4 antes de confirmarlo. No cambia ninguna cifra, pero queda dicho en el manifiesto. Con este commit el código queda confirmado.
3. **Las 3 corridas de DEV00 quedan como conflicto pendiente** (`not_loadable`) en `control.conflictos`. Es lo correcto: son corridas de recepción, sin escenario. Si quieres marcarlas como «riesgo aceptado», falta un comando pequeño para registrar esa decisión; lo propongo para F6.
4. **Tres accesos de la zona no tienen vehículos de la cohorte** (`1185174556`, `1436359637#0` y `563085958`): su cola está en `cola_segundo`, pero no en `resultados_acceso`. Sigue como cambio al diseño para F7.
5. **Quien solo lee ve el nombre de los escenarios de prueba** (`control.escenarios_cegados` y las asignaciones), pero ninguno de sus datos. Es parte del diseño aprobado en F1.
6. **Tiempos:** la carga completa tarda unos 4 minutos (248 s en el ensayo con los mismos datos; unos 2 s por corrida). Para DEV16 serían unas 2,5 horas la primera vez, y unos segundos las siguientes.
7. **Pendiente de F7 (documentación):** la tabla de `docs/bd/diccionario.md` seguirá igual hasta que decidas la pregunta 2.

## Lo que pido al PO

1. ¿Apruebas F4?
2. ¿Cambio la cola a **un arreglo por acceso**? Recomiendo que sí, antes de DEV16. Se haría como un paso corto aparte: cambiar el esquema, el cargador y las pruebas; crear una base nueva; recargar (4 minutos) y repetir la conciliación.
3. ¿Confirmo `docs/bd/huellas.json` en git (ADR03) junto con este commit? Lo hago ahora salvo que digas lo contrario. El push sigue siendo a tu pedido.
4. ¿Ejecuto F5 (panel estático)? Recomiendo **Sonnet**, como dice el plan. Conviene decidir antes la pregunta 2, porque el panel lee la cola.
