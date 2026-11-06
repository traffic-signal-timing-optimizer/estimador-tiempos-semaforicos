"""Bases temporales: para las pruebas y para regenerar la base y comparar su huella (DEV31 F3).

Se llaman siempre ``semaforo_pruebas_<…>`` y solo se borran bases con ese prefijo: nunca la base
``semaforo`` ni las de otros proyectos del mismo servicio. Las crea ``semaforo_admin`` (que tiene
permiso para crear bases) en el espacio de tablas del proyecto, con el esquema ya aplicado.
"""

import os
import secrets
import time
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg import sql

from semaforo.bd.conexion import ADMIN, BdError, connect
from semaforo.bd.esquema import apply_schema
from semaforo.bd.instalacion import TABLESPACE, prepare_database
from semaforo.dominio.errors import ErrorCode

__all__ = ["PREFIX", "create_database", "drop_database", "scratch_database"]

PREFIX = "semaforo_pruebas_"
DROP_PAUSE_S = 0.2
WAIT_S = 15.0


def _checked(name: str) -> sql.Identifier:
    if not name.startswith(PREFIX) or not name.replace("_", "").isalnum():
        raise BdError(ErrorCode.PATH_NOT_ALLOWED, "solo se manejan bases temporales", name)
    return sql.Identifier(name)


def create_database(*, template: str | None = None, schema: bool = True) -> str:
    """Crea una base temporal vacía (o copia de ``template``) y devuelve su nombre."""
    name = f"{PREFIX}{os.getpid()}_{secrets.token_hex(4)}"
    source = sql.SQL("template0") if template is None else _checked(template)
    query = sql.SQL("CREATE DATABASE {} OWNER {} TABLESPACE {} ENCODING 'UTF8' TEMPLATE {}").format(
        _checked(name), sql.Identifier(ADMIN), sql.Identifier(TABLESPACE), source
    )
    deadline = time.monotonic() + WAIT_S
    with connect(ADMIN, autocommit=True) as admin:
        while True:
            try:
                admin.execute(query)
                break
            except psycopg.errors.ObjectInUse:
                # El molde todavía tiene una conexión que se está cerrando.
                if time.monotonic() > deadline:
                    raise
                time.sleep(DROP_PAUSE_S)
        prepare_database(admin, name)
    if schema and template is None:
        try:
            with connect(ADMIN, database=name) as owner:
                apply_schema(owner)
        except BaseException:
            drop_database(name)
            raise
    return name


def drop_database(name: str, *, wait_s: float = WAIT_S) -> None:
    """Borra la base temporal ``name``.

    Si todavía hay una conexión cerrándose (el servidor tarda un instante en soltarla), espera.
    ``semaforo_admin`` no puede cortar conexiones de otros usuarios, y no se le da ese permiso:
    le alcanzaría para cortar las de otros proyectos del mismo servicio.
    """
    query = sql.SQL("DROP DATABASE IF EXISTS {}").format(_checked(name))
    deadline = time.monotonic() + wait_s
    with connect(ADMIN, autocommit=True) as admin:
        while True:
            try:
                admin.execute(query)
                return
            except psycopg.errors.ObjectInUse:
                if time.monotonic() > deadline:
                    raise
                time.sleep(DROP_PAUSE_S)


@contextmanager
def scratch_database(*, template: str | None = None) -> Generator[str]:
    """Una base temporal con el esquema, que se borra al salir."""
    name = create_database(template=template)
    try:
        yield name
    finally:
        drop_database(name)
