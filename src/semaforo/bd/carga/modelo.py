"""Unidades de carga: archivos con su huella y las filas que salen de ellos (DEV31 F3)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad.hashing import sha256_bytes

__all__ = [
    "DATA_ROOT",
    "REPOSITORY_ROOT",
    "CargaError",
    "FileRecord",
    "Need",
    "Pending",
    "Row",
    "Unit",
    "artifact_id",
    "read_file",
    "verified_record",
]

DATA_ROOT = "datos"
REPOSITORY_ROOT = "repositorio"
MAX_FILE_BYTES = 512 * 1024 * 1024

Row = dict[str, object]
Root = Literal["datos", "repositorio"]


class CargaError(DomainError):
    """Un archivo no se puede cargar: falta, cambió o no tiene la forma esperada."""


class Pending(Exception):
    """La unidad todavía no se puede cargar porque le falta otra (se dice cuál)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def artifact_id(root: Root, relative: str) -> str:
    """Identificador de un archivo en la base: ``datos:<ruta>`` o ``repositorio:<ruta>``."""
    return f"{root}:{relative}"


@dataclass(frozen=True)
class FileRecord:
    """Un archivo de la unidad, con la huella de los bytes que se leyeron."""

    root: Root
    relative: str
    kind: str
    sha256: str
    size: int
    manifest: str | None = None

    @property
    def artifact_id(self) -> str:
        return artifact_id(self.root, self.relative)


@dataclass(frozen=True)
class Need:
    """Una fila que tiene que existir antes de cargar la unidad (por ejemplo, su escenario)."""

    table: str
    key: dict[str, object]
    reason: str


@dataclass
class Unit:
    """Lo que se carga de una vez: archivos y filas por tabla.

    ``key`` la nombra en el informe (por ejemplo ``corrida:<run_id>``). Cada fila lleva su
    ``artefacto_id``; ``carga_id`` lo pone el cargador.
    """

    key: str
    kind: str
    files: list[FileRecord] = field(default_factory=list[FileRecord])
    rows: dict[str, list[Row]] = field(default_factory=dict[str, list[Row]])
    needs: list[Need] = field(default_factory=list[Need])
    notes: list[str] = field(default_factory=list[str])

    def add_file(self, record: FileRecord) -> FileRecord:
        self.files.append(record)
        return record

    def add(self, table: str, row: Row, source: FileRecord) -> None:
        self.rows.setdefault(table, []).append({**row, "artefacto_id": source.artifact_id})

    def need(self, table: str, key: dict[str, object], reason: str) -> None:
        self.needs.append(Need(table, key, reason))


def read_file(  # noqa: PLR0913  (la huella y el manifiesto son de solo palabra clave)
    base: Path,
    root: Root,
    relative: str,
    kind: str,
    *,
    expected: str | None = None,
    manifest: str | None = None,
) -> tuple[FileRecord, bytes]:
    """Lee ``base/relative`` una sola vez y devuelve su registro y sus bytes.

    La huella se calcula sobre esos mismos bytes, que son los que se usan para las filas: lo que
    entra a la base es exactamente lo que se verificó.

    Raises:
        CargaError: INPUT_SCHEMA si falta, es un enlace o es demasiado grande; HASH_MISMATCH si su
            huella no es la que declara su manifiesto (``expected``).
    """
    path = base / relative
    if path.is_symlink() or not path.is_file():
        raise CargaError(ErrorCode.INPUT_SCHEMA, "falta el archivo o es un enlace", relative)
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise CargaError(ErrorCode.INPUT_SCHEMA, "el archivo es demasiado grande", relative)
        data = path.read_bytes()
    except OSError as error:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, f"no se puede leer ({type(error).__name__})", relative
        ) from error
    digest = sha256_bytes(data)
    if expected is not None and digest != expected:
        raise CargaError(ErrorCode.HASH_MISMATCH, "el archivo cambió desde su manifiesto", relative)
    record = FileRecord(root, relative, kind, digest, len(data), manifest)
    return record, data


def verified_record(  # noqa: PLR0913, PLR0917  (todos describen el mismo archivo)
    base: Path, root: Root, relative: str, kind: str, sha256: str, manifest: str
) -> FileRecord:
    """Registro de un archivo que no se lee aquí porque su lector oficial ya verificó su huella.

    Es para los archivos grandes que la base solo enlaza (la FCD) o que no dan filas: así no se
    leen dos veces. Raises: CargaError INPUT_SCHEMA si el archivo falta.
    """
    path = base / relative
    try:
        size = path.stat().st_size
    except OSError as error:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "falta el archivo", relative) from error
    return FileRecord(root, relative, kind, sha256, size, manifest)
