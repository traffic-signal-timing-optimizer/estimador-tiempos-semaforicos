"""Operaciones sobre carpetas de copias inmutables (solo lectura) y lectura acotada de archivos."""

import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from semaforo.trazabilidad.paths import check_relative_path

# Tamaño de cada parte al leer con tope (DEV07 F0, D17).
READ_CHUNK_BYTES = 1024 * 1024


class Readable(Protocol):
    """Algo de lo que se leen bytes: un archivo abierto en binario o un ``GzipFile``."""

    def read(self, size: int = -1, /) -> bytes: ...


def read_at_most(stream: Readable, limit: int) -> bytes:
    """Hasta ``limit`` bytes de ``stream``, leídos por partes.

    ``stream.read(limit)`` reserva de una vez memoria para ``limit`` bytes aunque el archivo sea
    chico (medido en DEV07 F0: 512 MB para leer 0,8 MB). Por partes, la memoria es la del archivo.
    Para saber si un archivo supera un tope, se pide ``tope + 1`` y se compara el largo.
    """
    parts: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = stream.read(min(READ_CHUNK_BYTES, remaining))
        if not chunk:
            break
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


def make_read_only(folder: Path) -> None:
    """Marca como solo lectura todos los archivos de ``folder`` (las carpetas no).

    Protege contra modificaciones accidentales, no contra un atacante: quien tenga permisos de
    escritura sobre la carpeta puede quitar el atributo.
    """
    for path in folder.rglob("*"):
        if path.is_file():
            path.chmod(stat.S_IREAD)


def publish_files(final: Path, files: Mapping[str, bytes]) -> None:
    """Escribe ``files`` en una carpeta temporal y la publica como ``final`` de una sola vez.

    Las claves son rutas relativas con ``/``. Los archivos quedan de solo lectura. Si algo falla
    no queda nada a medias.

    Raises:
        FileExistsError: si ``final`` ya existe; nunca se sobrescribe.
        ValueError: si una ruta no es relativa o sale de la carpeta.
    """
    relatives = [check_relative_path(name) for name in files]
    if final.exists():
        raise FileExistsError(final.name)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".tmp-", dir=final.parent))
    try:
        for relative, data in zip(relatives, files.values(), strict=True):
            path = temporary / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        make_read_only(temporary)
        temporary.replace(final)
    except BaseException:
        remove_tree(temporary)
        raise


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
