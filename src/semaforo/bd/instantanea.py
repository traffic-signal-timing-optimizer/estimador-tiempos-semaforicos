"""Lectura estable de la base: una sola instantánea, de solo lectura y con candado compartido.

Una verificación o una conciliación hace muchas consultas. Para que todas vean la misma base:

1. toma el candado compartido (``candado``): si hay una carga en curso, no sigue (*no concluyente*);
2. abre **una** transacción de solo lectura con aislamiento ``REPEATABLE READ``: todas las
   consultas ven el mismo estado, aunque algo se escriba mientras tanto;
3. anota cuál es la última carga al empezar y la vuelve a mirar al terminar: si cambió, el resultado
   no es concluyente.

Nunca escribe nada ni crea bases.
"""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg

from semaforo.bd.candado import try_shared
from semaforo.bd.conexion import BdError, Connection, connect
from semaforo.dominio.errors import ErrorCode

__all__ = ["Inconcluso", "Lectura", "lectura_estable"]


class Inconcluso(Exception):
    """La lectura no puede dar un resultado firme; ``reason`` dice por qué."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class _Estado:
    """Lo que dicen las cargas en un momento: la última y cuántas figuran «en curso»."""

    ultima: str | None
    en_curso: int


class Lectura:
    """Una lectura estable: la conexión (ya dentro de la instantánea) y su resultado final."""

    def __init__(self, connection: Connection, inicio: _Estado) -> None:
        self.connection = connection
        self.inicio = inicio
        self.cambio: str | None = None

    @property
    def carga_id(self) -> str | None:
        """La última carga que vio la instantánea."""
        return self.inicio.ultima


def _estado(connection: Connection) -> _Estado:
    row = connection.execute(
        "SELECT (SELECT carga_id FROM control.cargas ORDER BY inicio DESC, carga_id DESC LIMIT 1), "
        "(SELECT count(*) FROM control.cargas WHERE estado = 'running')"
    ).fetchone()
    if row is None:
        return _Estado(None, 0)
    return _Estado(None if row[0] is None else str(row[0]), int(row[1]))


@contextmanager
def lectura_estable(role: str, *, database: str | None = None) -> Generator[Lectura]:
    """Abre la lectura estable como ``role`` (ver el módulo).

    Al salir, ``Lectura.cambio`` dice si la última carga cambió durante la lectura (``None`` si
    no cambió).

    Raises:
        Inconcluso: si hay una carga en curso, o alguna carga figura «en curso» (``running``).
        BdError: si no hay conexión con la base.
    """
    connection = connect(role, database=database, autocommit=True)
    try:
        if not try_shared(connection):
            raise Inconcluso("hay una carga en curso: no se puede leer una base que está cambiando")
        connection.autocommit = False
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        inicio = _estado(connection)
        if inicio.en_curso:
            connection.rollback()
            raise Inconcluso(
                f"{inicio.en_curso} cargas figuran «en curso» (running) sin proceso: "
                "se interrumpieron"
            )
        lectura = Lectura(connection, inicio)
        try:
            yield lectura
        finally:
            connection.rollback()
            connection.autocommit = True
            final = _estado(connection)
            if final != inicio:
                lectura.cambio = "la última carga cambió mientras se leía la base"
    except psycopg.Error as error:
        first = str(error).strip().splitlines()
        raise BdError(
            ErrorCode.DEPENDENCY_MISSING,
            f"falló la lectura de la base: {first[0] if first else type(error).__name__}",
            "lectura",
        ) from error
    finally:
        connection.close()
