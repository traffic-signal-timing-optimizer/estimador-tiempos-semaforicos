"""Lectura verificada de una carpeta publicada con manifiesto (DEV08 F1, decisión D5).

«Las lecturas usan artefactos publicados y hashes comprobados» (diseño técnico). Una carpeta
publicada con ``publish_files`` lleva un manifiesto que lista sus archivos con su huella. Leerla
verificada es comprobar que tiene **exactamente** esos archivos más el manifiesto, sin enlaces, y
que cada uno conserva su huella. Si algo no coincide, la carpeta no se usa.
"""

from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic import BaseModel, ValidationError

from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.fs import read_at_most
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.paths import check_relative_path
from semaforo.trazabilidad.store import TrazabilidadError, scan_files

__all__ = ["MAX_MANIFEST_BYTES", "read_verified", "verify_files"]

MAX_MANIFEST_BYTES = 16 * 1024 * 1024


def _folder_ready(folder: Path) -> None:
    if folder.is_symlink() or folder.is_junction():
        raise TrazabilidadError(
            ErrorCode.PATH_NOT_ALLOWED, "la carpeta es un enlace o una unión", folder.name
        )
    if not folder.is_dir():
        raise TrazabilidadError(ErrorCode.INPUT_SCHEMA, "la carpeta no existe", folder.name)


def verify_files(folder: Path, expected: Mapping[str, str], *, manifest: str) -> None:
    """``folder`` tiene exactamente ``expected`` y ``manifest``, y cada archivo su huella.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si la carpeta es un enlace, tiene enlaces o el
            manifiesto nombra una ruta que sale de la carpeta; INPUT_SCHEMA si no existe;
            HASH_MISMATCH si sobra, falta o cambió un archivo.
    """
    _folder_ready(folder)
    for name in expected:
        try:
            check_relative_path(name)
        except ValueError as error:
            raise TrazabilidadError(ErrorCode.PATH_NOT_ALLOWED, str(error), name) from error
    present = set(scan_files(folder))
    wanted = set(expected) | {manifest}
    if present != wanted:
        odd = sorted(present ^ wanted)[0]
        reason = "sobra" if odd in present else "falta"
        raise TrazabilidadError(
            ErrorCode.HASH_MISMATCH,
            f"la carpeta no tiene exactamente los archivos de su manifiesto ({reason} uno)",
            odd,
        )
    for name, digest in sorted(expected.items()):
        if sha256_file(folder / name) != digest:
            raise TrazabilidadError(ErrorCode.HASH_MISMATCH, "un archivo fue modificado", name)


def read_verified[M: BaseModel](
    folder: Path,
    manifest: str,
    model: type[M],
    files_of: Callable[[M], Mapping[str, str]],
) -> M:
    """Manifiesto ``manifest`` de ``folder`` como ``model``, después de verificar la carpeta.

    ``files_of`` dice qué archivos (y con qué huella) declara el manifiesto.

    Raises:
        TrazabilidadError: INPUT_SCHEMA si la carpeta o el manifiesto no existen, el manifiesto
            es demasiado grande o no cumple su modelo; y lo que lanza ``verify_files``.
    """
    _folder_ready(folder)
    path = folder / manifest
    if path.is_symlink() or not path.is_file():
        raise TrazabilidadError(ErrorCode.INPUT_SCHEMA, "falta el manifiesto", manifest)
    try:
        with path.open("rb") as stream:
            data = read_at_most(stream, MAX_MANIFEST_BYTES + 1)
    except OSError as error:
        raise TrazabilidadError(
            ErrorCode.INPUT_SCHEMA,
            f"el manifiesto no se puede leer ({type(error).__name__})",
            manifest,
        ) from error
    if len(data) > MAX_MANIFEST_BYTES:
        raise TrazabilidadError(
            ErrorCode.INPUT_SCHEMA, "el manifiesto es demasiado grande", manifest
        )
    try:
        parsed = model.model_validate_json(data)
    except ValidationError as error:
        raise TrazabilidadError(
            ErrorCode.INPUT_SCHEMA,
            f"el manifiesto no es válido ({error.error_count()} problemas)",
            manifest,
        ) from error
    verify_files(folder, files_of(parsed), manifest=manifest)
    return parsed
