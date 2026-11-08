"""«bd iniciar»: prepara PostgreSQL para el proyecto, una sola vez (DEV31 F3).

Con el administrador del servicio (``postgres``; su contraseña la da el PO en la variable
``PGPASSWORD`` solo para este comando y no se guarda en ningún lado):

1. crea la carpeta de los datos (por ejemplo ``D:\\pgdata\\semaforo``), le da permiso a la cuenta
   del servicio y la registra como espacio de tablas ``semaforo``;
2. crea los tres usuarios del proyecto con contraseñas nuevas y aleatorias, que se escriben solo
   en el ``pgpass.conf`` del usuario de Windows, junto con sus datos de conexión en el archivo de
   servicios. Las líneas de otros proyectos de esos archivos se conservan tal cual;
3. crea la base ``semaforo`` en ese espacio de tablas, con ``semaforo_admin`` como dueño, y le
   quita el acceso a cualquier otro usuario;
4. aplica el esquema como ``semaforo_admin``.

Se puede repetir: lo que ya existe se deja como está y el informe lo dice. No toca otras bases ni
otros usuarios del servicio. No cambia la configuración del servicio (``listen_addresses``): el PO
decidió dejarla como está (2026-11-06).
"""

import os
import re
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psycopg
from psycopg import conninfo, sql

from semaforo.bd.conexion import (
    ADMIN,
    CARGA,
    DATABASE,
    HOST,
    LECTURA,
    PORT,
    ROLES,
    BdError,
    Connection,
    connect,
    password_file,
    service_file,
)
from semaforo.bd.esquema import apply_schema, installed_version
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.herramientas import run_tool

__all__ = [
    "MIN_SERVER_VERSION",
    "NETWORK_SERVICE",
    "TABLESPACE",
    "InstallReport",
    "InstallRequest",
    "Step",
    "install",
    "merge_password_lines",
    "merge_service_text",
    "prepare_database",
]

TABLESPACE = "semaforo"
NETWORK_SERVICE = "*S-1-5-20"  # cuenta «Servicio de red», con la que corre PostgreSQL en Windows
MIN_SERVER_VERSION = 150000  # security_invoker en las vistas
PASSWORD_BYTES = 32
CONNECT_TIMEOUT_S = 10
ICACLS_TIMEOUT_S = 60.0

Step = Literal["created", "existing", "updated"]


class InstallReport(FrozenModel):
    """Qué hizo ``bd iniciar``. No incluye contraseñas."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    server_version: str
    tablespace: Step
    tablespace_location: str
    roles: dict[str, Step]
    password_file: Step
    service_file: Step
    database: Step
    database_schema: Step
    schema_version_installed: str


@dataclass(frozen=True)
class InstallRequest:
    """Datos de ``bd iniciar``."""

    folder: Path
    superuser: str = "postgres"
    service_account: str = NETWORK_SERVICE
    database: str = DATABASE


def _superuser(name: str) -> Connection:
    options = {
        "host": HOST,
        "port": PORT,
        "user": name,
        "dbname": "postgres",
        "connect_timeout": CONNECT_TIMEOUT_S,
        "application_name": "semaforo bd iniciar",
    }
    try:
        return psycopg.connect(conninfo.make_conninfo("", **options), autocommit=True)
    except psycopg.Error as error:
        first = str(error).strip().splitlines()
        raise BdError(
            ErrorCode.DEPENDENCY_MISSING,
            f"no se pudo entrar como {name}: {first[0] if first else type(error).__name__}. "
            "Defina PGPASSWORD con la contraseña del administrador solo para este comando.",
            "superuser",
        ) from error


def _one(connection: Connection, query: sql.SQL | sql.Composed, *params: object) -> object:
    row = connection.execute(query, params or None).fetchone()
    return None if row is None else row[0]


# --- espacio de tablas ---------------------------------------------------------------------


def _icacls(*arguments: str) -> None:
    """Cambia permisos de Windows con ``icacls``. Raises: BdError si no se pudo."""
    result = run_tool(["icacls", *arguments, "/Q"], timeout_s=ICACLS_TIMEOUT_S)
    if result is None or result.returncode != 0:
        raise BdError(
            ErrorCode.OUTPUT_INVALID, "no se pudieron cambiar los permisos (icacls)", arguments[0]
        )


def _grant_folder(folder: Path, account: str) -> None:
    """Permiso de escritura a la cuenta del servicio sobre ``folder`` (y lo que se cree dentro)."""
    if sys.platform != "win32":
        return
    _icacls(str(folder), "/grant", f"{account}:(OI)(CI)F")


def _tablespace(connection: Connection, request: InstallRequest) -> tuple[Step, str]:
    location = _one(
        connection,
        sql.SQL("SELECT pg_tablespace_location(oid) FROM pg_tablespace WHERE spcname = %s"),
        TABLESPACE,
    )
    wanted = request.folder.resolve()
    if location is not None:
        if Path(str(location)).resolve() != wanted:
            raise BdError(
                ErrorCode.INPUT_SCHEMA,
                f"el espacio de tablas {TABLESPACE} ya existe en otra carpeta",
                "folder",
            )
        return "existing", str(location)
    wanted.mkdir(parents=True, exist_ok=True)
    if any(wanted.iterdir()):
        raise BdError(ErrorCode.INPUT_SCHEMA, "la carpeta de los datos debe estar vacía", "folder")
    _grant_folder(wanted, request.service_account)
    connection.execute(
        sql.SQL("CREATE TABLESPACE {} LOCATION {}").format(
            sql.Identifier(TABLESPACE), sql.Literal(wanted.as_posix())
        )
    )
    return "created", wanted.as_posix()


# --- usuarios y archivos de conexión ---------------------------------------------------------

_ROLE_OPTIONS: dict[str, sql.SQL] = {
    ADMIN: sql.SQL("LOGIN CREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
    CARGA: sql.SQL("LOGIN NOCREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
    LECTURA: sql.SQL("LOGIN NOCREATEDB NOSUPERUSER NOCREATEROLE NOREPLICATION NOBYPASSRLS"),
}


def _entry_prefix(role: str) -> str:
    return f"{HOST}:{PORT}:*:{role}:"


def merge_password_lines(lines: list[str], passwords: dict[str, str]) -> list[str]:
    """Las líneas de ``pgpass.conf`` con las de ``passwords`` puestas al día.

    Las líneas de otros usuarios u otras bases (de otros proyectos) quedan tal cual y en su orden.
    """
    kept = [line for line in lines if not any(line.startswith(_entry_prefix(r)) for r in passwords)]
    return kept + [f"{_entry_prefix(role)}{secret}" for role, secret in passwords.items()]


def _known_roles(lines: list[str]) -> set[str]:
    return {role for role in ROLES if any(line.startswith(_entry_prefix(role)) for line in lines)}


SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def merge_service_text(text: str, database: str) -> str:
    """El archivo de servicios con las secciones del proyecto puestas al día.

    Las demás secciones (de otros proyectos) quedan tal cual y en su orden.
    """
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        match = SECTION.match(line)
        if match:
            blocks.append((match[1].strip(), []))
        blocks[-1][1].append(line)
    kept = [lines for name, lines in blocks if name not in ROLES]
    out = [line for lines in kept for line in lines]
    while out and not out[-1].strip():
        out.pop()
    for role in ROLES:
        if out:
            out.append("")
        out += [
            f"[{role}]",
            f"host={HOST}",
            f"port={PORT}",
            f"dbname={database}",
            f"user={role}",
        ]
    return "\n".join(out) + "\n"


def _restrict(path: Path) -> None:
    """Solo el usuario de Windows que ejecuta puede leer ``path`` (contiene contraseñas)."""
    if sys.platform != "win32":
        path.chmod(0o600)
        return
    user = os.environ.get("USERNAME")
    if not user:
        return
    _icacls(str(path), "/inheritance:r", "/grant:r", f"{user}:F")


def _write_private(path: Path, text: str) -> None:
    """Escribe ``path`` de una vez (temporal y renombrado) y lo deja solo para el usuario."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    _restrict(temporary)
    temporary.replace(path)


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _roles(connection: Connection, new_secret: Callable[[], str]) -> tuple[dict[str, Step], Step]:
    lines = _read_lines(password_file())
    known = _known_roles(lines)
    steps: dict[str, Step] = {}
    passwords: dict[str, str] = {}
    for role in ROLES:
        exists = _one(connection, sql.SQL("SELECT 1 FROM pg_roles WHERE rolname = %s"), role)
        if exists is not None and role in known:
            steps[role] = "existing"
            continue
        secret = new_secret()
        # Al servidor solo le llega la contraseña ya cifrada (SCRAM), nunca el texto: así no
        # puede quedar en ningún registro del servicio.
        verifier = connection.pgconn.encrypt_password(
            secret.encode("utf-8"), role.encode("utf-8"), b"scram-sha-256"
        ).decode("ascii")
        connection.execute(
            sql.SQL("{verb} ROLE {role} {options} PASSWORD {verifier}").format(
                verb=sql.SQL("ALTER" if exists is not None else "CREATE"),
                role=sql.Identifier(role),
                options=_ROLE_OPTIONS[role],
                verifier=sql.Literal(verifier),
            )
        )
        passwords[role] = secret
        steps[role] = "updated" if exists is not None else "created"
    if not passwords:
        return steps, "existing"
    _write_private(password_file(), "\n".join(merge_password_lines(lines, passwords)) + "\n")
    return steps, "updated" if lines else "created"


def _service(database: str) -> Step:
    path = service_file()
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    after = merge_service_text(before, database)
    if after == before:
        return "existing"
    _write_private(path, after)
    return "updated" if before else "created"


# --- base y esquema -------------------------------------------------------------------------


def prepare_database(connection: Connection, name: str) -> None:
    """Solo los usuarios del proyecto entran a la base ``name`` (la ejecuta su dueño o el admin).

    El cargador además puede crear tablas temporales (las usa para comparar antes de escribir);
    el usuario de lectura, no.
    """
    database = sql.Identifier(name)
    connection.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(database))
    connection.execute(
        sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(
            database, sql.Identifier(CARGA)
        )
    )
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(database, sql.Identifier(LECTURA))
    )
    panel = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = 'semaforo_panel'").fetchone()
    if panel is not None:
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                database, sql.Identifier("semaforo_panel")
            )
        )


def _database(connection: Connection, name: str) -> Step:
    exists = _one(connection, sql.SQL("SELECT 1 FROM pg_database WHERE datname = %s"), name)
    if exists is not None:
        owner = _one(
            connection,
            sql.SQL("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s"),
            name,
        )
        if owner != ADMIN:
            raise BdError(
                ErrorCode.INPUT_SCHEMA,
                f"ya existe una base {name} que no es del proyecto: no se toca",
                "database",
            )
        prepare_database(connection, name)  # los permisos se vuelven a dejar como deben ser
        return "existing"
    connection.execute(
        sql.SQL(
            "CREATE DATABASE {} OWNER {} TABLESPACE {} ENCODING 'UTF8' TEMPLATE template0"
        ).format(sql.Identifier(name), sql.Identifier(ADMIN), sql.Identifier(TABLESPACE))
    )
    prepare_database(connection, name)
    return "created"


def _new_secret() -> str:
    return secrets.token_urlsafe(PASSWORD_BYTES)


def install(
    request: InstallRequest, *, new_secret: Callable[[], str] = _new_secret
) -> InstallReport:
    """Prepara PostgreSQL para el proyecto (ver el módulo). Se puede repetir.

    Raises:
        BdError: DEPENDENCY_MISSING si no se puede entrar como administrador o como
            ``semaforo_admin``; INPUT_SCHEMA si el servidor es anterior a la versión 15, el
            espacio de tablas ya existe en otra carpeta, la carpeta nueva no está vacía o ya hay
            una base con ese nombre que no es del proyecto.
    """
    with _superuser(request.superuser) as connection:
        number = _one(connection, sql.SQL("SHOW server_version_num"))
        if int(str(number)) < MIN_SERVER_VERSION:
            raise BdError(ErrorCode.INPUT_SCHEMA, "se necesita PostgreSQL 15 o más nuevo", "server")
        server = str(_one(connection, sql.SQL("SHOW server_version")))
        tablespace, location = _tablespace(connection, request)
        roles, passwords = _roles(connection, new_secret)
        connection.execute(
            sql.SQL("GRANT CREATE ON TABLESPACE {} TO {}").format(
                sql.Identifier(TABLESPACE), sql.Identifier(ADMIN)
            )
        )
        services = _service(request.database)
        database = _database(connection, request.database)
    with connect(ADMIN, database=request.database) as owner:
        version = installed_version(owner)
        schema: Step = "existing"
        if version is None:
            version = apply_schema(owner)
            schema = "created"
    return InstallReport(
        server_version=server,
        tablespace=tablespace,
        tablespace_location=location,
        roles=roles,
        password_file=passwords,
        service_file=services,
        database=database,
        database_schema=schema,
        schema_version_installed=version,
    )
