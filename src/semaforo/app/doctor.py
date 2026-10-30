"""Diagnóstico del entorno de trabajo: ``python -m semaforo doctor`` (DEV01).

Este módulo contiene las reglas: a partir de lo medido en el equipo (``EnvironmentFacts``) decide
el estado de cada comprobación y el código de salida. La medición se añade en F2.

Decisiones de F0 (acta ``2026-10-29-dev01-f0-decisiones.md``):

- el espacio libre y la RAM solo se informan: los umbrales los fija el piloto;
- la versión de SUMO esperada es 1.27.1; otra versión es un aviso, no un error;
- solo es un error lo indispensable: Python 3.12, las dependencias del paquete, SUMO ejecutable con
  versión legible y una carpeta de trabajo donde se pueda escribir.

Códigos de los errores (diseño técnico, «Errores y códigos de salida»): DEPENDENCY_MISSING (3) para
Python, paquetes y SUMO; INPUT_SCHEMA (2) si la carpeta de trabajo no existe; PATH_NOT_ALLOWED (5)
si es un enlace, no es una carpeta o no se puede escribir en ella. Con varios errores, el código de
salida es el del primero en el orden de las comprobaciones.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from semaforo.app.doctor_models import Check, DoctorReport, DoctorStatus
from semaforo.app.exit_codes import exit_code_for
from semaforo.dominio.errors import ErrorCode

REQUIRED_PYTHON = (3, 12)
EXPECTED_SUMO_VERSION = "1.27.1"
REQUIRED_PACKAGES = ("semaforo", "pydantic", "defusedxml")
_PYTHON_VERSION = re.compile(r"^(\d+)\.(\d+)(?:\.\d+)?")
_GIB = 1024**3


@dataclass(frozen=True)
class WorkspaceFacts:
    """Lo medido de la carpeta de trabajo."""

    path: str
    exists: bool
    is_directory: bool
    is_link: bool
    writable: bool


@dataclass(frozen=True)
class EnvironmentFacts:
    """Lo medido en el equipo. None significa que no se pudo medir.

    ``packages`` asocia cada paquete con su versión instalada, o None si falta. ``sumo_problem``
    explica, si lo hay, por qué no se encontró SUMO o no se leyó su versión.
    """

    python_version: str
    packages: Mapping[str, str | None]
    operating_system: str | None
    cpu_count: int | None
    memory_total_bytes: int | None
    memory_available_bytes: int | None
    workspace: WorkspaceFacts
    disk_free_bytes: int | None
    sumo_binary: str | None
    sumo_version: str | None
    sumo_problem: str | None = None


def _ok(name: str, value: str | int | None, message: str) -> Check:
    return Check(name=name, status="ok", value=value, message=message)


def _warning(name: str, value: str | int | None, message: str) -> Check:
    return Check(name=name, status="warning", value=value, message=message)


def _error(name: str, value: str | int | None, message: str, code: ErrorCode) -> Check:
    return Check(name=name, status="error", value=value, message=message, code=code.value)


def _gib(value: int) -> str:
    return f"{value / _GIB:.1f} GiB"


def check_python(version: str) -> Check:
    """Python debe ser 3.12, como fija ``pyproject.toml``."""
    required = ".".join(str(part) for part in REQUIRED_PYTHON)
    match = _PYTHON_VERSION.match(version)
    if match is None:
        message = f"no se reconoce la versión de Python; se necesita {required}"
        return _error("python", version, message, ErrorCode.DEPENDENCY_MISSING)
    if (int(match.group(1)), int(match.group(2))) != REQUIRED_PYTHON:
        message = f"se necesita Python {required}"
        return _error("python", version, message, ErrorCode.DEPENDENCY_MISSING)
    return _ok("python", version, f"Python {version}")


def check_packages(packages: Mapping[str, str | None]) -> list[Check]:
    """Cada paquete de ``REQUIRED_PACKAGES`` debe estar instalado; se informa su versión."""
    checks: list[Check] = []
    for name in REQUIRED_PACKAGES:
        version = packages.get(name)
        check_name = f"package:{name}"
        if version is None:
            message = f"falta el paquete {name}: instale las dependencias desde el lock"
            checks.append(_error(check_name, None, message, ErrorCode.DEPENDENCY_MISSING))
        else:
            checks.append(_ok(check_name, version, f"{name} {version}"))
    return checks


def check_operating_system(name: str | None) -> Check:
    """Sistema operativo, solo informativo."""
    if name is None:
        return _warning("os", None, "no se pudo identificar el sistema operativo")
    return _ok("os", name, name)


def check_cpu(count: int | None) -> Check:
    """Procesadores lógicos, solo informativo."""
    if count is None or count <= 0:
        return _warning("cpu", None, "no se pudo medir la cantidad de procesadores")
    return _ok("cpu", count, f"{count} procesadores lógicos")


def check_memory(total: int | None, available: int | None) -> list[Check]:
    """RAM total y disponible, solo informativas (decisión 2 de F0)."""
    checks: list[Check] = []
    for name, value, label in (
        ("memory_total", total, "total"),
        ("memory_available", available, "disponible"),
    ):
        if value is None:
            checks.append(_warning(name, None, f"no se pudo medir la RAM {label}"))
        else:
            checks.append(_ok(name, value, f"RAM {label}: {_gib(value)}"))
    return checks


def check_workspace(workspace: WorkspaceFacts) -> Check:
    """La carpeta de trabajo debe existir, ser una carpeta real y admitir escritura."""
    path = workspace.path
    if not workspace.exists:
        message = "la carpeta de trabajo no existe"
        return _error("workspace", path, message, ErrorCode.INPUT_SCHEMA)
    if workspace.is_link:
        message = "la carpeta de trabajo es un enlace o una unión; use la carpeta real"
        return _error("workspace", path, message, ErrorCode.PATH_NOT_ALLOWED)
    if not workspace.is_directory:
        message = "la ruta de trabajo no es una carpeta"
        return _error("workspace", path, message, ErrorCode.PATH_NOT_ALLOWED)
    if not workspace.writable:
        message = "no se puede escribir en la carpeta de trabajo"
        return _error("workspace", path, message, ErrorCode.PATH_NOT_ALLOWED)
    return _ok("workspace", path, "carpeta de trabajo con permiso de escritura")


def check_disk(free: int | None) -> Check:
    """Espacio libre en la unidad de la carpeta de trabajo, sin umbral (decisión 2 de F0).

    Solo es un aviso si no se pudo medir o si no queda ningún byte libre.
    """
    if free is None:
        return _warning("disk_free", None, "no se pudo medir el espacio libre")
    if free == 0:
        return _warning("disk_free", 0, "no queda espacio libre en la unidad de trabajo")
    return _ok("disk_free", free, f"{_gib(free)} libres en la unidad de trabajo")


def check_sumo(binary: str | None, version: str | None, problem: str | None) -> list[Check]:
    """SUMO debe encontrarse y responder con su versión; se espera 1.27.1 (decisión 3 de F0)."""
    if binary is None:
        message = problem or "no se encuentra SUMO: indique --sumo-bin o configure SUMO_HOME"
        return [
            _error("sumo", None, message, ErrorCode.DEPENDENCY_MISSING),
            _warning("sumo_version", None, "no se comprobó porque falta SUMO"),
        ]
    found = _ok("sumo", binary, "SUMO encontrado")
    if version is None:
        detail = f": {problem}" if problem else ""
        message = f"no se pudo leer la versión de SUMO{detail}"
        return [found, _error("sumo_version", None, message, ErrorCode.DEPENDENCY_MISSING)]
    if version != EXPECTED_SUMO_VERSION:
        message = f"SUMO {version}; se esperaba {EXPECTED_SUMO_VERSION}"
        return [found, _warning("sumo_version", version, message)]
    return [found, _ok("sumo_version", version, f"SUMO {version}")]


def build_report(facts: EnvironmentFacts) -> DoctorReport:
    """Diagnóstico a partir de lo medido, con el estado y el código de salida."""
    checks = [
        check_python(facts.python_version),
        *check_packages(facts.packages),
        check_operating_system(facts.operating_system),
        check_cpu(facts.cpu_count),
        *check_memory(facts.memory_total_bytes, facts.memory_available_bytes),
        check_workspace(facts.workspace),
        check_disk(facts.disk_free_bytes),
        *check_sumo(facts.sumo_binary, facts.sumo_version, facts.sumo_problem),
    ]
    errors = [check for check in checks if check.status == "error"]
    status: DoctorStatus
    if errors:
        status = "failed"
    elif any(check.status == "warning" for check in checks):
        status = "warnings"
    else:
        status = "ok"
    first_code = errors[0].code if errors else None
    exit_code = 0 if first_code is None else exit_code_for(first_code)
    return DoctorReport(status=status, exit_code=exit_code, checks=checks)
