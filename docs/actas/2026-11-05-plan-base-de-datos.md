Escrito para: el Product Owner (decisiones), el asesor (porque cambia el diseño técnico de la tesis) y el equipo técnico (ejecución).

# Plan: base de datos de la evidencia y panel de resultados (cambio de alcance)

- **Fecha:** 2026-11-05
- **Estado:** propuesto. **Sin código y sin cambios en `documentacion/`.** Espera el OK del PO y las decisiones de la sección 11.
- **Origen:** pedido del PO del 2026-11-05: antes de seguir con DEV16, tener una base de datos relacional con todas las entradas y salidas de las pruebas, para respaldar la tesis ante el asesor y el jurado, y un panel simple para verla.
- **Qué es:** un **cambio de alcance**. Hoy la documentación excluye las bases de datos (sección 7). Según `documentacion/FUENTES_Y_PRECEDENCIA.md`, un cambio de alcance se registra con su impacto antes de modificar tareas, contratos o evaluación. Este plan es ese análisis de impacto; F0 lo convierte en acta y cambia los documentos.
- **Identificadores propuestos:** historia HU15 (requisito RF15), tarea DEV31, decisión de arquitectura ADR12 y pruebas QA32 a QA37.
- **Tamaño:** L (grande). Complejidad media-alta, esfuerzo alto, riesgo medio. El modelo sugerido por fase está en la sección 9.

## 1. Qué pidió el PO y qué se ajusta

| Lo que planteó el PO | Lectura del equipo |
|---|---|
| La base debe tener dos alcances: los datos de las pruebas de entrenamiento y lo que arroja el modelo entrenado | Correcto, pero se queda corto. Son **cinco etapas**, y la que más respalda la tesis es la quinta: (1) el caso y sus datos de campo; (2) la fabricación de ejemplos: escenarios, simulaciones de SUMO y búsqueda del mejor plan; (3) el entrenamiento; (4) las consultas al modelo; (5) la **comprobación en SUMO** de lo que sugiere el modelo, frente al plan vigente y a Webster. Lo que el modelo sugiere no prueba nada por sí solo: la prueba es que, al simular su plan, la demora baje. |
| Las pruebas de entrenamiento darán métricas de cómo va mejorando el modelo | Casi. El modelo **no mejora solo con el uso**: no aprende de las consultas. Mejora cuando se entrena una versión nueva, con más escenarios u otra configuración. La base guarda cada versión y su error, medido **siempre con el mismo grupo de validación** para que la comparación sea justa. El grupo de prueba final no sirve para seguir la mejora: se mira **una sola vez**, al final (ADR07). Si se mira antes, la tesis pierde su prueba limpia. |
| Lo más detallado posible | De acuerdo: cada corrida, cada vehículo, cada choque y cada teletransporte. **Dos excepciones.** (a) La posición de cada vehículo segundo a segundo (archivo FCD), que ocupa el 94 % del disco: daría miles de millones de filas. Queda en su archivo; la base guarda dónde está, su huella y las colas ya calculadas. (b) Los videos de campo, por privacidad (RNF10). |
| Un repositorio de datos que sea una base relacional | Sí, con una condición: los **archivos con su huella digital siguen siendo el original**, y la base es la copia ordenada y completa donde se busca. Pasa como con un acta notarial y el archivo de una oficina: se consulta el archivo, pero si alguien duda de un dato, se muestra el original con su sello. En una base de datos se puede cambiar un número sin dejar rastro; en los archivos con huella, no. |
| Lo esencial son las entradas con las que trabaja el modelo y sus salidas | Correcto. La **entrada** es la demanda: vehículos por hora en cada movimiento y la proporción de cada tipo de vehículo. La **salida** son las duraciones de los tramos variables (en Frutales, t1, t3, t5 y t7); con ellas se reconstruyen el ciclo y los verdes, y luego pasan por la corrección de DEV13. La base guarda la salida original y la corregida. |
| Un panel HTML simple, generado sin servidor, que se mejore en la fase final | Correcto, y encaja con ADR02. Es una foto: se regenera con un comando cada vez que se cargan datos nuevos. Se abre con doble clic y no usa internet ni recursos externos; los gráficos van dibujados dentro de la página. |

## 2. ¿SQLite o PostgreSQL?

**Recomendación: PostgreSQL desde el inicio.** En la laptop del PO ya está instalada la versión 17.9, en marcha y con arranque automático.

| Criterio | SQLite | PostgreSQL |
|---|---|---|
| Instalación | Ninguna; viene con Python | Ya instalado (17.9) |
| Qué es | Un solo archivo | Un servicio que corre en la laptop |
| Protección de los datos | Básica: quien abre el archivo puede cambiarlo | Completa: tipos estrictos, fechas con zona horaria, permisos por usuario y bloqueo de cambios |
| Usuario de solo lectura para el panel | No existe | Sí |
| Separar la prueba final con permisos | Solo con código | Con los permisos de la propia base |
| Varias simulaciones escribiendo a la vez | Una por vez | Sin problema |
| Panel web con servidor en la fase final | Habría que migrar | Se conecta directo |
| Varias personas o varios cruces en el futuro | Pensado para un solo usuario | Pensado para varios |
| Entregar los datos al jurado | Se copia el archivo | Exportación completa (respaldo y un CSV por tabla, con huellas) |
| Contraseña | No | Sí, guardada fuera del repositorio |
| Pruebas automáticas | Más simples | Necesitan PostgreSQL encendido; si está apagado, la puerta falla, no se salta |

**¿Se puede migrar de SQLite a PostgreSQL después?** Sí, sin perder datos, porque la base se llena desde los archivos: migrar es volver a cargar. Pero no es gratis. El cargador, las consultas del panel y las pruebas habría que adaptarlos y probarlos de nuevo, porque cada motor escribe algunas cosas de otra forma. Como PostgreSQL ya está instalado y la meta final es un panel web, empezar con él evita ese trabajo doble.

**Condiciones para usarlo bien:**
1. La contraseña nunca va al repositorio, que es público. Se guarda en el archivo estándar de contraseñas de PostgreSQL del usuario de Windows; el código solo lo usa.
2. Dos usuarios de la base: uno que carga datos y otro de solo lectura para el panel y las consultas. El administrador (`postgres`) queda solo para el PO.
3. Hoy PostgreSQL acepta conexiones desde la red, no solo desde la laptop (hallazgo 1). Hay que limitarlo a la laptop.
4. PostgreSQL guarda sus datos en C: (131 GB libres). La base del proyecto iría a una carpeta en D: (423 GB libres).
5. Se registran la versión exacta (17.9) y la del controlador de Python (psycopg 3), fijada tras una prueba de instalación, como pide ADR08 para las librerías.
6. Sin herramientas extra que escondan el SQL: las tablas se definen en archivos SQL estándar y numerados, que cualquiera puede leer y revisar.

## 3. Principios del diseño

1. **Archivos = original; base = copia ordenada y completa.** Los procesos (búsqueda, entrenamiento, evaluación) siguen leyendo y escribiendo archivos como hasta hoy, así que no cambia nada de lo ya probado (5181 pruebas). La base se alimenta de esos archivos.
2. **Carga verificada.** Antes de cargar una carpeta se comprueba su huella. Si no coincide, no entra y queda registrado el motivo.
3. **Todo o nada.** Una corrida se carga entera o no se carga.
4. **Nada se corrige ni se borra dentro de la base.** La propia base rechaza modificar o borrar evidencia. Una corrección es un dato nuevo que dice a cuál reemplaza.
5. **Cada fila sabe de dónde vino:** de qué archivo, con qué huella, con qué versión del código y en qué carga.
6. **Se puede borrar y regenerar idéntica.** Una huella del contenido completo de la base lo demuestra.
7. **Prueba final cegada.** Los resultados de prueba y las semillas finales (3001 a 3013) quedan en una zona separada que el panel no puede leer hasta la apertura, registrada en un acta.
8. **Sirve para cualquier cruce.** El caso es un dato más; nada del esquema nombra a Frutales.

## 4. Qué guarda: el esquema propuesto

Unas 35 tablas en ocho áreas. Los nombres y las columnas finales se fijan en F1, con un diccionario de datos. La última columna dice qué pregunta del asesor o del jurado responde cada tabla.

### Área 0. Trazabilidad (sirve a todas las demás)

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| artefactos | Cada archivo cargado: ruta, tipo, tamaño y huella | «¿De qué archivo sale este número?» |
| cargas | Cada carga: fecha, versión del cargador, resultado y filas por tabla | «¿Cuándo entró este dato?» |
| entornos | Versiones de SUMO, Python, librerías y código | «¿Con qué versión se calculó?» |

### Área 1. El caso

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| casos | Cruce, versión, origen (campo o sintético) y huella de la red | «¿Qué cruce y qué versión del mapa?» |
| movimientos | M01 a M23: acceso, giro y carriles | «¿Qué es el movimiento M07?» |
| tipos_vehiculo | Auto, bus, moto, camioneta y camión | |
| tramos | t1 a t9: fijo o variable, mínimo, máximo y paso | «¿Por qué el verde de Frutales no baja de 35 s?» |
| grupos_verde | Qué tramos dan verde a cada grupo | |
| planes_observados | Plan vigente 82/45/45/10 con su fuente y fecha | «¿De dónde sale el plan actual?» |
| aforos y calibracion | Conteos de campo y su comparación con SUMO (DEV22 y DEV23, más adelante) | «¿La simulación se parece a la realidad?» |

### Área 2. Escenarios, particiones y protocolo

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| familias | BAJA, MEDIA y ALTA, con su origen | |
| escenarios | Familia, variante, semilla de generación y huella | |
| demanda | Escenario × movimiento × tipo de vehículo: veh/h y proporción. **Es la entrada del modelo** | «¿Qué demanda tenía el escenario MEDIA-07 en el giro a la izquierda de Javier Prado?» |
| particiones | Qué grupo va a entrenamiento, a validación o a prueba | «¿Cómo sabe que no entrenó con la prueba?» |
| protocolos | Semillas por etapa, calentamiento, vaciado, versión de la regla C y estado | «¿Las reglas se fijaron antes del experimento?» |

### Área 3. Simulaciones

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| planes | Cada plan probado: duraciones, ciclo y origen (búsqueda, vigente, Webster o modelo) | |
| corridas | Escenario, plan, semilla, etapa, estado, código de salida, duración, memoria, versiones y huellas | «¿Cuántas veces se simuló y con qué semillas?» |
| resultados_corrida | Insertados, terminados, sin terminar, teletransportes por tipo, choques, avisos, demora, cola y detenciones. Además, la clase según la regla C: limpia, incidente aislado o colapso | «¿Cuántas semillas tuvieron choques?» |
| resultados_movimiento y resultados_acceso | Lo mismo, por giro y por entrada del cruce | «¿A quién perjudica el plan?» |
| vehiculos | Cada vehículo: movimiento, tipo, si es de la cohorte, salida programada y real, llegada, pérdida de tiempo, espera, recorrido y estado | «¿Algún vehículo desapareció?» |
| eventos | Teletransportes, choques y avisos de SUMO, con hora, vehículo y carril | «¿Dónde fue el choque?» |
| serie_cola (opcional) | Cola por acceso, segundo a segundo | «Muéstreme cómo crece la cola en la hora punta» |

### Área 4. Búsqueda del mejor plan (etiquetas) y comparadores

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| busquedas | Escenario, presupuesto, intentos, descartados por regla e identidad | |
| candidatos | Cada plan candidato: origen, etapa a la que llegó, puntaje y motivo de descarte | «¿Por qué este plan y no otro?» |
| etiquetas | Plan ganador o «sin referencia», y con qué regla | |
| comparadores | Plan vigente y Webster: si aplica y, si no, por qué | «¿Por qué no se usó Webster?» |

### Área 5. Entrenamiento

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| conjuntos | Qué etiquetas entraron al entrenamiento, con su huella | |
| entrenamientos | Mediana o XGBoost, configuración, semilla, versión de la librería y duración | |
| curva_aprendizaje | Error en cada vuelta del entrenamiento, con los datos de entrenamiento y con los de validación | «¿Se sobreajustó?» |
| metricas_modelo | Error del ciclo y de cada verde, factibilidad y cobertura, por versión | «¿Cuánto mejor es XGBoost que la mediana?» |
| modelos y seleccion | Versión elegida, su huella y la decisión con su motivo | «¿Por qué eligió este modelo?» |

### Área 6. Consultas al modelo

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| consultas | Entrada, modelo, estado (aceptado, corregido o rechazado), motivo y tiempo | «¿Propuso alguna vez un plan imposible?» |
| consulta_tramos | Duración original y corregida de cada tramo | «¿Cuánto corrigió la regla?» |
| consulta_reglas | Reglas cumplidas e incumplidas | |

### Área 7. Evaluación final (lo que respalda la tesis)

| Tabla | Qué guarda | Pregunta que responde |
|---|---|---|
| experimentos | Protocolo congelado, semillas finales y fecha de apertura | |
| comparaciones | Escenario × alternativa (modelo, mediana, vigente, Webster o búsqueda) × semilla, con su corrida | |
| diferencias | Diferencias emparejadas de demora, cola y detenciones, en total y por acceso | «¿Cuánto bajó la demora frente al plan vigente?» |
| indicadores | I1 a I8, con valor, denominadores, intervalo de confianza y versión | «¿Con qué incertidumbre?» |

## 5. Volumen esperado

- **Hoy:** 133 corridas, el piloto de DEV14 y los comparadores de DEV15.
- **DEV16:** unas 4700 corridas y unos 8,4 millones de vehículos, de 2 a 3 GB. Con la cola segundo a segundo se suman unos 60 millones de filas y de 3 a 4 GB.
- **DEV24:** varias veces más. PostgreSQL lo maneja sin problema, y por eso la base va en D:.

## 6. El panel, versión simple

- **Páginas:** Inicio (resumen y estado), Caso, Escenarios, Simulaciones, Búsqueda, Entrenamiento (cómo cambian las versiones del modelo), Consultas y Evaluación final (bloqueada hasta la apertura).
- **Trazable:** cada cifra muestra de qué corrida sale y su huella.
- **Cómo se genera:** con un comando, desde la base y con el usuario de solo lectura. Se abre con doble clic, sin internet. El texto se escapa (QA30) y el color nunca es la única señal.
- **Relación con DEV21:** puede ser la vista «Resultados» que DEV21 ya tenía prevista, adelantada.
- **En la fase final** se podrá cambiar por un panel con servidor conectado a la base. Eso requiere otra decisión (cambiar ADR02) y pruebas de seguridad.

## 7. Documentos que cambian

**Antes de tocar nada:** `documentacion/` no está en git. F0 guarda una copia de la versión 1.0 con sus huellas, para que siempre se pueda ver qué decía antes.

| Documento | Hoy dice | Pasaría a decir |
|---|---|---|
| `CONTEXTO.md`, línea 71 | Bases de datos fuera de alcance, «no lo propongas» | Se quita de la lista, y la sección 1.3 suma la enmienda 12, con fecha y origen |
| `01_Diseno_tecnico.md`, alcance (línea 18) | No se requiere base de datos | Base relacional local de consulta (PostgreSQL), derivada de los archivos; sin API ni nube |
| 01, ADR01, ADR02 y ADR03 (líneas 25 a 29) | Monolito; sin servidor; base descartada | PostgreSQL como servicio local, igual que SUMO es un proceso externo. Panel estático generado desde la base. La base es la copia de consulta y los archivos, el original |
| 01, ADR12 nuevo | — | Decisión de la base: motor, principios de la sección 3 y cegado |
| 01, paquetes y estructura (líneas 47 a 61) | Ocho paquetes | Paquete nuevo `bd` (esquema, carga verificada y consultas) y carpeta de migraciones |
| 01, transacciones (línea 66) | «No se prevén transacciones de base de datos» | La carga es de todo o nada, después de verificar las huellas |
| 01, despliegue (líneas 169 a 171) | «Sin puertos de aplicación» | PostgreSQL escucha solo dentro de la laptop |
| 01, seguridad (líneas 178 a 181) | «No hay secretos» | La contraseña de la base es un secreto local, fuera del repositorio. Amenazas nuevas: alterar la base y espiar la prueba desde el panel |
| 01, diagramas D02, D03, D06 y D07 | Sin base | Con la base. Se cambian las fuentes `.mmd` y `.dot`; para las imágenes ver el hallazgo 6 |
| 01, línea 242 | «No una base de datos relacional» | Archivos más una copia relacional |
| `02_Requisitos_y_plan.md` | 14 historias y 31 tareas | HU15 y RF15, DEV31, el entregable nuevo y su lugar en la hoja de ruta (F2) |
| `03_Pruebas_y_operacion.md` | 31 casos de prueba; respaldo de archivos | QA32 a QA37; las pruebas necesitan PostgreSQL; respaldo y restauración de la base |
| `matrices/*.csv` | HU01 a HU14, DEV00 a DEV30, QA01 a QA31 | Filas nuevas |
| `tools/contracts/validar_paquete.py` | Exige exactamente HU01 a HU14 | Acepta HU15 (hallazgo 3) |
| `LEEME.md`, `VALIDACION_PAQUETE.md` e `INVENTARIO_SHA256.json` | Cantidades y huellas de la v1.0 | Cantidades nuevas, validación repetida y huellas nuevas |
| Los tres documentos Word | v1.0 | Ver el hallazgo 5 |
| `docs/adr/` | ADR01 a ADR11 | Enmiendas a ADR01, ADR02 y ADR03, y ADR12 nuevo |
| La tesis v2.5 | — | **No se toca.** El asesor decide si su metodología menciona la base |

**Pruebas nuevas propuestas:**

| ID | Qué comprueba |
|---|---|
| QA32 | Una carpeta alterada no se carga, y cargar dos veces lo mismo no lo duplica |
| QA33 | La base coincide con los archivos: mismos conteos y misma demora recalculada en cada corrida |
| QA34 | Seguridad: el panel no puede modificar nada; la base rechaza cambios y borrados de la evidencia; no hay contraseñas en el repositorio; solo acepta conexiones desde la laptop; un texto con código malicioso se muestra como texto |
| QA35 | Cegado: antes de la apertura, ninguna consulta del panel ni de desarrollo devuelve datos de prueba |
| QA36 | Borrar y regenerar la base da la misma huella, y el respaldo se restaura |
| QA37 | Revisión manual: una persona no técnica entiende el panel |

## 8. Hallazgos de la inspección

1. **PostgreSQL acepta conexiones de toda la red** (escucha en `0.0.0.0:5432`). En un wifi compartido, otro equipo podría intentar entrar. Hay que limitarlo a la laptop. Es un cambio de configuración que hace el PO como administrador, con pasos exactos que preparará el equipo.
2. **Las corridas no registran la versión del código.** El manifiesto guarda SUMO, Python y el sistema operativo, pero no el commit. Para la base y para la reproducibilidad (RNF03) conviene agregarlo desde ya. Las 133 corridas existentes quedarán con «versión de código no registrada», sin inventarla.
3. **El validador de contratos exige exactamente HU01 a HU14.** Agregar HU15 sin actualizarlo rompería la puerta (43/43).
4. **`documentacion/` no está en git.** Por eso se guarda la copia de la versión 1.0 antes de cambiar.
5. **Los documentos Word no se pueden regenerar desde el Markdown:** no hay una herramienta de conversión instalada. Opciones: instalar una (pandoc) o dejar los Word en la v1.0 con una nota que diga que manda el Markdown 1.1.
6. **Las imágenes de los diagramas tampoco se pueden regenerar:** no están instalados Graphviz ni Mermaid.
7. **PostgreSQL guarda sus datos en C:.** Conviene que la base del proyecto vaya en D:.
8. **El repositorio remoto es público.** Ninguna contraseña ni dato privado de conexión puede ir en él.

## 9. Fases

| Fase | Contenido | Resultado | Complejidad | Riesgo | Modelo |
|---|---|---|---|---|---|
| **F0** | Acta del cambio de alcance con su impacto; DEC09 (aceptar ADR01 a ADR08 con las precisiones ya analizadas) y ADR12; copia de la v1.0; cambios de la sección 7; validador actualizado | Documentación 1.1 coherente y contratos 43/43 | Media | Medio: contradicciones entre documentos | Opus |
| **F1** | Esquema detallado: tablas, columnas, unidades, reglas, permisos y cegado; diccionario de datos; volumen | Esquema revisable antes de programar | Media-alta | Medio | Opus |
| **F2** | Preparar PostgreSQL: base del proyecto en D:, usuarios y conexiones solo desde la laptop (lo hace el PO con los pasos del equipo). Instalar el controlador. Cargador verificado, de todo o nada y que no duplica. Commit del código en los manifiestos nuevos. QA32, QA34 y QA36 | Cargador probado | Media-alta | Medio | Opus |
| **F3** | Cargar lo existente (133 corridas, piloto y comparadores) y conciliarlo con los archivos (QA33); cegado (QA35) | Base con los datos actuales y conciliación al 100 % | Media | Bajo | Sonnet |
| **F4** | Panel estático v1 (sección 6) y revisión manual (QA37) | Panel que se abre con doble clic | Media | Bajo | Sonnet |
| **F5** | Ensayos de daño a propósito, inspección contra la documentación y acta de cierre | Cierre de DEV31 | Media | Bajo | Haiku |

Antes de cargar datos grandes, cada fase mide memoria y disco, como en el resto del proyecto.

## 10. Orden respecto de DEV16

- **DEV31 F0 a F3 van antes de generar los 40 escenarios (DEV16 F1)**, para que esas corridas entren a la base desde el primer día.
- **El panel (F4)** puede hacerse mientras corren los escenarios.
- **DEV16 F0** (solo decisiones) no depende de la base y puede hacerse en cualquier momento.

## 11. Decisiones que se piden al PO

1. ¿Se aprueba el cambio de alcance como requisito nuevo (HU15 y DEV31)? La alternativa es colgarlo de HU14 (exportar y reproducir), pero quedaría menos visible en la tesis.
2. ¿PostgreSQL 17 desde el inicio, con las condiciones de la sección 2?
3. ¿Se confirma que los archivos siguen siendo el original y la base, la copia completa para consultar?
4. ¿Se guarda también la cola segundo a segundo? En DEV16 suma de 3 a 4 GB, y responde preguntas como «muéstreme cómo crece la cola».
5. Documentos Word: ¿se instala pandoc para regenerarlos, o se quedan en la v1.0 con una nota?
6. Lo que quedó pendiente de DEC09: comprimir el FCD, anclar en git las huellas de lo publicado y aceptar ADR01 a ADR08 con sus precisiones.
7. ¿Se avisa al asesor? Cambia el diseño técnico, aunque no la tesis.
8. ¿Se ejecuta F0?
