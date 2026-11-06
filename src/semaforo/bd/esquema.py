"""Crea el esquema en una base vacía y dice qué versión tiene (DEV31 F3).

El esquema se aplica entero y de una vez (``sql/01_tablas.sql``, ``02_reglas.sql`` y
``03_seguridad.sql``), dentro de una sola transacción: o queda completo o no queda nada. No hay
migraciones sobre una base con datos: si el diseño cambia, se crea una base nueva y se vuelve a
cargar desde los archivos (B1).
"""

import hashlib
from importlib import resources

from semaforo.bd.conexion import BdError, Connection
from semaforo.dominio.errors import ErrorCode

__all__ = ["SQL_FILES", "apply_schema", "installed_version", "schema_sql", "schema_version"]

SQL_FILES = ("01_tablas.sql", "02_reglas.sql", "03_seguridad.sql")
VERSION_CHARS = 16


def schema_sql() -> list[tuple[str, str]]:
    """Cada archivo del esquema, en el orden en que se aplica, con su texto."""
    folder = resources.files("semaforo.bd").joinpath("sql")
    return [(name, folder.joinpath(name).read_text(encoding="utf-8")) for name in SQL_FILES]


def schema_version() -> str:
    """Versión del esquema: la huella de sus tres archivos (cambia si cambia cualquiera)."""
    digest = hashlib.sha256()
    for name, text in schema_sql():
        digest.update(name.encode("utf-8") + b"\0" + text.encode("utf-8") + b"\0")
    return f"sql-{digest.hexdigest()[:VERSION_CHARS]}"


def installed_version(connection: Connection) -> str | None:
    """La versión del esquema de la base conectada; ``None`` si no tiene esquema."""
    row = connection.execute(
        "SELECT to_regprocedure('control.version_esquema()') IS NOT NULL"
    ).fetchone()
    if row is None or not row[0]:
        return None
    version = connection.execute("SELECT control.version_esquema()").fetchone()
    return None if version is None else str(version[0])


def apply_schema(connection: Connection) -> str:
    """Crea el esquema en la base conectada (como su dueño) y devuelve su versión.

    Raises:
        BdError: INPUT_SCHEMA si la base ya tiene tablas del proyecto (no se aplica dos veces).
    """
    with connection.transaction():
        present = connection.execute("SELECT to_regnamespace('control') IS NOT NULL").fetchone()
        if present is not None and present[0]:
            raise BdError(
                ErrorCode.INPUT_SCHEMA,
                "la base ya tiene el esquema; para otro diseño se crea una base nueva",
                "database",
            )
        for _, text in schema_sql():
            connection.execute(text.encode("utf-8"))
        version = schema_version()
        # La versión es una huella hexadecimal calculada aquí, no un texto de afuera.
        connection.execute(
            "CREATE FUNCTION control.version_esquema() RETURNS text LANGUAGE sql IMMUTABLE "
            f"AS $$ SELECT '{version}'::text $$".encode()
        )
    return version
