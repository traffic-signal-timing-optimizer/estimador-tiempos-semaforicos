# Acta 2026-11-01: DEV08 · F0 (decisiones de la trazabilidad)

Written for: el Product Owner y el equipo, para revisar qué se decidió antes de construir DEV08 y por qué.

- **Tipo:** fase F0 de DEV08 (HU14; P0, tamaño M). Dependencia: DEV01, cerrada.
- **Autorización:** el Product Owner aprobó el plan y pidió ejecutar todas las fases seguidas, parando solo para confirmar algo, cambiar de modelo, ante errores que bloqueen o ante cambios de alcance. Las cuatro decisiones que el plan dejaba abiertas se toman con la recomendación ya explicada (D7, D9, D11 y D12).
- **Datos:** sintéticos y las carpetas reales de `datos/`, solo para leerlas.

## Qué pide la documentación

- `02_Requisitos_y_plan.md`, DEV08: «IDs únicos, temporales/renombrado atómico, hashes, vínculos, locks y manifiestos; no sobrescribir». Archivos: `trazabilidad/store.py`, `trazabilidad/manifest.py`. Resultado: «Almacén inmutable reproducible». Verificación: QA09 y QA29.
- `01_Diseno_tecnico.md`: paquete `trazabilidad` = «IDs, hashes y vínculos» (`register_artifact(path, metadata) → ArtifactRef`); «Un lock exclusivo impide dos escrituras al mismo destino. Las lecturas usan artefactos publicados y hashes comprobados»; código 5 = fallo de integridad; 0 incluye un resultado de dominio registrado; hay que leer `status`.
- `03_Pruebas_y_operacion.md`: QA09 (dos ejecuciones con los mismos insumos y semilla; comparar huellas de entradas y resultados normalizados; iguales dentro de tolerancia; horas fuera de la comparación; evidencia: reporte de réplica), QA29 (artefacto modificado, exportación con video y mismo destino: la huella incompatible bloquea, el video se excluye, no se sobrescribe), I8 («identidad exacta de entradas y tolerancia numérica de salidas»).
- ADR03 (propuesta): artefactos inmutables con manifiesto y SHA-256, directorio nuevo y renombrado atómico; prueba de aceptación QA09 y QA29.

## Qué ya existe

| Familia | Dónde | Publicación | Candado | Lectura verificada |
|---|---|---|---|---|
| Corridas | `ejecuciones/<run_id>` | `RunWriter` | Sí (del sistema, DEV07) | `read_run` |
| Recepciones | `derivados/recepcion/<id>` | `publish_files` | **No** | `read_reception` |
| Copias de originales | `originales/sumo/<snapshot_id>` | propia (copia verificada) | **No** | Al reutilizar (`_verify_existing`); el nombre es la huella del contenido |
| Programas derivados | `derivados/programas/<caso>/<fecha>_<huella>` | `publish_files` + `manifiesto.json` | **No** | **No** (solo al prepararse las entradas) |
| Entradas de SUMO | `derivados/entradas/<escenario>/<fecha>_<huella>` | `publish_files` + `manifiesto.json` | **No** | `verify_inputs` |
| Reportes de calidad | `<raíz>/<caso>/<fecha>_<huella>` | `publish_files` + `manifiesto.json` | **No** | **No** |

Además: corridas caídas apartadas en `ejecuciones/.incompletas` (DEV07); `retry_of` validado (DEV07); `content_id` para identificadores por contenido (DEV00).

## Decisiones

| # | Tema | Decisión | Por qué |
|---|---|---|---|
| D1 | Alcance | Completar lo que falta sin reemplazar lo que funciona. **No se cambia el contrato `run_manifest`** ni los formatos de los manifiestos existentes | La documentación prevalece; los formatos ya publicados tienen archivos reales en `datos/` |
| D2 | Candado en todas las publicaciones | `publish_files` toma el bloqueo del sistema `<carpeta>/.lock-<destino>` (el mismo `RunLock` de DEV07) antes de comprobar que el destino no existe y lo suelta después de publicar. Igual la copia de originales | El diseño pide un lock exclusivo por destino; hoy solo lo tienen las corridas |
| D3 | Nombre de la carpeta temporal | `.tmp-<destino>-<aleatorio>`, en vez de `.tmp-<aleatorio>`, salvo en corridas (siguen cortas por el límite de rutas de SUMO) | Así se sabe a qué destino pertenece una carpeta temporal y si su candado sigue tomado |
| D4 | Publicaciones caídas | Antes de publicar en una carpeta se apartan sus temporales caídas a `<carpeta>/.incompletas/<nombre>` con `INCOMPLETA.json`; no se borran. Una temporal con nombre antiguo (sin destino) se aparta solo si tiene más de 60 s | Mismo criterio que las corridas de DEV07: nada se borra; una corrida viva no se toca |
| D5 | Lectura verificada común | `verify_files(carpeta, esperados)`: la carpeta tiene exactamente esos archivos (más el manifiesto), con esas huellas y sin enlaces. Se agregan `read_program` y `read_quality_report` con esa regla | «Las lecturas usan artefactos publicados y hashes comprobados» |
| D6 | Vínculos | `trace_run`: de una corrida a su carpeta de entradas, de ahí al programa derivado y al caso, comprobando en cada paso las huellas registradas. Cada eslabón queda «verificado», «no encontrado» o «alterado» | Las huellas ya existen en los manifiestos; falta comprobar la cadena completa |
| D7 | Revisión de todo `datos/` | `verify_workspace`: recorre las seis familias y dice, para cada carpeta, «íntegra», «alterada» (con el motivo), «incompleta» o «desconocida» (lo que no sigue un formato conocido). Solo lee: no mueve ni corrige nada | QA29 pide que una huella incompatible bloquee; esto permite encontrarla antes |
| D8 | Normalización para la réplica | Entradas: huellas idénticas. XML de SUMO (`tripinfo.xml`, `statistics.xml`): se comparan elemento por elemento; los comentarios no cuentan (allí va la hora) y en `statistics.xml` se omite el bloque `performance` (tiempos de reloj). Tablas y JSON de la corrida (`cohorte_conciliada.csv`, `conciliacion.json`, `summary.json`): idénticos. Fuera de la comparación: `tiempos.json`, `sumo.log`, `sumo.stdout.txt`, `sumo.stderr.txt` | Hallazgo de DEV07: SUMO escribe la hora dentro de cada XML. Los registros llevan duraciones |
| D9 | Tolerancia | Los números enteros y los textos, exactos. Los números con decimales: diferencia relativa de hasta 1e-9 (una parte en mil millones) o absoluta de 1e-9. Se puede cambiar al pedir la réplica | I8: «tolerancia numérica de salidas». No hay un valor en la documentación; con la misma semilla SUMO da lo mismo, así que el margen solo absorbe redondeos entre equipos |
| D10 | Reporte de réplica | `compare_runs` produce un reporte (`replica.json`): las dos corridas, si las entradas y la semilla coinciden, cada archivo con su regla y su resultado, la tolerancia y un veredicto `equivalent` o `different`. Se publica en `derivados/replicas/<fecha>_<huella>/` con su manifiesto, sin sobrescribir | QA09 pide un «reporte de réplica» como evidencia |
| D11 | Comandos | **Sí:** `python -m semaforo runs verify [--workspace]` y `python -m semaforo runs compare --run-a --run-b [--workspace] [--tolerance]`, por la capa `app`. `verify`: 0 si todo está íntegro, **5** si algo está alterado (fallo de integridad). `compare`: 0 al registrar el reporte, sea `equivalent` o `different` (hay que leer `status`), 2 si una corrida no existe, 5 si una está alterada | El diseño: 0 incluye un resultado de dominio registrado; 5 = integridad. Sin comandos, revisar `datos/` depende de scripts |
| D12 | ADR03 | Se **recomienda** pasarla a «Aceptada» al cierre, porque sus pruebas (QA09 y QA29 en lo que toca) quedarán cumplidas. **El cambio de estado lo confirma el Product Owner**; no se cambia en esta tarea | Aceptar una decisión de arquitectura es del Product Owner |
| D13 | Fuera de DEV08 | Exportar evidencia y excluir videos (resto de QA29: DEV21 y DEV27), reproducir desde una exportación (DEV27), respaldo y restauración (DEV30) | Cada uno tiene su tarea en el plan |
| D14 | Recursos | Mutaciones de a una; temporales de verificación borrados al cerrar cada fase; ningún programa del usuario se cierra. La revisión de `datos/` real solo lee | Regla vigente |

## Fases

| Fase | Qué se hace | Criterio de cierre | Complejidad | Modelo |
|---|---|---|---|---|
| F1 | Almacén común (D2 a D5) | Toda publicación tiene candado y no sobrescribe aunque dos lleguen a la vez; una publicación caída se aparta; programas y reportes de calidad se leen verificados | Media | Sonnet |
| F2 | Vínculos y revisión de `datos/` (D6, D7) | La cadena de una corrida del caso real se verifica entera; un archivo alterado en cualquier familia aparece como «alterado» | Media | Sonnet |
| F3 | Réplica (D8 a D10) | Dos corridas iguales dan `equivalent`; una con otra semilla o un resultado cambiado dan `different` con el motivo; el reporte queda publicado | Media | Sonnet |
| F4 | Comandos `runs verify` y `runs compare` (D11) | Códigos de salida del diseño y JSON en la salida estándar | Baja | Sonnet |
| F5 | Cierre | Caso real, mutaciones, inspección, tabla de HU14, QA09 y QA29 | Baja-media | Sonnet |

Cada fase cierra con una inspección de lo desarrollado contra la documentación y el caso real.
