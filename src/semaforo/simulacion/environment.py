"""Con qué código y en qué equipo corrió un proceso (DEV31 F2; indicador I7 de la tesis).

``capture_environment`` devuelve los datos que el manifiesto de una corrida suma a la versión de
SUMO, de Python y del sistema operativo:

- ``commit``: el commit del proyecto, y ``code_modified`` (``true``/``false``) si los archivos que
  git sigue tenían cambios sin confirmar. Sin git o fuera de un repositorio, ninguno de los dos.
- ``cpu``, ``cpu_cores`` y ``memory_gb``: el procesador, los núcleos lógicos y la memoria total.
- ``location``: ``local`` o ``cloud``. Y, si es ``cloud``, ``cloud_provider``, ``machine_type`` y
  ``region``, cuando se conocen.

No usa la red y no guarda el nombre del equipo ni rutas. Un dato que no se puede obtener se omite:
«no registrado» no es lo mismo que cero. La ubicación se declara con variables de entorno
(``SEMAFORO_UBICACION`` = ``local`` o ``nube``; ``SEMAFORO_NUBE_PROVEEDOR``,
``SEMAFORO_NUBE_TIPO_MAQUINA`` y ``SEMAFORO_NUBE_REGION``); sin declaración se supone ``local``,
salvo que el equipo se presente como una máquina de una nube conocida (``/sys/class/dmi``).
Funciona igual con cualquier proveedor: no depende de ninguno.
"""

import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from semaforo.simulacion.resources import total_memory_bytes

__all__ = ["PROJECT_ROOT", "capture_environment"]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GIT_TIMEOUT_S = 10.0
GIB = 1024**3
MAX_TEXT_CHARS = 100
COMMIT = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
CPU_REGISTRY_KEY = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
DMI_FOLDER = Path("/sys/class/dmi/id")
# Fabricantes que el equipo declara cuando es una máquina virtual de una nube.
CLOUD_VENDORS = frozenset(
    {"Amazon EC2", "Google", "DigitalOcean", "Hetzner", "Alibaba Cloud", "OpenStack Foundation"}
)
UNIDENTIFIED = "no identificado"
LOCATION_VARIABLE = "SEMAFORO_UBICACION"
PROVIDER_VARIABLE = "SEMAFORO_NUBE_PROVEEDOR"
MACHINE_VARIABLE = "SEMAFORO_NUBE_TIPO_MAQUINA"
REGION_VARIABLE = "SEMAFORO_NUBE_REGION"


def _clean(text: str | None) -> str | None:
    """El texto sin espacios repetidos y recortado; ``None`` si queda vacío."""
    if text is None:
        return None
    one_line = "".join(character if character.isprintable() else " " for character in text)
    cleaned = " ".join(one_line.split())[:MAX_TEXT_CHARS]
    return cleaned or None


def _git(root: Path, *arguments: str) -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603  (lista de argumentos fija, sin shell)
            [git, "-C", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _code(root: Path) -> dict[str, str]:
    commit = _git(root, "rev-parse", "HEAD")
    if commit is None or COMMIT.fullmatch(commit) is None:
        return {}
    changes = _git(root, "status", "--porcelain", "--untracked-files=no")
    if changes is None:
        return {"commit": commit}
    return {"commit": commit, "code_modified": "true" if changes else "false"}


def _cpu_name() -> str | None:
    if sys.platform == "win32":
        import winreg  # noqa: PLC0415  (solo existe en Windows)

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, CPU_REGISTRY_KEY) as key:
                name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        except OSError:
            return _clean(platform.processor())
        return _clean(str(name))
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _clean(platform.processor())
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            return _clean(line.partition(":")[2])
    return _clean(platform.processor())


def _machine() -> dict[str, str]:
    found: dict[str, str] = {}
    cpu = _cpu_name()
    if cpu is not None:
        found["cpu"] = cpu
    cores = os.cpu_count()
    if cores is not None and cores > 0:
        found["cpu_cores"] = str(cores)
    memory = total_memory_bytes()
    if memory is not None and memory > 0:
        found["memory_gb"] = f"{memory / GIB:.1f}"
    return found


def _dmi(name: str) -> str | None:
    try:
        return _clean((DMI_FOLDER / name).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None


def _location(environ: Mapping[str, str]) -> dict[str, str]:
    """Ubicación declarada, o deducida; vacía si la declaración no es ``local`` ni ``nube``."""
    declared = _clean(environ.get(LOCATION_VARIABLE))
    vendor = _dmi("sys_vendor")
    if declared is None:
        in_cloud = vendor in CLOUD_VENDORS
    elif declared.lower() in ("local", "nube"):
        in_cloud = declared.lower() == "nube"
    else:
        return {}
    if not in_cloud:
        return {"location": "local"}
    result = {"location": "cloud"}
    provider = _clean(environ.get(PROVIDER_VARIABLE)) or vendor or UNIDENTIFIED
    machine = _clean(environ.get(MACHINE_VARIABLE)) or _dmi("product_name")
    region = _clean(environ.get(REGION_VARIABLE))
    result["cloud_provider"] = provider
    if machine is not None:
        result["machine_type"] = machine
    if region is not None:
        result["region"] = region
    return result


def capture_environment(
    root: Path = PROJECT_ROOT, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Commit del código y equipo del proceso actual, para el ``environment`` del manifiesto.

    Args:
        root: carpeta del proyecto, donde se consulta git.
        environ: variables de entorno con la ubicación declarada; por defecto, las del proceso.
    """
    variables = os.environ if environ is None else environ
    return {**_code(root), **_machine(), **_location(variables)}
