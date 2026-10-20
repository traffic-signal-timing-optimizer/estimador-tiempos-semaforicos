"""Operaciones sobre carpetas de copias inmutables (solo lectura)."""

import shutil
import stat
from collections.abc import Callable
from pathlib import Path


def make_read_only(folder: Path) -> None:
    """Marca como solo lectura todos los archivos de ``folder`` (las carpetas no).

    Protege contra modificaciones accidentales, no contra un atacante: quien tenga permisos de
    escritura sobre la carpeta puede quitar el atributo.
    """
    for path in folder.rglob("*"):
        if path.is_file():
            path.chmod(stat.S_IREAD)


def remove_tree(path: Path) -> None:
    """Borra una carpeta aunque tenga archivos de solo lectura. Ignora una ruta inexistente."""
    if path.exists():
        shutil.rmtree(path, onexc=_make_writable_and_retry)


def _make_writable_and_retry(
    function: Callable[..., object], target: str, _error: BaseException
) -> None:
    """Quita el solo lectura al archivo que impidió borrar y repite la operación."""
    Path(target).chmod(stat.S_IWRITE)
    function(target)
