"""Conexión con PostgreSQL por nombre de servicio (DEV31 F3; decisiones de despliegue de F0).

El código nunca ve una contraseña: pide el servicio por nombre (``semaforo_admin``,
``semaforo_carga`` o ``semaforo_lectura``) y ``libpq`` toma los datos de conexión del archivo de
servicios del usuario de Windows y la contraseña de su ``pgpass.conf``. Los dos archivos viven en
``%APPDATA%\\postgresql`` y nunca entran al repositorio (QA34).
"""

import os
import sys
from pathlib import Path

import psycopg
from psycopg import conninfo
from psycopg.rows import TupleRow

from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "ADMIN",
    "CARGA",
    "DATABASE",
    "HOST",
    "LECTURA",
    "PORT",
    "ROLES",
    "BdError",
    "Connection",
    "connect",
    "password_file",
    "service_file",
]

ADMIN = "semaforo_admin"
CARGA = "semaforo_carga"
LECTURA = "semaforo_lectura"
ROLES = (ADMIN, CARGA, LECTURA)
DATABASE = "semaforo"
HOST = "localhost"
PORT = 5432
CONNECT_TIMEOUT_S = 10
APPLICATION = "semaforo"

type Connection = psycopg.Connection[TupleRow]


class BdError(DomainError):
    """Error de la base de datos o de su configuración."""


def _user_folder() -> Path:
    """Carpeta de configuración de ``libpq`` del usuario: ``%APPDATA%\\postgresql`` en Windows."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise BdError(ErrorCode.DEPENDENCY_MISSING, "falta la variable APPDATA", "APPDATA")
        return Path(appdata) / "postgresql"
    return Path.home()


def service_file() -> Path:
    """Archivo de servicios que lee ``libpq`` (o ``PGSERVICEFILE`` si está definida)."""
    chosen = os.environ.get("PGSERVICEFILE")
    if chosen:
        return Path(chosen)
    return _user_folder() / ".pg_service.conf"


def password_file() -> Path:
    """Archivo de contraseñas que lee ``libpq`` (o ``PGPASSFILE`` si está definida)."""
    chosen = os.environ.get("PGPASSFILE")
    if chosen:
        return Path(chosen)
    name = "pgpass.conf" if sys.platform == "win32" else ".pgpass"
    return _user_folder() / name


def _reason(error: psycopg.Error) -> str:
    """Primera línea del mensaje de ``libpq``: dice qué falló sin datos de la conexión."""
    text = str(error).strip().splitlines()
    return text[0] if text else type(error).__name__


def connect(role: str, *, database: str | None = None, autocommit: bool = False) -> Connection:
    """Conexión como ``role`` a la base del servicio (o a ``database`` si se indica).

    Raises:
        BdError: DEPENDENCY_MISSING si PostgreSQL no responde, falta el servicio o la contraseña,
            o el usuario no puede entrar. El mensaje no incluye contraseñas.
    """
    if role not in ROLES:
        raise ValueError(f"usuario desconocido: {role}")
    options = {
        "service": role,
        "connect_timeout": CONNECT_TIMEOUT_S,
        "application_name": APPLICATION,
    }
    if database is not None:
        options["dbname"] = database
    # PGPASSWORD (si alguien la definió, por ejemplo para «bd iniciar») ganaría al pgpass.conf
    # del proyecto: se aparta mientras se conecta para que cada usuario use su propia contraseña.
    outside = os.environ.pop("PGPASSWORD", None)
    try:
        return psycopg.connect(conninfo.make_conninfo("", **options), autocommit=autocommit)
    except psycopg.Error as error:
        raise BdError(
            ErrorCode.DEPENDENCY_MISSING,
            f"no hay conexión con PostgreSQL como {role}: {_reason(error)}. "
            "¿Está encendido el servicio y se ejecutó «bd iniciar»?",
            "service",
        ) from error
    finally:
        if outside is not None:
            os.environ["PGPASSWORD"] = outside
