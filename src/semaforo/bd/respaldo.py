"""Respaldo y restauración de la base con las herramientas de PostgreSQL (DEV31 F3 y F4c; QA36).

``backup`` llama a ``pg_dump`` en su formato propio (comprimido) como dueño de la base y deja, junto
al archivo, su huella SHA-256 y una **ficha** (C1.8). Se guarda en ``<carpeta>/<versión del
esquema>/<fecha>.dump``: cada versión del esquema tiene su carpeta, así un respaldo del diseño
anterior no se confunde con el vigente.

La ficha dice, campo por campo, qué se sabe del respaldo y **con qué certeza**. Cada campo tiene un
estado y nunca se afirma lo que no se leyó del archivo o de una restauración:

- *verificado*: se comprobó (se calculó o se comparó);
- *declarado*: el archivo lo dice, pero no se restauró para confirmarlo;
- *no comprobado*: no se intentó comprobar (por ejemplo, la huella de un respaldo antiguo antes de
  restaurarlo);
- *desconocido*: se intentó y no se pudo saber (falta o no coincide).

Para un respaldo **nuevo**, la huella de contenido y el volcado se toman con la **misma
instantánea** de la base (``pg_export_snapshot`` y ``pg_dump --snapshot``): la ficha corresponde
exactamente a lo exportado, aunque alguien escriba mientras tanto. ``restore`` lo vuelve a cargar
en una base temporal vacía; la comparación de la huella la hace ``prueba_respaldo``.
"""

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

import psycopg
from psycopg import conninfo

from semaforo.bd.carga.insercion import Catalog
from semaforo.bd.conexion import ADMIN, CONNECT_TIMEOUT_S, BdError, connect
from semaforo.bd.esquema import installed_version
from semaforo.bd.reglas import SCHEMAS
from semaforo.bd.verificacion import HASH_ALGORITHM, content_hash
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.environment import capture_environment
from semaforo.simulacion.herramientas import run_tool
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import utc_now

__all__ = [
    "BackupReport",
    "Ficha",
    "FichaCampo",
    "backup",
    "ficha_de_archivo",
    "ficha_path",
    "pg_tool",
    "read_ficha",
    "restore",
]

TIMEOUT_S = 3600
NO_SCHEMA = "sin-esquema"
VERSION = re.compile(r"sql-[0-9a-f]{16}")
TABLE_ENTRY = re.compile(r"\sTABLE\s+(\S+)\s+(\S+)\s+\S+\s*$")
Estado = Literal["verificado", "declarado", "no_comprobado", "desconocido"]


class FichaCampo(FrozenModel):
    """Un dato de la ficha: su valor, qué tan seguro es y de dónde sale."""

    valor: str | list[str] | None
    estado: Estado
    fuente: str


class Ficha(FrozenModel):
    """Lo que se sabe de un respaldo, campo por campo (C1.8)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    archivo: str
    generada_en: datetime
    algoritmo_huella: str
    sha256: FichaCampo
    version_esquema: FichaCampo
    tablas: FichaCampo
    huella_contenido: FichaCampo
    carga_id: FichaCampo
    commit_codigo: FichaCampo


class BackupReport(FrozenModel):
    """Un respaldo hecho: archivo (relativo a la carpeta pedida), tamaño, huella y ficha."""

    file: str
    size_bytes: int
    sha256: str
    database: str
    ficha: str
    version_esquema: str | None


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


def _run(command: list[str], what: str) -> str:
    """Corre la herramienta sin la contraseña del entorno y devuelve lo que escribió."""
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
    return result.stdout


def ficha_path(dump: Path) -> Path:
    """Dónde está (o estaría) la ficha de ``dump``."""
    return dump.with_name(f"{dump.name}.ficha.json")


def read_ficha(dump: Path) -> Ficha | None:
    """La ficha de ``dump``; ``None`` si no tiene o no es una ficha válida."""
    path = ficha_path(dump)
    try:
        return Ficha.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _tables(dump: Path) -> list[str]:
    """Las tablas del proyecto que lista el catálogo del archivo (``pg_restore --list``)."""
    listing = _run([str(pg_tool("pg_restore")), "--list", str(dump)], "pg_restore")
    found: set[str] = set()
    for line in listing.splitlines():
        match = TABLE_ENTRY.search(line)
        if match is not None and match[1] in SCHEMAS:
            found.add(f"{match[1]}.{match[2]}")
    return sorted(found)


def _declared_version(dump: Path) -> str | None:
    """La versión del esquema que dice el texto del archivo (solo la parte del esquema)."""
    text = _run([str(pg_tool("pg_restore")), "--schema-only", "--file=-", str(dump)], "pg_restore")
    found = sorted(set(VERSION.findall(text)))
    return found[0] if len(found) == 1 else None


def _write_ficha(dump: Path, ficha: Ficha) -> None:
    ficha_path(dump).write_text(ficha.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _commit() -> str | None:
    return capture_environment().get("commit")


def backup(folder: Path, *, database: str | None = None) -> BackupReport:
    """Respalda la base en ``folder/<versión>/<fecha>.dump``, con su huella y su ficha al lado.

    La huella de contenido y el volcado salen de la **misma instantánea** de la base.

    Raises:
        BdError: DEPENDENCY_MISSING si falta ``pg_dump``; OUTPUT_INVALID si el respaldo falla.
    """
    with connect(ADMIN, database=database) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        row = connection.execute("SELECT pg_export_snapshot()").fetchone()
        snapshot = "" if row is None else str(row[0])
        digest, _ = content_hash(connection, Catalog.load(connection))
        version = installed_version(connection)
        last = connection.execute(
            "SELECT carga_id FROM control.cargas WHERE estado = 'completed' "
            "ORDER BY inicio DESC LIMIT 1"
        ).fetchone()
        target = folder / (version or NO_SCHEMA)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{utc_now():%Y%m%dT%H%M%SZ}.dump"
        if path.exists():
            raise BdError(ErrorCode.RUN_EXISTS, "ya hay un respaldo con esa fecha", path.name)
        _run(
            [
                str(pg_tool("pg_dump")),
                "--format=custom",
                "--no-password",
                f"--snapshot={snapshot}",
                f"--file={path}",
                _target(database),
            ],
            "pg_dump",
        )
        connection.rollback()
    file_digest = sha256_file(path)
    (target / f"{path.name}.sha256").write_text(f"{file_digest}  {path.name}\n", encoding="utf-8")
    exported = "la misma instantánea de la base que se exportó"
    load = None if last is None else str(last[0])
    ficha = Ficha(
        archivo=path.name,
        generada_en=utc_now(),
        algoritmo_huella=HASH_ALGORITHM,
        sha256=FichaCampo(valor=file_digest, estado="verificado", fuente="calculado del archivo"),
        version_esquema=FichaCampo(
            valor=version,
            estado="verificado" if version else "desconocido",
            fuente=exported,
        ),
        tablas=FichaCampo(
            valor=_tables(path), estado="verificado", fuente="catálogo del archivo (pg_restore)"
        ),
        huella_contenido=FichaCampo(valor=digest, estado="verificado", fuente=exported),
        carga_id=FichaCampo(
            valor=load,
            estado="verificado" if load else "desconocido",
            fuente="última carga completa de la misma instantánea",
        ),
        commit_codigo=FichaCampo(
            valor=_commit(), estado="verificado", fuente="código que hizo el respaldo"
        ),
    )
    _write_ficha(path, ficha)
    return BackupReport(
        file=path.relative_to(folder).as_posix(),
        size_bytes=path.stat().st_size,
        sha256=file_digest,
        database=database or "semaforo",
        ficha=ficha_path(path).relative_to(folder).as_posix(),
        version_esquema=version,
    )


def ficha_de_archivo(dump: Path) -> Ficha:
    """Escribe la ficha de un respaldo que ya existe, con lo que se puede comprobar sin restaurar.

    - la huella del archivo se compara con su ``.sha256``: *verificado* si coincide, *desconocido*
      si no coincide o no hay con qué compararla;
    - la versión del esquema es *declarada* (el texto del archivo la dice una sola vez); si no se
      puede leer o dice varias, es *desconocida*;
    - las tablas salen del catálogo del archivo (*verificado*);
    - la huella de contenido, la carga y el commit quedan *no comprobados*: se saben restaurando
      (``prueba_respaldo``).

    El archivo del respaldo no se mueve ni se modifica. Una ficha que ya existe no se reescribe: la
    que salió junto con el respaldo, de la misma instantánea, sabe más que esta.

    Raises:
        BdError: INPUT_SCHEMA si ``dump`` no existe o ya tiene ficha; DEPENDENCY_MISSING si falta
            ``pg_restore``.
    """
    if not dump.is_file():
        raise BdError(ErrorCode.INPUT_SCHEMA, "no existe el respaldo", dump.name)
    if ficha_path(dump).exists():
        raise BdError(ErrorCode.INPUT_SCHEMA, "el respaldo ya tiene ficha", ficha_path(dump).name)
    digest = sha256_file(dump)
    recorded = dump.with_name(f"{dump.name}.sha256")
    try:
        expected = recorded.read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        expected = None
    if expected is None:
        sha = FichaCampo(valor=digest, estado="desconocido", fuente="falta su archivo .sha256")
    elif expected == digest:
        sha = FichaCampo(valor=digest, estado="verificado", fuente="coincide con su .sha256")
    else:
        sha = FichaCampo(valor=digest, estado="desconocido", fuente="NO coincide con su .sha256")
    version = _declared_version(dump)
    pending = FichaCampo(valor=None, estado="no_comprobado", fuente="se sabe al restaurar")
    ficha = Ficha(
        archivo=dump.name,
        generada_en=utc_now(),
        algoritmo_huella=HASH_ALGORITHM,
        sha256=sha,
        version_esquema=FichaCampo(
            valor=version,
            estado="declarado" if version else "desconocido",
            fuente="texto del archivo (pg_restore)"
            if version
            else "el archivo no dice una sola versión",
        ),
        tablas=FichaCampo(
            valor=_tables(dump), estado="verificado", fuente="catálogo del archivo (pg_restore)"
        ),
        huella_contenido=pending,
        carga_id=pending,
        commit_codigo=pending,
    )
    _write_ficha(dump, ficha)
    return ficha


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
