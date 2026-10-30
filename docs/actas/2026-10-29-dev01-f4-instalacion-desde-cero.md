# Acta 2026-10-29: DEV01 · F4 (instalación desde cero y registro de versiones)

- **Tipo:** registro de fase del plan de DEV01 (HU01, HU14). Es la verificación que fija `02_Requisitos_y_plan.md` para DEV01: «Instalar desde cero y registrar versiones».
- **Autorización:** el Product Owner autorizó F4 («ejecuta f4»).
- **Siguiente fase:** F5 (cierre de DEV01), a la espera de su autorización.

## Qué se hizo

**1. uv en el PATH.** uv 0.13.6 estaba instalado desde F0 (`python -m pip install --user uv`), pero su ejecutable quedó en `%APPDATA%\Python\Python312\Scripts`, una carpeta fuera del PATH. Se agregó esa carpeta al final de la variable `Path` del usuario, sin modificar las demás entradas: pasa de 14 a 15. El valor anterior se guardó como copia fuera del repositorio. Con el PATH nuevo, `uv --version` responde `uv 0.13.6`.

**2. `README.md`.** Requisitos en Windows, cómo instalar uv, instalación desde cero paso a paso, uso de `doctor` con sus códigos de salida, verificaciones de desarrollo (`scripts/check.ps1` y hooks) y dónde está la documentación. Commit `7d465c0`.

**3. Instalación desde cero.** En una carpeta nueva fuera del repositorio y con el PATH recién configurado, como en una terminal recién abierta, se siguieron los pasos del `README.md`:

| Paso | Resultado |
|---|---|
| `git clone` | commit `7d465c0` |
| `uv sync --frozen` | código 0; crea `.venv` e instala lo de `uv.lock` |
| `uv lock --check` | código 0: `uv.lock` coincide con `pyproject.toml` (49 paquetes resueltos) |
| `New-Item -ItemType Directory datos` | carpeta de trabajo creada |
| `.venv\Scripts\python.exe -m semaforo doctor` | «Diagnóstico todo bien (código de salida 0)»; las 12 comprobaciones en `ok` |
| `scripts/check.ps1` | pasa: ruff, formato, pyright estricto, 528 pruebas pasan y 1 se salta de forma declarada (enlaces simbólicos sin privilegios), contratos de referencia, ningún código ignorado y ruff alineado |

**Diferencia con el `README.md`:** se clonó el repositorio local y no el de GitHub, porque los commits de DEV01 todavía no se habían subido. El contenido clonado es el mismo commit que tendrá GitHub después del push.

## Versiones registradas (equipo del Product Owner, 2026-10-29)

| Componente | Versión |
|---|---|
| Sistema operativo | Windows-11-10.0.26200-SP0 |
| CPU / RAM total | 16 procesadores lógicos / 15,4 GiB |
| Python | 3.12.3 |
| uv | 0.13.6 |
| Git | 2.49.0.windows.1 |
| SUMO | 1.27.1 |
| semaforo | 0.1.0 |
| pydantic | 2.14.1 |
| defusedxml | 0.7.1 |
| pytest | 9.1.1 |
| hypothesis | 6.170.3 |
| ruff | 0.17.1 |
| pyright | 1.1.414 |
| pre-commit | 4.7.0 |
| pip-audit | 2.10.1 |

Las versiones de Python, sistema, CPU, RAM, paquetes de ejecución y SUMO salen de `doctor`. Las de las herramientas de desarrollo salen de `uv pip list` en el entorno recién instalado. El `.venv` del repositorio original se había creado con uv 0.13.2; ambos entornos salen del mismo `uv.lock`.

## No verificado

- Clonar desde GitHub. Se podrá hacer después del push.
- La ruta de menús de Windows para editar la variable `Path` que indica el `README.md` se escribió de memoria; no se recorrió en la interfaz.
- `pre-commit install` en el entorno nuevo. Es opcional y solo afecta a quien hace commits.
- Otro equipo: la instalación se probó en el del Product Owner.

## Verificación

- La carpeta de la instalación de prueba queda fuera del repositorio. Se puede borrar.
- Sin cambios en el código ni en el paquete de documentación del investigador (`documentacion/`).
