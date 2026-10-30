# Acta 2026-10-29: DEV01 · F3 (comando `doctor`)

- **Tipo:** registro de fase del plan de DEV01 (HU01, HU14)
- **Autorización:** el Product Owner autorizó F3 («Ejecuta F3»).
- **Siguiente fase:** F4 (instalación desde cero y registro de versiones), a la espera de su autorización.

## Qué se hizo

El comando `python -m semaforo doctor`, con los parámetros que fija el diseño técnico («CLI propuesta»: `--workspace --sumo-bin`).

| Archivo | Contenido |
|---|---|
| `src/semaforo/cli/doctor.py` | argumento `--sumo-bin`, ejecución del diagnóstico (medición de F2 y reglas de F1) y resumen para la persona. Es el archivo que propone `02_Requisitos_y_plan.md` |
| `src/semaforo/cli/main.py` | `doctor` como comando de primer nivel, con `--workspace` (por defecto `datos`) y `--debug`, igual que los comandos de `case` |
| `tests/unit/test_doctor_cli.py` | 11 pruebas sin medir el equipo |
| `tests/e2e/test_cli_doctor.py` | 3 pruebas que ejecutan el comando en un proceso aparte |

**Cómo responde**, igual que el resto de la CLI (diseño técnico, «Errores y códigos de salida»):
- **Salida estándar:** solo el diagnóstico en JSON (`schema_version` 1.0.0, estado, código de salida y comprobaciones).
- **Salida de error:** una línea por comprobación (`[bien]`, `[AVISO]` o `[ERROR]`) y el resultado final, por ejemplo «Diagnóstico todo bien (código de salida 0)».
- **Código de salida:** 0 si está todo bien o solo hay avisos; 2 si la carpeta de trabajo no existe; 3 si falta una dependencia (Python, paquetes o SUMO); 5 si la carpeta es un enlace, no es carpeta o no admite escritura; 1 si hay un error interno, sin mostrar la traza salvo con `--debug`.

**Cómo usarlo**, en PowerShell, desde la carpeta del repositorio:

```powershell
.venv\Scripts\python.exe -m semaforo doctor
.venv\Scripts\python.exe -m semaforo doctor --workspace datos --sumo-bin "C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"
```

Sin `--sumo-bin`, SUMO se busca con `SUMO_HOME`.

En el equipo del Product Owner (2026-10-29), `doctor` sin argumentos da «Diagnóstico todo bien (código de salida 0)», con las mismas versiones que el acta de F2.

## Pruebas

| Archivo | Qué se prueba | Pruebas |
|---|---|---|
| `test_doctor_cli.py` | todo bien da código 0 y su resumen; con avisos, código 0; sin SUMO, sin carpeta o con carpeta enlazada dan 3, 2 y 5; valores por defecto (`datos` y `SUMO_HOME`); los argumentos llegan a la medición; la salida estándar es solo el JSON; error interno oculto (1) y visible con `--debug`; argumento desconocido (2) | 11 |
| `test_cli_doctor.py` | con el SUMO instalado, código 0 sin dejar archivos en la carpeta de trabajo; `--sumo-bin` inexistente da 3; carpeta inexistente da 2 y no se crea | 3 |

**Mutaciones:** 10 errores introducidos a propósito en `main.py` y `doctor.py` (devolver siempre 0, ignorar `--sumo-bin` o `--workspace`, no escribir el JSON o el resumen, cambiar las etiquetas, cambiar el valor por defecto de `--sumo-bin`, entre otros). Las pruebas detectaron los 10, y los archivos quedaron restaurados.

**Nombre de archivo:** la prueba unitaria se llama `test_doctor_cli.py` y no `test_cli_doctor.py`, porque pytest no admite dos archivos de prueba con el mismo nombre en carpetas sin paquete.

## Verificación

- `scripts/check.ps1` pasa: ruff, formato, pyright estricto, 528 pruebas pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios), contratos de referencia (43 comprobaciones), ningún código ignorado por git y ruff alineado.
- La CLI solo importa `app` (ADR01, `tests/unit/test_arquitectura.py`).
- Sin cambios en el paquete de documentación del investigador (`documentacion/`).

## Pendiente

- **F4:** `README.md` con la instalación en Windows; dejar `uv` en el PATH; instalación desde cero en una carpeta temporal; `doctor` en el equipo del Product Owner y registro de versiones.
- El caso de QA para `doctor` sigue pendiente de decisión del Product Owner (ver acta de F1).
