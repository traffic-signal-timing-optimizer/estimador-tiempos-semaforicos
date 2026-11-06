"""Respaldo y restauración de la base con las herramientas de PostgreSQL (DEV31 F3; QA36).

``backup`` llama a ``pg_dump`` en su formato propio (comprimido) como dueño de la base y deja,
junto al archivo, su huella SHA-256. ``restore`` lo vuelve a cargar en una base temporal vacía; las
pruebas comparan la huella de contenido antes y después. Las herramientas se buscan en
``SEMAFORO_PG_BIN``, en el PATH o en la instalación estándar de PostgreSQL para Windows.
"""

import os
import shutil
import sys
from pathlib import Path

from psycopg import conninfo

from semaforo.bd.conexion import ADMIN, CONNECT_TIMEOUT_S, BdError
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.herramientas import run_tool
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import utc_now

__all__ = ["BackupReport", "backup", "pg_tool", "restore"]

TIMEOUT_S = 3600


class BackupReport(FrozenModel):
    """Un respaldo hecho: archivo (dentro de la carpeta pedida), tamaño y huella."""

    file: str
    size_bytes: int
    sha256: str
    database: str


def pg_tool(name: str) -> Path:
    """La ruta de ``pg_dump`` o ``pg_restore``.

    Raises:
        BdError: DEPENDENCY_MISSING si no se encuentra.
    """
    exe = f"{name}.exe" if sys.platform == "win32" else name
    chosen = os.environ.get("SEMAFORO_PG_BIN")
    if chosen and (Path(chosen) / exe).is_file():
        return Path(chosen) / exe
    found = shutil.which(name)
    if found:
        return Path(found)
    if sys.platform == "win32":
        root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
        versions = sorted(
            (p for p in root.glob(f"*/bin/{exe}") if p.parent.parent.name.isdigit()),
            key=lambda p: int(p.parent.parent.name),
        )
        if versions:
            return versions[-1]
    raise BdError(ErrorCode.DEPENDENCY_MISSING, f"no se encuentra {name} de PostgreSQL", name)


def _target(database: str | None) -> str:
    options: dict[str, str | int] = {"service": ADMIN, "connect_timeout": CONNECT_TIMEOUT_S}
    if database is not None:
        options["dbname"] = database
    return conninfo.make_conninfo("", **options)


def _run(command: list[str], what: str) -> None:
    environment = {key: value for key, value in os.environ.items() if key != "PGPASSWORD"}
    result = run_tool(command, timeout_s=TIMEOUT_S, environment=environment)
    if result is None:
        raise BdError(ErrorCode.DEPENDENCY_MISSING, f"{what} no se pudo ejecutar a tiempo", what)
    if result.returncode != 0:
        first = result.stderr.strip().splitlines()
        raise BdError(
            ErrorCode.OUTPUT_INVALID,
            f"{what} falló: {first[0] if first else result.returncode}",
            what,
        )


def backup(folder: Path, *, database: str | None = None) -> BackupReport:
    """Respalda la base en ``folder/<fecha UTC>.dump`` y escribe su huella al lado.

    Raises:
        BdError: DEPENDENCY_MISSING si falta ``pg_dump``; OUTPUT_INVALID si el respaldo falla.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{utc_now():%Y%m%dT%H%M%SZ}.dump"
    if path.exists():
        raise BdError(ErrorCode.RUN_EXISTS, "ya hay un respaldo con esa fecha", path.name)
    _run(
        [
            str(pg_tool("pg_dump")),
            "--format=custom",
            "--no-password",
            f"--file={path}",
            _target(database),
        ],
        "pg_dump",
    )
    digest = sha256_file(path)
    (folder / f"{path.name}.sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return BackupReport(
        file=path.name,
        size_bytes=path.stat().st_size,
        sha256=digest,
        database=database or "semaforo",
    )


def restore(path: Path, database: str) -> None:
    """Restaura el respaldo ``path`` en la base vacía ``database`` (normalmente temporal).

    Raises:
        BdError: HASH_MISMATCH si el archivo no tiene la huella de su ``.sha256``;
            DEPENDENCY_MISSING u OUTPUT_INVALID si ``pg_restore`` falta o falla.
    """
    recorded = path.with_name(f"{path.name}.sha256")
    if recorded.is_file():
        expected = recorded.read_text(encoding="utf-8").split()[0]
        if sha256_file(path) != expected:
            raise BdError(ErrorCode.HASH_MISMATCH, "el respaldo cambió", path.name)
    _run(
        [
            str(pg_tool("pg_restore")),
            "--no-password",
            "--exit-on-error",
            f"--dbname={_target(database)}",
            str(path),
        ],
        "pg_restore",
    )
