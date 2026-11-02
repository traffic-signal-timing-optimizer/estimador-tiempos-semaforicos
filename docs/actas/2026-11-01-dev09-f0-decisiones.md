# Acta 2026-11-01: DEV09 · F0 (decisiones de las vistas de Caso y Datos)

- **Tipo:** fase F0 de DEV09 (HU01, HU02 y HU03; P1, tamaño M). Dependencias: DEV02, DEV05 y DEV08, cerradas.
- **Autorización:** el Product Owner aprobó el plan (`2026-11-01-planes-dev09-dev11-dev12.md`) y pidió ejecutar F0 a F5 seguidas, parando solo para confirmar algo, cambiar de modelo, ante errores que bloqueen o ante cambios de alcance.
- **Datos:** sintéticos. El `datos/` real solo se lee (el caso-001); no se escribe en él salvo la carpeta de revisión del Product Owner.

## Qué pide la documentación

- `02_Requisitos_y_plan.md`, DEV09: «Generar HTML estático escapado con tablas de estado, unidades, cero/faltante y causa; abrir archivos localmente». Resultado: «Dos vistas legibles». Verificación: «QA30 y revisión manual».
- `01_Diseno_tecnico.md`, «Vistas y experiencia»: «**Caso** muestra origen sintético/real, versión y restricciones. **Datos** distingue cero/faltante, observado/corregido/excluido y cobertura. [...] Los reportes son accesibles mediante encabezados, tablas y texto; color nunca es el único indicador de estado».
- `01_Diseno_tecnico.md`, seguridad: «Los reportes HTML escapan texto».
- ADR02: reportes HTML estáticos, sin servidor.
- HU01: «origen sintético/real visible». HU03: «cero distinto de faltante; control manual o sintético identificado; exclusiones justificadas; error relativo nulo si control cero».
- QA30: «Cinco vistas con errores y texto HTML inyectado. Abrir reportes y revisar campos/unidades. Estados claros; texto escapado; sin ejecución de contenido; tabla legible. Evidencia: Checklist UX».

## Qué ya existe y qué falta

| Pieza | Estado |
|---|---|
| Validación del caso con reporte de reglas | Existe: `caso/case_validation.py` (`validate_case`, `read_case`) y `CaseReport` |
| Reporte de calidad de aforos publicado con manifiesto | Existe: `datos/quality_report.py` (`calidad.csv`, `resumen.json`, `manifiesto.json`). **Solo se escribe**; la lectura de vuelta cubre el manifiesto |
| Publicación y lectura verificada de carpetas | Existe (DEV08): `publish_files`, `read_verified` |
| Código HTML | **No existe** ninguno en `src/` |
| Lectura tipada de `calidad.csv` y `resumen.json` | **No existe** |

## Hallazgos de F0

| # | Hallazgo | Qué se hace |
|---|---|---|
| H1 | El reporte de calidad no se puede leer de vuelta (solo su manifiesto) | F1: lectores tipados de `calidad.csv` y `resumen.json`, con la huella de los bytes leídos |
| H2 | La matriz propone `cli/reports.py` y `templates/case.html` y `data.html`. ADR01 impide que `cli` importe `caso` o `datos` | El código va en `app/` (como `reception_report.py`); la `cli` solo agrega el grupo `report`. Mismo resultado, sin romper la regla de capas |
| H3 | QA30 pide cinco vistas y DEV09 entrega dos | QA30 queda parcial hasta DEV21 (ya aprobado en el plan) |
| H4 | «Datos» pide distinguir observado, **corregido** y excluido, pero el proyecto no corrige datos (DEV05: no se imputa nada en silencio) | El informe muestra «corregidos: 0» con una nota que lo explica |
| H5 | El reporte de calidad guarda conteos, no vehículos por hora ni composición (eso es de DEV04 y no se guarda) | La vista muestra conteos en vehículos por ventana, con la duración en segundos. No se repite la normalización |
| H6 | El `datos/` real no tiene reporte de calidad: los aforos reales de Frutales siguen pendientes | La vista de datos se muestra con datos sintéticos; la del caso, con el caso-001 real |

## Decisiones

| # | Tema | Decisión | Por qué |
|---|---|---|---|
| D1 | Alcance | Dos vistas: **Caso** y **Datos**. Las otras tres son de DEV21 | Plan aprobado |
| D2 | Dónde vive el código | HTML en `app/` (`html_page.py`, vistas del caso y de los datos, publicación); `cli/main.py` agrega el grupo `report`. No se crean `cli/reports.py` ni `templates/` | H2: ADR01 |
| D3 | Cómo se arma el HTML | Sin librería de plantillas (no hay `uv` para bloquear una dependencia). Funciones que reciben texto y lo escapan con `html.escape`; el texto fijo vive en constantes. **Ningún dato se pega a mano en el HTML** | Los reportes escapan texto; QA30 |
| D4 | Entrada de la vista del caso | El archivo `case.json`: `validate_case` (reporte de las reglas) y `read_case` (movimientos, grupos, restricciones). Si las dos lecturas no dan la misma huella, el archivo cambió a medias y se rechaza | Evita mostrar dos cosas distintas |
| D5 | Entrada de la vista de datos | El caso y la carpeta del reporte de calidad de DEV05. Se verifica la carpeta (`read_quality_report`) y que `case_sha256` del manifiesto sea el del caso dado. Si algo no coincide, **no se publica nada** y sale 5 | «Las lecturas usan artefactos publicados y hashes comprobados» |
| D6 | Contenido de la vista del caso | Identidad (ID, versión, huella); **origen sintético o real**, escrito en palabras; estado de la representación; estado de la validación con sus 19 reglas (cumple, aviso, no cumple, no aplica) y los problemas de cada una; estado de la red; límites (tick, ciclo declarado y factible, tiempo fijo, grupos de verde con lo declarado y lo alcanzable); movimientos con su flujo permitido en veh/h; clases de vehículos; política de frontera; evidencia de restricciones (o el aviso de que no hay) | HU01; diseño «Vistas» |
| D7 | Contenido de la vista de datos | Identidad del caso y del reporte; cobertura de la ventana (segundos cubiertos, porcentaje, mínimo cumplido o no definido), por movimiento, huecos, solapes y periodos fuera de la ventana; ventanas por estado; tabla de comparación con el control (observado y control en vehículos, error absoluto en vehículos, error relativo como fracción, estado y motivo, **fuente del control**); lista de faltantes; exclusiones con su causa y el límite usado; contador de observados, corregidos y excluidos | HU02, HU03; diseño «Vistas» |
| D8 | Cero y faltante | Un cero se escribe «0»; un faltante se escribe «sin dato» y nunca «0». Error relativo nulo se escribe con su motivo (por ejemplo, control en cero) | HU03; QA05 |
| D9 | Accesibilidad | Idioma `es`, un título, `h1` y `h2` por sección, tablas con `caption` y `th scope`. Cada estado lleva **símbolo y texto** además del color, y el informe se entiende en blanco y negro | «Color nunca es el único indicador» |
| D10 | Contención | Sin `script`, sin atributos de eventos, sin recursos externos y con una política `Content-Security-Policy` en el propio HTML que no permite scripts. Ningún enlace sale de datos | Defensa en profundidad para QA30 |
| D11 | Publicación | `datos/reportes/informes/<caso\|datos>/<id-del-caso>/<fecha>_<huella>/` con `index.html` y `manifiesto.json` (huellas de las entradas y de los archivos), con `publish_files`. Nunca se sobrescribe. Lectura verificada propia (`read_report`) | ADR03; trazabilidad |
| D12 | Comandos | `report case --case RUTA` y `report data --case RUTA --quality-report CARPETA`, con `--workspace`. Por la salida estándar un JSON con `status` y la ruta del informe; no abre el navegador (se abre con doble clic). Salidas 0, 2, 3, 5 y 1 | Mismo patrón que `runs compare` |
| D13 | Casos inválidos | Un caso inválido **sí** genera informe, con los problemas a la vista (es lo que pide QA30). La salida es 0 y hay que leer `status`. Un caso que no se puede leer (no existe, es un enlace) no genera informe: sale 2 o 5 | QA30: «vistas con errores» |
| D14 | `runs verify` | No se agrega la nueva carpeta a `runs verify`: `datos/reportes/` no se revisa hoy y los informes se pueden regenerar. Queda anotado como mejora | Alcance |
| D15 | Pruebas | Automáticas: estructura, estados, cero y faltante, accesibilidad básica y **texto inyectado en todos los campos libres**. Mutaciones sobre el escape y sobre los estados. Revisión manual de QA30: lista para el Product Owner en el cierre | QA30 |
| D16 | Para que el Product Owner revise | Se generan informes de muestra en `datos/revisiones/dev09/` (no se versiona): el del caso-001 real y uno de datos con el caso sintético | «Dos vistas legibles» |
| D17 | Modelo | Sonnet (esfuerzo alto) en todas las fases; ninguna requiere más | Complejidad media, riesgo bajo |

## Fases (ajustadas)

| Fase | Qué se hace | Complejidad |
|---|---|---|
| F1 | Lectura verificada: lectores tipados de `calidad.csv` y `resumen.json` en `datos/quality_report.py`; entradas de las dos vistas (caso con la doble lectura, reporte de calidad con huella y vínculo al caso) | baja-media |
| F2 | `app/html_page.py` (escape, tablas, estados, página) y la **vista del caso**, con publicación y `read_report` | media |
| F3 | La **vista de datos** (D7 y D8) | media |
| F4 | Comandos `report case` y `report data`, README, pruebas de seguridad de QA30 y muestras para la revisión | media-baja |
| F5 | Cierre: acta con HU01 a HU03 y QA30 (parcial), inspección contra la documentación y el caso real, lista de revisión manual, bitácora | baja |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría. Sin código nuevo en esta fase.
