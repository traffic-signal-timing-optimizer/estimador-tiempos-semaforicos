# Acta 2026-10-29: DEV01 · F2 (medición del equipo y de SUMO)

- **Tipo:** registro de fase del plan de DEV01 (HU01, HU14)
- **Autorización:** el Product Owner autorizó F2 («ejecuta f2 si ya no hay pendientes de f1»). F1 no tenía pendientes propios: su acta solo dejaba F2 y el caso de QA, que decide el Product Owner.
- **Siguiente fase:** F3 (comando `python -m semaforo doctor`), a la espera de su autorización.

## Qué se hizo

`src/semaforo/app/doctor_probe.py` mide el equipo y entrega a las reglas de F1 (`build_report`) lo que necesitan. Lo que no se puede medir queda en None, y las reglas lo informan como aviso.

| Medición | Cómo |
|---|---|
| Python | `platform.python_version()` |
| Paquetes `semaforo`, `pydantic`, `defusedxml` | metadatos de los paquetes instalados (`importlib.metadata`); None si falta |
| Sistema operativo y CPU | `platform.platform()` y `os.cpu_count()` |
| RAM total y disponible | biblioteca estándar, sin dependencias nuevas (decisión 4 de F0): `GlobalMemoryStatusEx` en Windows; `os.sysconf` en otros sistemas |
| Carpeta de trabajo | si existe, si es enlace o unión, si es carpeta. La escritura se prueba creando y borrando un archivo temporal (`.doctor-…`), solo en una carpeta real: nunca a través de un enlace |
| Espacio libre | `shutil.disk_usage`, solo en una carpeta real |
| SUMO | el ejecutable de `--sumo-bin` o, si no se indica, el de `SUMO_HOME`; la versión, con `sumo --version`. Se usan las funciones de `simulacion/runner.py`, el único módulo que ejecuta procesos |

## Medición en el equipo del Product Owner (2026-10-29)

Con la carpeta `datos/` y el SUMO de `SUMO_HOME`, el diagnóstico queda `ok` con código de salida 0:

| Comprobación | Valor |
|---|---|
| Python | 3.12.3 |
| Paquetes | semaforo 0.1.0, pydantic 2.14.1, defusedxml 0.7.1 |
| Sistema operativo | Windows-11-10.0.26200-SP0 |
| CPU | 16 procesadores lógicos |
| RAM total | 15,4 GiB |
| SUMO | 1.27.1 |

La RAM disponible y el espacio libre cambian de un momento a otro, así que no se registran aquí. La prueba de escritura no dejó archivos en `datos/`. El registro formal de versiones de la instalación desde cero es de F4.

## Pruebas

| Archivo | Qué se prueba | Pruebas |
|---|---|---|
| `tests/unit/test_doctor_probe.py` | versiones de los paquetes y paquete faltante; RAM medida (en Windows, disponible ≤ total); carpeta real con escritura; la prueba de escritura no deja nada; permiso denegado (simulado); carpeta inexistente; archivo en lugar de carpeta; unión de Windows: se detecta, no se escribe a través de ella y no se mide su espacio; espacio libre; SUMO por `SUMO_HOME`; `--sumo-bin` manda sobre `SUMO_HOME`; sin `SUMO_HOME`; `--sumo-bin` inexistente; SUMO que no responde; medición completa de este equipo sin SUMO: el único error es SUMO | 16 |
| `tests/integration/test_doctor_sumo.py` | con el SUMO instalado, se encuentra y responde su versión, sin errores | 1 |

**Mutaciones:** 12 errores introducidos a propósito en `doctor_probe.py` (no detectar uniones, escribir a través de un enlace, no borrar el archivo de prueba, aceptar cualquier `--sumo-bin`, perder el motivo del fallo de SUMO, invertir RAM total y disponible, entre otros). Las pruebas detectaron los 12, y el archivo quedó restaurado con sus finales de línea.

**Permiso denegado:** en Windows, quitar el permiso de escritura a una carpeta exige cambiar sus permisos de seguridad (ACL). Por eso la prueba simula el fallo al crear el archivo, en lugar de hacerlo con una carpeta real.

## Verificación

- `scripts/check.ps1` pasa: ruff, formato, pyright estricto, 514 pruebas pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios), contratos de referencia (43 comprobaciones), ningún código ignorado por git y ruff alineado.
- Ningún módulo fuera de `simulacion/` ejecuta procesos (`tests/unit/test_estructura.py`).
- Sin cambios en el paquete de documentación del investigador (`documentacion/`).

## Pendiente

- **F3:** el comando `python -m semaforo doctor --workspace … --sumo-bin …`, con el diagnóstico en JSON por la salida estándar y un resumen para la persona en la salida de error.
- El caso de QA para `doctor` sigue pendiente de decisión del Product Owner (ver acta de F1).
