"""Operaciones sobre carpetas de copias inmutables (solo lectura) y lectura acotada de archivos.

Publicar una carpeta (DEV08 F1, decisiones D2 a D4): se toma el bloqueo del sistema
``<carpeta>/.lock-<destino>``, se escribe en ``<carpeta>/.tmp-<destino>-<aleatorio>`` y se publica
con un renombrado. Nunca se sobrescribe un destino, aunque dos publicaciones lleguen a la vez. Si
el programa muere a medias, la carpeta temporal queda; la siguiente publicación en esa carpeta la
aparta a ``<carpeta>/.incompletas/`` con ``INCOMPLETA.json``, sin borrarla.
"""

import shutil
import stat
import tempfile
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from semaforo.dominio.base_model import FrozenModel
from semaforo.trazabilidad.lock import RunLock
from semaforo.trazabilidad.paths import check_relative_path

TEMP_PREFIX = ".tmp-"
LOCK_PREFIX = ".lock-"
INCOMPLETE_DIR = ".incompletas"
INCOMPLETE_MARK = "INCOMPLETA.json"
# Una carpeta temporal sin destino en el nombre puede estar naciendo; antes de esto no se toca.
FRESH_S = 60.0
_RUN_MANIFEST = "manifest.json"  # las temporales de corridas las aparta recover_interrupted
_MAX_NAME_TRIES = 1000
PUBLICATION_CAUSE = "el programa que publicaba la carpeta terminó sin publicarla"

# Tamaño de cada parte al leer con tope (DEV07 F0, D17).
READ_CHUNK_BYTES = 1024 * 1024

# Renombrar una carpeta recién escrita puede fallar un instante en Windows con «acceso denegado»
# mientras otro programa (el antivirus) revisa sus archivos (DEV14 F2: 1 de 116 renombrados con
# corridas en paralelo, liberado en menos de 50 ms). Se reintenta durante unos 2 s.
RENAME_ATTEMPTS = 40
RENAME_PAUSE_S = 0.05


def replace_patiently(
    source: Path, target: Path, *, pause: Callable[[float], object] = time.sleep
) -> None:
    """Renombra ``source`` a ``target`` y reintenta si el sistema lo niega un instante.

    Solo reintenta ``PermissionError`` mientras ``target`` no exista; cualquier otro error, o el
    mismo después de ``RENAME_ATTEMPTS`` intentos, se lanza tal cual.
    """
    for attempt in range(1, RENAME_ATTEMPTS + 1):
        try:
            source.replace(target)
        except PermissionError:
            if attempt == RENAME_ATTEMPTS or target.exists():
                raise
            pause(RENAME_PAUSE_S)
        else:
            return


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


class IncompletePublication(FrozenModel):
    """Una publicación que quedó a medias y se apartó. Rutas relativas a su carpeta."""

    folder: str
    source_folder: str
    target: str | None
    detected_at: datetime
    cause: str


def free_name(parent: Path, base: str) -> str:
    """``base`` si está libre en ``parent``; si no, ``base-2``, ``base-3``…"""
    for number in range(1, _MAX_NAME_TRIES + 1):
        name = base if number == 1 else f"{base}-{number}"
        if not (parent / name).exists():
            return name
    raise OSError(f"no hay un nombre libre en {INCOMPLETE_DIR} para {base}")


def is_plain_folder(path: Path) -> bool:
    """Una carpeta de verdad: ni enlace ni unión."""
    return path.is_dir() and not path.is_symlink() and not path.is_junction()


def _target_of(name: str) -> str | None:
    """Destino de una carpeta ``.tmp-<destino>-<aleatorio>``; ``None`` si el nombre es antiguo."""
    rest = name.removeprefix(TEMP_PREFIX)
    target, separator, _ = rest.rpartition("-")
    return target if separator and target else None


def _age_s(folder: Path) -> float:
    try:
        return time.time() - folder.stat().st_mtime
    except OSError:
        return 0.0


def _set_aside(
    parent: Path, folder: Path, target: str | None, now: datetime
) -> IncompletePublication:
    destination_root = parent / INCOMPLETE_DIR
    destination_root.mkdir(exist_ok=True)
    name = free_name(destination_root, folder.name.removeprefix(TEMP_PREFIX))
    record = IncompletePublication(
        folder=f"{INCOMPLETE_DIR}/{name}",
        source_folder=folder.name,
        target=target,
        detected_at=now,
        cause=PUBLICATION_CAUSE,
    )
    (folder / INCOMPLETE_MARK).write_text(record.model_dump_json(indent=2), encoding="utf-8")
    folder.replace(destination_root / name)
    return record


def _now() -> datetime:
    return datetime.now(UTC)


def recover_publications(
    parent: Path, *, clock: Callable[[], datetime] = _now
) -> list[IncompletePublication]:
    """Aparta las publicaciones caídas de ``parent`` a ``parent/.incompletas`` y las devuelve.

    Una publicación viva (su candado está tomado) no se toca. Las temporales de corridas (con
    ``manifest.json``) se dejan para ``recover_interrupted``. Lo que no se puede mover se deja y se
    vuelve a intentar la próxima vez. Si ``parent`` no existe, no hace nada.
    """
    if not is_plain_folder(parent):
        return []
    now = clock()
    moved: list[IncompletePublication] = []
    for folder in sorted(parent.iterdir()):
        if not (folder.name.startswith(TEMP_PREFIX) and is_plain_folder(folder)):
            continue
        target = _target_of(folder.name)
        try:
            if target is None:
                if (folder / _RUN_MANIFEST).exists() or _age_s(folder) < FRESH_S:
                    continue
                moved.append(_set_aside(parent, folder, None, now))
                continue
            lock = RunLock.acquire(parent / f"{LOCK_PREFIX}{target}")
            if lock is None:
                continue  # sigue viva
            with lock:
                moved.append(_set_aside(parent, folder, target, now))
        except OSError:
            continue
    return moved


@contextmanager
def publication(final: Path) -> Generator[Path]:
    """Carpeta temporal donde escribir lo que se publicará como ``final``, con su candado tomado.

    Antes aparta las publicaciones caídas de la misma carpeta. Si el bloque termina bien, los
    archivos quedan de solo lectura y la temporal se publica como ``final`` con un renombrado; si
    falla, la temporal se borra (su contenido se puede volver a generar).

    Raises:
        FileExistsError: si ``final`` ya existe o si otra publicación del mismo destino está en
            curso. Nunca se sobrescribe.
    """
    parent = final.parent
    parent.mkdir(parents=True, exist_ok=True)
    recover_publications(parent)
    lock = RunLock.acquire(parent / f"{LOCK_PREFIX}{final.name}")
    if lock is None:
        raise FileExistsError(final.name)
    with lock:
        if final.exists():
            raise FileExistsError(final.name)
        temporary = Path(tempfile.mkdtemp(prefix=f"{TEMP_PREFIX}{final.name}-", dir=parent))
        try:
            yield temporary
            make_read_only(temporary)
            try:
                replace_patiently(temporary, final)
            except OSError as error:
                if final.exists():  # apareció mientras se escribía: no se sobrescribe
                    raise FileExistsError(final.name) from error
                raise
        except BaseException:
            remove_tree(temporary)
            raise


def publish_files(final: Path, files: Mapping[str, bytes]) -> None:
    """Escribe ``files`` en una carpeta temporal y la publica como ``final`` de una sola vez.

    Las claves son rutas relativas con ``/``. Los archivos quedan de solo lectura. Si algo falla
    no queda nada a medias.

    Raises:
        FileExistsError: si ``final`` ya existe o se está publicando; nunca se sobrescribe.
        ValueError: si una ruta no es relativa o sale de la carpeta.
    """
    relatives = [check_relative_path(name) for name in files]
    if final.exists():
        raise FileExistsError(final.name)
    with publication(final) as temporary:
        for relative, data in zip(relatives, files.values(), strict=True):
            path = temporary / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


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
