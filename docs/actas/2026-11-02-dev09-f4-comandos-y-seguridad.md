# Acta 2026-11-02: DEV09 · F4 (comandos, seguridad de QA30 y muestras)

- **Tipo:** fase F4 de DEV09 (HU01, HU02 y HU03). Ejecutada sin pausa, como pidió el Product Owner.
- **Decisiones que aplica:** D12, D13, D15 y D16 de F0.
- **Datos:** sintéticos, y el caso-001 real solo para leerlo.

## Qué se construyó

| Archivo | Qué hace |
|---|---|
| `src/semaforo/app/report_commands.py` | `report_case` y `report_data`: leen con verificación, publican y devuelven `ReportResult` (tipo, caso, estado del caso, carpeta y página, con rutas relativas) |
| `src/semaforo/cli/main.py` (ampliado) | Grupo `report` con `case` y `data`, `--workspace` y `--debug`; el mensaje para la persona da la ruta completa de la página y el estado del caso en palabras |
| `README.md` | Sección «Informes HTML del caso y de los datos» con los comandos y los códigos de salida |
| `tests/unit/test_report_cli.py`, `tests/e2e/test_cli_report.py`, `tests/security/test_dev09_reports.py` | 26, 3 y 20 pruebas |
| `docs/actas/2026-11-02-dev09-lista-de-revision-qa30.md` | La lista de revisión manual para el Product Owner |

## Los comandos

```powershell
.venv\Scripts\python.exe -m semaforo report case --case RUTA\case.json [--workspace datos]
.venv\Scripts\python.exe -m semaforo report data --case RUTA\case.json --quality-report CARPETA [--workspace datos]
```

| Código | Cuándo |
|---|---|
| 0 | Informe publicado, también con un caso inválido o con avisos (el JSON dice `case_status`) |
| 2 | El caso o el reporte de calidad no existen o no son válidos, o el reporte es de otro caso |
| 5 | Un enlace, un reporte alterado, el caso cambió desde que se generó el reporte, o el informe ya existe |
| 1 | Error interno |

En ningún error de lectura se publica nada. La salida estándar lleva solo el JSON, sin rutas de la máquina.

## Seguridad de QA30 (la parte automática)

Con la herramienta ejecutada como un proceso aparte:

- **8 ataques** (`script`, imágenes con `onerror`, `svg`, `iframe`, enlaces `javascript:`, redirección con `meta`, `style` y cierre de etiquetas) puestos en el identificador, la frontera y las restricciones del caso: se ven como texto, la página no tiene ninguna etiqueta peligrosa ni atributos de eventos, y la carpeta es `sin-identificar`.
- **Caracteres de control y de dirección de texto** en las restricciones: no llegan a la página.
- **Ataques en los periodos y las fuentes de los datos**: se ven como texto en el informe de datos.
- **Archivos hostiles** (vacío, que no es texto, clave repetida, anidado 100 000 niveles, `NaN`, con marca BOM, de más de 1 MiB): cada uno genera un informe de caso inválido y el programa no se cae.
- **Confinamiento:** con el identificador `../../fuera`, todo lo escrito queda dentro de `reportes/informes/` y no se crea nada fuera.
- Ninguna página apunta fuera de sí misma (los únicos enlaces son anclas internas).

## Verificación

- **Pruebas:** 49 nuevas. Suite completa: **2264 pasan, 1 se salta**. Formato, lint, tipos y contratos sin observaciones.
- **Mutaciones:** 21 cambios a propósito sobre los casos de uso y la línea de comandos. **18 se detectaron en la primera pasada y 3 no**: el estado del caso en el informe de datos (siempre daba «válido» en las pruebas) y que los dos casos de uso respetan la hora que se les da. Se cerraron con 3 pruebas y los 21 quedan detectados.
- **Muestras para la revisión manual:** 9 informes generados con los comandos reales en `datos/revisiones/dev09/` (no se versiona): el caso real, uno válido, uno con avisos, uno inválido, uno con texto hostil y cuatro de datos. Los 9 pasan las comprobaciones de seguridad y sus manifiestos se leen verificados.

## Hallazgos de la inspección

| # | Hallazgo | Qué se hizo |
|---|---|---|
| 1 | Una de mis pruebas usaba como nombre el propio archivo hostil de 100 000 corchetes, y pytest se rompía al armar la carpeta temporal | Cada caso hostil tiene un nombre corto |
| 2 | Una comprobación mía daba una falsa alarma: el texto escapado `&lt;img ... onerror=...&gt;` contiene la palabra `onerror`, aunque no se ejecuta | Ahora se comprueba lo que importa: que ningún elemento tenga atributos de eventos ni etiquetas peligrosas |
| 3 | En el caso base, el estado del caso en el informe de datos no se distinguía (siempre válido) | Una prueba con un caso con avisos |
| 4 | `datos/` real: solo se creó `datos/revisiones/dev09/`, que es mío y no se versiona; el resto no se tocó | Anotado |

## Estado del repositorio

- Autor `crisroco`, sin línea de coautoría.
