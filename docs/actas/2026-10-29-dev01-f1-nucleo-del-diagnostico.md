# Acta 2026-10-29: DEV01 · F1 (núcleo del diagnóstico)

- **Tipo:** registro de fase del plan de DEV01 (HU01, HU14)
- **Autorización:** el Product Owner autorizó F1 («ejecuta F1») después de revisar la lista de pruebas propuesta.
- **Siguiente fase:** F2 (medir el equipo y SUMO), a la espera de su autorización.

## Qué se hizo

Las reglas del diagnóstico de `python -m semaforo doctor`, sin medir todavía el equipo. Reciben lo medido (`EnvironmentFacts`) y deciden el estado de cada comprobación y el código de salida. La medición se añade en F2 y el comando en F3.

| Archivo | Contenido |
|---|---|
| `src/semaforo/app/doctor_models.py` | `Check` (nombre, estado `ok`/`warning`/`error`, valor medido, motivo y código de error) y `DoctorReport` (estado `ok`/`warnings`/`failed`, código de salida y comprobaciones en orden fijo) |
| `src/semaforo/app/doctor.py` | `EnvironmentFacts`, `WorkspaceFacts` y las reglas de cada comprobación; `build_report` arma el diagnóstico |
| `tests/unit/test_doctor.py` | 32 pruebas |

**Comprobaciones, en orden:** Python; paquetes `semaforo`, `pydantic` y `defusedxml`; sistema operativo; CPU; RAM total y disponible; carpeta de trabajo; espacio libre; SUMO; versión de SUMO.

**Reglas, según las decisiones de F0:**

| Comprobación | Error (código de salida) | Aviso | Bien |
|---|---|---|---|
| Python | otra versión que no sea 3.12, o versión ilegible: `DEPENDENCY_MISSING` (3) | — | 3.12.x |
| Paquetes | falta alguno: `DEPENDENCY_MISSING` (3) | — | se informa su versión |
| Sistema operativo, CPU | — | no se pudo medir | se informa |
| RAM | — | no se pudo medir | se informa en bytes, sin umbral |
| Carpeta de trabajo | no existe: `INPUT_SCHEMA` (2); es un enlace o una unión, no es carpeta o no admite escritura: `PATH_NOT_ALLOWED` (5) | — | carpeta real con escritura |
| Espacio libre | — | no se pudo medir o queda 0 bytes | se informa en bytes, sin umbral |
| SUMO | no se encuentra: `DEPENDENCY_MISSING` (3) | — | se informa la ruta |
| Versión de SUMO | ilegible: `DEPENDENCY_MISSING` (3) | otra versión que no sea 1.27.1, o no se comprobó porque falta SUMO | 1.27.1 |

El estado es `failed` si hay algún error, `warnings` si solo hay avisos y `ok` si todo está bien. Con avisos, el código de salida es 0. Con varios errores, se usa el código del primero en el orden de las comprobaciones. Los códigos son los del diseño técnico, los mismos que usa `case receive`.

## Pruebas

| Qué se prueba | Pruebas |
|---|---|
| Un equipo bien configurado da `ok`, código 0 y el orden fijo de comprobaciones | 1 |
| El diagnóstico se guarda y se vuelve a leer en JSON sin cambios; rechaza campos desconocidos | 2 |
| Python 3.11, 3.13, 2.7 o ilegible es un error; cualquier 3.12.x pasa | 5 |
| Falta cada uno de los tres paquetes; se informa la versión | 4 |
| Carpeta que no existe, enlace, no carpeta, sin escritura; un enlace se rechaza aunque admita escritura | 5 |
| Espacio libre: 0 bytes o sin medida es aviso; 1 byte se informa sin umbral | 3 |
| RAM y CPU sin medida son avisos; la RAM se informa en bytes; sistema operativo desconocido | 5 |
| SUMO ausente, motivo conservado, versión ilegible, otra versión | 4 |
| Varios errores: manda el primero | 1 |
| Un código de error existe si y solo si la comprobación es un error | 1 |
| Propiedad (hypothesis): para cualquier combinación de mediciones, el estado y el código de salida siguen a las comprobaciones | 1 |

**Mutaciones:** 12 errores introducidos a propósito en `doctor.py` (invertir la versión de Python, no detectar enlaces, cambiar códigos, usar el último error, ignorar avisos, entre otros). Las pruebas detectaron los 12 y el archivo quedó restaurado.

## Verificación

- `scripts/check.ps1` pasa: ruff, formato, pyright estricto, 497 pruebas pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios), contratos de referencia (43 comprobaciones), ningún código ignorado por git y ruff alineado.
- Sin cambios en el paquete de documentación del investigador (`documentacion/`).
- Ninguna prueba nueva ejecuta SUMO ni mide el equipo.

## Pendiente

- **F2:** medir el equipo (Python, paquetes, sistema, CPU, RAM con la biblioteca estándar, carpeta de trabajo y espacio) y SUMO, con las funciones de `simulacion/`.
- La documentación no tiene un caso de QA para `doctor`. Si el Product Owner quiere trazabilidad formal, hay que agregarlo al catálogo de pruebas; `documentacion/` no se modifica desde el desarrollo.
