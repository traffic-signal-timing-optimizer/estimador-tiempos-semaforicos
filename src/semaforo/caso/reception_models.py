"""Manifiesto de la copia de entrada de una recepción (ADR09).

Los modelos siguen las convenciones de los contratos de referencia: sin campos desconocidos,
sin conversión de tipos y sin NaN. Además son inmutables. Todas las rutas son relativas a la
carpeta de origen y usan ``/``, para que el manifiesto no revele rutas de ningún equipo.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from semaforo.caso.sumo_config import is_absolute_like
from semaforo.trazabilidad.ids import content_id

Role = Literal["entry_config", "input", "view", "output", "script", "unreferenced"]
IDENTITY_ROLES: frozenset[str] = frozenset({"entry_config", "input"})
SHA256_PATTERN = r"^[a-f0-9]{64}$"
_LINE_BREAKING_CHARACTERS = "\t\n\r"


def _check_relative_path(value: str) -> str:
    if not value or is_absolute_like(value) or "\\" in value:
        raise ValueError(f"la ruta debe ser relativa y usar '/': {value!r}")
    if any(character in value for character in _LINE_BREAKING_CHARACTERS):
        raise ValueError(f"la ruta no puede contener tabuladores ni saltos de línea: {value!r}")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError(f"la ruta no puede salir de la carpeta ni tener tramos vacíos: {value!r}")
    return value


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class FileRecord(_Base):
    """Un archivo observado en la carpeta de origen.

    ``in_snapshot`` indica si se copió a la copia inmutable (solo los archivos de identidad).
    Un archivo que no se pudo leer conserva su motivo en ``unreadable_reason``.
    """

    path: str
    role: Role
    size_bytes: int = Field(ge=0)
    sha256: str | None = Field(pattern=SHA256_PATTERN)
    in_snapshot: bool
    unreadable_reason: str | None = None

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        return _check_relative_path(value)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.sha256 is None:
            if self.unreadable_reason is None:
                raise ValueError("un archivo ilegible necesita unreadable_reason")
            if self.in_snapshot:
                raise ValueError("un archivo ilegible no puede estar en in_snapshot")
        elif self.unreadable_reason is not None:
            raise ValueError("un archivo con hash no puede tener unreadable_reason")
        if self.in_snapshot and self.role not in IDENTITY_ROLES:
            raise ValueError("solo entry_config e input pueden estar en in_snapshot")
        return self


class MissingDependency(_Base):
    """Un archivo que el .sumocfg declara y que no se pudo encontrar dentro del origen.

    ``path`` es el valor tal como está escrito en el .sumocfg: puede ser absoluto o salir de la
    carpeta, por eso no se valida como ruta relativa.
    """

    path: str
    section: Literal["input", "gui_only"]
    option: str
    reason: Literal["not_found", "not_a_file", "outside_source", "absolute_path"]


class Finding(_Base):
    """Un hallazgo de la recepción. ``path`` reproduce el valor del .sumocfg."""

    code: Literal["ABSOLUTE_PATH"]
    section: str
    option: str
    path: str
    message: str


class SnapshotManifest(_Base):
    """Qué contiene una copia de entrada y qué se observó en la carpeta de origen.

    El manifiesto no lleva fechas ni rutas de equipo: el mismo contenido produce siempre el
    mismo manifiesto. ``snapshot_id`` se recalcula con los hashes de ``identity_files`` y debe
    coincidir (ADR09).
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    snapshot_id: str = Field(pattern=SHA256_PATTERN)
    entry_config: str
    identity_files: list[str]
    files: list[FileRecord]
    missing_dependencies: list[MissingDependency]
    findings: list[Finding]

    @field_validator("entry_config")
    @classmethod
    def _relative_entry_config(cls, value: str) -> str:
        return _check_relative_path(value)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        paths = [record.path for record in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("hay rutas duplicadas en files")
        if paths != sorted(paths):
            raise ValueError("files debe estar ordenada por ruta")
        by_path = {record.path: record for record in self.files}
        for path in self.identity_files:
            record = by_path.get(path)
            if record is None or not record.in_snapshot:
                raise ValueError(f"identity_files contiene {path!r}, que no está en la copia")
        if sorted(set(self.identity_files)) != self.identity_files:
            raise ValueError("identity_files debe estar ordenada y sin repetidos")
        if {record.path for record in self.files if record.in_snapshot} != set(self.identity_files):
            raise ValueError("identity_files debe coincidir con los archivos in_snapshot")
        entry = by_path.get(self.entry_config)
        if entry is None or entry.role != "entry_config":
            raise ValueError("entry_config debe ser el archivo con rol entry_config")
        expected = content_id((path, by_path[path].sha256 or "") for path in self.identity_files)
        if self.snapshot_id != expected:
            raise ValueError("snapshot_id no coincide con los hashes de identity_files")
        return self
