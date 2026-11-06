"""Hitos del procedimiento como archivos publicados (DEV31 F3).

Un hito (congelar el protocolo, la partición o el modelo, o abrir la prueba) es una decisión del
PO con su acta. ``bd hito`` lo publica como carpeta de solo lectura
``datos/derivados/hitos/<hito_id>/`` (``hito.json`` y ``manifiesto.json``) y lo carga. Así el hito
también sale de un archivo, como todo lo demás, y la base se puede regenerar con sus hitos (B1).

El acta tiene que estar confirmada en git y sin cambios: el commit que la contiene da la fecha
externa del hito cuando se sube a GitHub (hallazgo 8 de F0).
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from semaforo.bd.carga.modelo import (
    DATA_ROOT,
    REPOSITORY_ROOT,
    CargaError,
    Row,
    Unit,
    read_file,
    verified_record,
)
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.paths import check_relative_path
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "MILESTONES",
    "Milestone",
    "MilestoneKind",
    "MilestoneManifest",
    "milestone_row",
    "milestone_unit",
    "publish_milestone",
    "read_milestone",
]

MILESTONES = "derivados/hitos"
MILESTONE_FILE = "hito.json"
MANIFEST_FILE = "manifiesto.json"
MilestoneKind = Literal["protocol_frozen", "split_frozen", "model_frozen", "test_opened"]


class Milestone(FrozenModel):
    """Un hito: qué se congeló o abrió, cuándo, con qué huella, con qué acta y quién."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    hito_id: str
    tipo: MilestoneKind
    registrado_en: datetime
    protocolo_id: str | None
    particion_id: str | None
    modelo_id: str | None
    experimento_id: str | None
    huella_objeto: str
    acta: str
    acta_sha256: str
    commit_codigo: str | None
    responsable: str
    notas: str | None


class MilestoneManifest(FrozenModel):
    """Manifiesto de la carpeta de un hito."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    hito_id: str
    created_at: datetime
    files: dict[str, str]


def _json(model: FrozenModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode("utf-8")


def publish_milestone(workspace: Path, milestone: Milestone) -> str:
    """Publica la carpeta del hito y devuelve su ruta relativa a ``workspace``.

    Raises:
        FileExistsError: si ya existe un hito con ese identificador (no se sobrescribe).
    """
    data = _json(milestone)
    manifest = MilestoneManifest(
        hito_id=milestone.hito_id,
        created_at=milestone.registrado_en,
        files={MILESTONE_FILE: sha256_bytes(data)},
    )
    relative = f"{MILESTONES}/{milestone.hito_id}"
    publish_files(workspace / relative, {MILESTONE_FILE: data, MANIFEST_FILE: _json(manifest)})
    return relative


def read_milestone(workspace: Path, folder: str) -> tuple[Milestone, str]:
    """El hito de ``datos/<folder>`` y la huella de su ``hito.json``, ya verificados."""
    manifest = read_verified(
        workspace / folder, MANIFEST_FILE, MilestoneManifest, lambda m: m.files
    )
    if set(manifest.files) != {MILESTONE_FILE}:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "el manifiesto no lista el hito", folder)
    _, data = read_file(
        workspace,
        DATA_ROOT,
        f"{folder}/{MILESTONE_FILE}",
        "other",
        expected=manifest.files[MILESTONE_FILE],
    )
    try:
        milestone = Milestone.model_validate_json(data)
    except ValidationError as error:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "el hito no es válido", folder) from error
    if milestone.hito_id != manifest.hito_id or folder.rsplit("/", 1)[-1] != milestone.hito_id:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "el hito no coincide con su carpeta", folder)
    return milestone, manifest.files[MILESTONE_FILE]


OBJECTS: dict[MilestoneKind, tuple[str, str]] = {
    "protocol_frozen": ("experimento.protocolos", "protocolo_id"),
    "split_frozen": ("experimento.particiones", "particion_id"),
    "model_frozen": ("aprendizaje.modelos", "modelo_id"),
    "test_opened": ("evaluacion.experimentos", "experimento_id"),
}


def milestone_unit(workspace: Path, repository: Path | None, folder: str) -> Unit:
    """La unidad de un hito publicado, con su acta del repositorio.

    Raises:
        CargaError: si el hito no es válido, falta el repositorio o el acta cambió.
    """
    milestone, digest = read_milestone(workspace, folder)
    if repository is None:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, "para cargar un hito hace falta la carpeta del repositorio"
        )
    try:
        acta = check_relative_path(milestone.acta)
    except ValueError as error:
        raise CargaError(ErrorCode.PATH_NOT_ALLOWED, str(error), "acta") from error
    acta_record, _ = read_file(
        repository, REPOSITORY_ROOT, acta, "minutes", expected=milestone.acta_sha256
    )
    manifest, _ = read_file(workspace, DATA_ROOT, f"{folder}/{MANIFEST_FILE}", "manifest")
    source = verified_record(
        workspace,
        DATA_ROOT,
        f"{folder}/{MILESTONE_FILE}",
        "other",
        digest,
        manifest.artifact_id,
    )
    unit = Unit(key=f"hito:{milestone.hito_id}", kind="milestone")
    for record in (manifest, source, acta_record):
        unit.add_file(record)
    table, column = OBJECTS[milestone.tipo]
    target = getattr(milestone, column)
    if target is None:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, f"el hito {milestone.tipo} no dice su objeto", folder
        )
    unit.need(table, {column: target}, f"falta {table} {target}")
    unit.add("control.hitos", milestone_row(milestone), acta_record)
    return unit


def milestone_row(milestone: Milestone) -> Row:
    """La fila de ``control.hitos`` (su ``artefacto_id`` es el acta)."""
    return {
        "hito_id": milestone.hito_id,
        "tipo": milestone.tipo,
        "registrado_en": milestone.registrado_en,
        "protocolo_id": milestone.protocolo_id,
        "particion_id": milestone.particion_id,
        "modelo_id": milestone.modelo_id,
        "experimento_id": milestone.experimento_id,
        "huella_objeto": milestone.huella_objeto,
        "commit_codigo": milestone.commit_codigo,
        "responsable": milestone.responsable,
        "notas": milestone.notas,
    }
