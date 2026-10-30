"""Medición del equipo para el diagnóstico (``python -m semaforo doctor``, DEV01 F2).

Reúne lo que necesitan las reglas de ``semaforo.app.doctor``: versiones de Python y de los paquetes,
sistema operativo, CPU, RAM, carpeta de trabajo, espacio libre y SUMO. Lo que no se puede medir
queda en None y las reglas lo informan como aviso.

- La RAM se lee con la biblioteca estándar (decisión 4 de F0): ``GlobalMemoryStatusEx`` en
  Windows y ``os.sysconf`` en otros sistemas.
- La escritura en la carpeta de trabajo se prueba creando y borrando un archivo temporal. No se
  prueba a través de un enlace o una unión, que las reglas rechazan.
- SUMO se busca y se consulta con las funciones de ``semaforo.simulacion``, el único módulo que
  ejecuta procesos (regla de aislamiento).
"""

import ctypes
import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping
from importlib import metadata
from pathlib import Path

from semaforo.app.doctor import REQUIRED_PACKAGES, EnvironmentFacts, WorkspaceFacts
from semaforo.dominio.errors import DomainError
from semaforo.simulacion.runner import find_sumo, sumo_version

PROBE_PREFIX = ".doctor-"


class _MemoryStatus(ctypes.Structure):
    """Estructura ``MEMORYSTATUSEX`` de la API de Windows."""

    _fields_ = (
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    )


def package_versions(
    lookup: Callable[[str], str] = metadata.version,
) -> dict[str, str | None]:
    """Versión instalada de cada paquete de ``REQUIRED_PACKAGES``; None si falta."""
    versions: dict[str, str | None] = {}
    for name in REQUIRED_PACKAGES:
        try:
            versions[name] = lookup(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def operating_system() -> str | None:
    """Nombre del sistema operativo, por ejemplo ``Windows-11-10.0.26200-SP0``."""
    name = platform.platform()
    return name or None


def memory_bytes() -> tuple[int | None, int | None]:
    """RAM total y disponible en bytes, o None si el sistema no permite medirlas."""
    if sys.platform == "win32":
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None
        return int(status.ullTotalPhys), int(status.ullAvailPhys)
    return _posix_memory_bytes()


def _posix_memory_bytes() -> tuple[int | None, int | None]:
    """RAM con ``os.sysconf``. La disponible solo existe en algunos sistemas (Linux)."""
    if sys.platform == "win32":
        return None, None
    try:
        page = os.sysconf("SC_PAGE_SIZE")
        total = page * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        return None, None
    try:
        available: int | None = page * os.sysconf("SC_AVPHYS_PAGES")
    except (ValueError, OSError):
        available = None
    return total, available


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def can_write(folder: Path) -> bool:
    """Indica si se puede crear y borrar un archivo en ``folder``; no deja nada escrito."""
    try:
        handle, name = tempfile.mkstemp(dir=folder, prefix=PROBE_PREFIX)
    except OSError:
        return False
    os.close(handle)
    Path(name).unlink(missing_ok=True)
    return True


def workspace_facts(path: Path) -> WorkspaceFacts:
    """Lo medido de la carpeta de trabajo. Solo se prueba la escritura en una carpeta real."""
    is_link = _is_link(path)
    exists = is_link or path.exists()
    is_directory = path.is_dir()
    usable = exists and is_directory and not is_link
    return WorkspaceFacts(
        path=str(path),
        exists=exists,
        is_directory=is_directory,
        is_link=is_link,
        writable=usable and can_write(path),
    )


def free_bytes(path: Path) -> int | None:
    """Espacio libre en la unidad de ``path``, si es una carpeta real; si no, None."""
    if _is_link(path) or not path.is_dir():
        return None
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def sumo_facts(
    sumo: Path | None,
    environment: Mapping[str, str] | None = None,
    version_of: Callable[[Path], str] = sumo_version,
) -> tuple[str | None, str | None, str | None]:
    """Ruta de SUMO, su versión y, si algo falla, el motivo.

    Args:
        sumo: ejecutable indicado con ``--sumo-bin``; si es None, se busca con ``SUMO_HOME``.
        environment: variables de entorno para buscar SUMO; por defecto, las del proceso.
        version_of: función que consulta la versión (se reemplaza en las pruebas).
    """
    if sumo is None:
        try:
            binary = find_sumo(environment)
        except DomainError as error:
            return None, None, error.message
    elif sumo.is_file():
        binary = sumo
    else:
        return None, None, "no existe el ejecutable indicado en --sumo-bin"
    try:
        return str(binary), version_of(binary), None
    except DomainError as error:
        return str(binary), None, error.message


def measure_environment(
    workspace: Path,
    sumo: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> EnvironmentFacts:
    """Mide el equipo para ``semaforo.app.doctor.build_report``."""
    total, available = memory_bytes()
    binary, version, problem = sumo_facts(sumo, environment)
    return EnvironmentFacts(
        python_version=platform.python_version(),
        packages=package_versions(),
        operating_system=operating_system(),
        cpu_count=os.cpu_count(),
        memory_total_bytes=total,
        memory_available_bytes=available,
        workspace=workspace_facts(workspace),
        disk_free_bytes=free_bytes(workspace),
        sumo_binary=binary,
        sumo_version=version,
        sumo_problem=problem,
    )
