"""Decisiones sobre archivos excluidos, como archivos publicados (DEV31 F4c, C1.5).

Una corrida que no se puede cargar (por ejemplo, las de DEV00, sin escenario) queda en
``control.conflictos`` como pendiente. El PO puede decidir qué hacer con ella (aceptar el riesgo,
descartarla…). Esa decisión **no vive solo en la base**: ``bd decidir`` la publica como carpeta de
solo lectura ``datos/derivados/decisiones/<decision_id>/`` (``decision.json`` y ``manifiesto.json``)
con su acta confirmada en git. Así sobrevive a una reconstrucción: la base se vuelve a llenar desde
los archivos y la decisión vuelve a aplicarse.

La identidad de una decisión es la **ruta y la huella** del archivo excluido. Si el archivo cambia,
su huella cambia y la decisión anterior ya no lo cubre: queda pendiente y se puede decidir sobre la
versión nueva.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from semaforo.bd.carga.modelo import (
    DATA_ROOT,
    REPOSITORY_ROOT,
    CargaError,
    Unit,
    artifact_id,
    read_file,
    verified_record,
)
from semaforo.bd.conexion import Connection
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.paths import check_relative_path
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "DECISIONS",
    "Decision",
    "DecisionIndex",
    "DecisionKind",
    "DecisionManifest",
    "apply_decision",
    "decision_unit",
    "publish_decision",
    "read_decision",
]

DECISIONS = "derivados/decisiones"
DECISION_FILE = "decision.json"
MANIFEST_FILE = "manifiesto.json"
SHA256 = r"^[0-9a-f]{64}$"
DecisionKind = Literal["kept_existing", "new_version", "discarded", "accepted_risk"]


class Decision(FrozenModel):
    """Qué se decidió sobre un archivo excluido, quién, cuándo y con qué acta."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    decision_id: str = Field(min_length=1)
    decision: DecisionKind
    ruta: str = Field(min_length=1)
    huella: str = Field(pattern=SHA256)
    motivo: str = Field(min_length=1)
    acta: str
    acta_sha256: str = Field(pattern=SHA256)
    commit_codigo: str | None
    responsable: str = Field(min_length=1)
    decidido_en: datetime


class DecisionManifest(FrozenModel):
    """Manifiesto de la carpeta de una decisión."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    decision_id: str
    created_at: datetime
    files: dict[str, str]


@dataclass(frozen=True)
class DecisionIndex:
    """Las decisiones válidas, por archivo excluido (``artefacto_id`` y huella)."""

    by_file: dict[tuple[str, str], Decision]

    def covering(self, relative: str, sha256: str) -> Decision | None:
        """La decisión que cubre el archivo ``datos/<relative>`` con esa huella, o ``None``."""
        return self.by_file.get((artifact_id(DATA_ROOT, relative), sha256))


def _json(model: FrozenModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode("utf-8")


def publish_decision(workspace: Path, decision: Decision) -> str:
    """Publica la carpeta de la decisión y devuelve su ruta relativa a ``workspace``.

    Raises:
        FileExistsError: si ya existe una decisión con ese identificador (no se sobrescribe).
    """
    data = _json(decision)
    manifest = DecisionManifest(
        decision_id=decision.decision_id,
        created_at=decision.decidido_en,
        files={DECISION_FILE: sha256_bytes(data)},
    )
    relative = f"{DECISIONS}/{decision.decision_id}"
    publish_files(workspace / relative, {DECISION_FILE: data, MANIFEST_FILE: _json(manifest)})
    return relative


def read_decision(workspace: Path, folder: str) -> tuple[Decision, str]:
    """La decisión de ``datos/<folder>`` y la huella de su ``decision.json``, ya verificados."""
    manifest = read_verified(workspace / folder, MANIFEST_FILE, DecisionManifest, lambda m: m.files)
    if set(manifest.files) != {DECISION_FILE}:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "el manifiesto no lista la decisión", folder)
    _, data = read_file(
        workspace,
        DATA_ROOT,
        f"{folder}/{DECISION_FILE}",
        "other",
        expected=manifest.files[DECISION_FILE],
    )
    try:
        decision = Decision.model_validate_json(data)
    except ValidationError as error:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "la decisión no es válida", folder) from error
    if decision.decision_id != manifest.decision_id or (
        folder.rsplit("/", 1)[-1] != decision.decision_id
    ):
        raise CargaError(ErrorCode.INPUT_SCHEMA, "la decisión no coincide con su carpeta", folder)
    try:
        check_relative_path(decision.ruta)
    except ValueError as error:
        raise CargaError(ErrorCode.PATH_NOT_ALLOWED, str(error), "ruta") from error
    return decision, manifest.files[DECISION_FILE]


def decision_unit(workspace: Path, repository: Path | None, folder: str) -> tuple[Decision, Unit]:
    """La decisión publicada y su unidad (sus archivos y el acta del repositorio, sin filas).

    Raises:
        CargaError: si la decisión no es válida, falta el repositorio o el acta cambió.
    """
    decision, digest = read_decision(workspace, folder)
    if repository is None:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, "para cargar una decisión hace falta la carpeta del repositorio"
        )
    try:
        acta = check_relative_path(decision.acta)
    except ValueError as error:
        raise CargaError(ErrorCode.PATH_NOT_ALLOWED, str(error), "acta") from error
    acta_record, _ = read_file(
        repository, REPOSITORY_ROOT, acta, "minutes", expected=decision.acta_sha256
    )
    manifest, _ = read_file(workspace, DATA_ROOT, f"{folder}/{MANIFEST_FILE}", "manifest")
    source = verified_record(
        workspace, DATA_ROOT, f"{folder}/{DECISION_FILE}", "other", digest, manifest.artifact_id
    )
    unit = Unit(key=f"decision:{decision.decision_id}", kind="decision")
    for record in (manifest, source, acta_record):
        unit.add_file(record)
    return decision, unit


def apply_decision(connection: Connection, decision: Decision) -> int:
    """Marca como decidido el conflicto pendiente de esa ruta y esa huella; cuántos cambió.

    Solo toca conflictos **sin decisión** de ese archivo con **esa** huella: la base solo deja
    decidir una vez cada conflicto, y una decisión de una versión vieja no cubre la nueva.
    """
    cursor = connection.execute(
        "UPDATE control.conflictos SET decision = %s, decidido_en = %s, decidido_por = %s "
        "WHERE artefacto_id = %s AND huella_nueva = %s AND decision IS NULL",
        (
            decision.decision,
            decision.decidido_en,
            decision.responsable,
            artifact_id(DATA_ROOT, decision.ruta),
            decision.huella,
        ),
    )
    return cursor.rowcount
