"""Bloqueo del sistema operativo que dice si una corrida sigue viva (DEV07 F3, D8).

Un archivo de lock creado con ``O_EXCL`` no sirve para saber si quien lo creó murió: si el proceso
cae, el archivo queda y nadie puede distinguir una corrida viva de una caída. Aquí el lock es un
bloqueo del sistema (``msvcrt`` en Windows, ``fcntl`` en los demás) sobre un archivo: el sistema lo
libera solo cuando el proceso termina, de cualquier forma que sea. Si el bloqueo se puede tomar,
quien lo tenía ya no existe.
"""

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import Self

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

__all__ = ["RunLock"]


def _try_lock(descriptor: int) -> bool:
    """Toma el bloqueo exclusivo sin esperar. ``False`` si otro lo tiene."""
    try:
        if sys.platform == "win32":
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(descriptor: int) -> None:
    """Suelta el bloqueo ya: en Windows, cerrar el archivo puede tardar en soltarlo."""
    if sys.platform == "win32":
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


class RunLock:
    """Bloqueo tomado sobre un archivo de lock. Se suelta con ``release`` o al salir del bloque.

    El descriptor no se hereda: un proceso hijo (SUMO) no puede mantener vivo el bloqueo cuando el
    proceso que lo tomó muere.
    """

    def __init__(self, path: Path, descriptor: int) -> None:
        self._path = path
        self._descriptor: int | None = descriptor

    @classmethod
    def acquire(cls, path: Path) -> Self | None:
        """Crea el archivo si falta y toma el bloqueo; ``None`` si otro proceso lo tiene."""
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR)
        except PermissionError:
            return None  # Windows: otro proceso lo está borrando en este instante
        if not _try_lock(descriptor):
            os.close(descriptor)
            return None
        return cls(path, descriptor)

    @classmethod
    def is_held(cls, path: Path) -> bool:
        """¿Hay un proceso vivo con el bloqueo? Si el archivo no existe, no."""
        if not path.exists():
            return False
        lock = cls.acquire(path)
        if lock is None:
            return True
        lock.release()
        return False

    def release(self) -> None:
        """Suelta el bloqueo y borra el archivo. Es seguro llamarlo más de una vez."""
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            _unlock(descriptor)
            if sys.platform != "win32":
                self._path.unlink(missing_ok=True)  # con el bloqueo puesto: nadie lo toma a medias
        finally:
            os.close(descriptor)
        if sys.platform == "win32":
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                pass  # otro proceso lo abrió justo ahora: el archivo suelto no estorba

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
