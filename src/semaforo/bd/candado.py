"""Candado de sesión que coordina las cargas y las verificaciones (DEV31 F4c, ACU-10).

La carga toma el candado en modo **exclusivo**: solo puede haber una a la vez y ninguna mientras
alguien verifica. La verificación y la conciliación lo toman en modo **compartido**: pueden correr
varias a la vez, y ninguna carga empieza mientras alguna siga leyendo. Así lo que se lee no cambia a
mitad de camino. Es un candado de sesión: se suelta solo al cerrar la conexión.
"""

from semaforo.bd.conexion import Connection

__all__ = ["LOCK_KEY", "try_exclusive", "try_shared"]

LOCK_KEY = 31_031_031


def try_exclusive(connection: Connection) -> bool:
    """Toma el candado exclusivo (una carga). ``False`` si hay otra carga o una verificación."""
    row = connection.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()
    return row is not None and bool(row[0])


def try_shared(connection: Connection) -> bool:
    """Toma el candado compartido (una verificación). ``False`` si hay una carga en curso."""
    row = connection.execute("SELECT pg_try_advisory_lock_shared(%s)", (LOCK_KEY,)).fetchone()
    return row is not None and bool(row[0])
