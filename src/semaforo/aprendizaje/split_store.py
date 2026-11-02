"""Partición publicada e inmutable, con su manifiesto y lectura verificada (DEV12 F3, D8, D10).

``publish_split`` crea la partición de un conjunto de escenarios ya leído y verificado y la publica
de una vez en ``<workspace>/derivados/particiones/<caso>/<huella16>/``, donde ``<huella16>`` es el
comienzo de la huella de contenido del conjunto:

- ``split.json``: la partición, con el contrato ``split`` v1.0 (``frozen`` siempre verdadero);
- ``manifiesto.json``: caso, conjunto de escenarios (su huella de contenido), política y
  proporciones (y si son provisionales), semilla, fecha, grupos y cantidad de escenarios por
  partición, y la huella de ``split.json``.

Como la carpeta se nombra con la huella del conjunto y nunca se sobrescribe, **un conjunto tiene
una sola partición**: la prueba se reserva una vez. Cambiarla exige un conjunto nuevo (un
experimento nuevo, ADR07). Los archivos quedan de solo lectura.

``read_split`` la vuelve a leer comprobando la carpeta, las huellas y la coherencia interna del
manifiesto con la partición; ``validate_split`` la compara además con su conjunto de escenarios.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from semaforo.aprendizaje.splits import create_split
from semaforo.datos.scenario_set import SAFE_FOLDER, ScenarioSet
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import CaseIssue, cap_issues
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.split import (
    PARTITIONS,
    Partition,
    Proportions,
    Split,
    SplitInvalidError,
    SplitPolicy,
    parse_split,
    split_issues,
    split_self_issues,
)
from semaforo.trazabilidad.fs import publish_files, read_at_most
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import TrazabilidadError, utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "MANIFEST_FILE",
    "SPLITS",
    "PublishedSplit",
    "SplitManifest",
    "StoredSplit",
    "publish_split",
    "read_split",
    "validate_split",
]

SPLITS = "derivados/particiones"
SPLIT_FILE = "split.json"
MANIFEST_FILE = "manifiesto.json"
SET_HASH_CHARS = 16
MAX_SPLIT_BYTES = 8 * 1024 * 1024
SHA256_PATTERN = r"^[a-f0-9]{64}$"


class SplitManifest(FrozenModel):
    """Manifiesto de una partición publicada."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    split_id: str
    case_id: str
    case_version: str
    scenario_set_content_id: str = Field(pattern=SHA256_PATTERN)
    policy_id: str
    proportions: Proportions
    provisional: bool
    seed: int = Field(ge=0)
    created_at: datetime
    groups: dict[Partition, list[str]]
    scenarios: dict[Partition, int]
    files: dict[str, str]


@dataclass(frozen=True)
class PublishedSplit:
    """La partición recién publicada: su carpeta, su manifiesto y la partición."""

    folder: Path
    manifest: SplitManifest
    split: Split


@dataclass(frozen=True)
class StoredSplit:
    """Una partición leída y verificada."""

    manifest: SplitManifest
    split: Split


def _groups_of(split: Split) -> dict[Partition, list[str]]:
    groups: dict[Partition, list[str]] = {partition: [] for partition in PARTITIONS}
    for assignment in split.assignments:
        if assignment.group_id not in groups[assignment.partition]:
            groups[assignment.partition].append(assignment.group_id)
    return {partition: sorted(found) for partition, found in groups.items()}


def _counts_of(split: Split) -> dict[Partition, int]:
    counts: dict[Partition, int] = dict.fromkeys(PARTITIONS, 0)
    for assignment in split.assignments:
        counts[assignment.partition] += 1
    return counts


def _json_bytes(model: FrozenModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode("utf-8")


# --- publicar ---------------------------------------------------------------------------------


def publish_split(
    workspace: Path,
    scenario_set: ScenarioSet,
    policy: SplitPolicy,
    seed: int,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> PublishedSplit:
    """Crea y publica la partición de ``scenario_set`` según ``policy`` y ``seed``.

    Raises:
        DomainError: PATH_NOT_ALLOWED si el identificador del caso no sirve como nombre de
            carpeta; RUN_EXISTS si el conjunto ya tiene su partición; SplitInvalidError
            (INPUT_SCHEMA) si no se puede partir (menos de tres familias, una fuente de campo
            compartida…).
    """
    manifest_of_set = scenario_set.manifest
    if SAFE_FOLDER.fullmatch(manifest_of_set.case_id) is None:
        raise DomainError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el identificador del caso solo puede tener letras, números, punto, guion bajo y "
            "guion para usarse como nombre de carpeta",
            "case_id",
        )
    folder_name = manifest_of_set.content_id[:SET_HASH_CHARS]
    split = create_split(scenario_set.scenarios, policy, seed, f"split-{folder_name}")
    data = _json_bytes(split)
    manifest = SplitManifest(
        split_id=split.split_id,
        case_id=manifest_of_set.case_id,
        case_version=manifest_of_set.case_version,
        scenario_set_content_id=manifest_of_set.content_id,
        policy_id=policy.policy_id,
        proportions=policy.proportions,
        provisional=policy.provisional,
        seed=seed,
        created_at=clock(),
        groups=_groups_of(split),
        scenarios=_counts_of(split),
        files={SPLIT_FILE: sha256_bytes(data)},
    )
    folder = workspace / SPLITS / manifest_of_set.case_id / folder_name
    try:
        publish_files(folder, {SPLIT_FILE: data, MANIFEST_FILE: _json_bytes(manifest)})
    except FileExistsError as error:
        raise DomainError(
            ErrorCode.RUN_EXISTS,
            "este conjunto de escenarios ya tiene su partición: la prueba se reserva una sola "
            "vez; para otra partición hace falta un conjunto nuevo",
            "scenarios",
        ) from error
    return PublishedSplit(folder, manifest, split)


# --- leer -------------------------------------------------------------------------------------


def _bad(message: str, field: str | None = None) -> TrazabilidadError:
    return TrazabilidadError(ErrorCode.INPUT_SCHEMA, message, field)


def read_split(folder: Path) -> StoredSplit:
    """La partición de ``folder``, después de verificar la carpeta, las huellas y el manifiesto.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si la carpeta, el
            manifiesto o la partición no existen o no son válidos, o el manifiesto no coincide con
            la partición; HASH_MISMATCH si un archivo sobra, falta o cambió.
        SplitInvalidError: si la partición incumple SPLIT-C02, C04 o C05.
    """
    manifest = read_verified(folder, MANIFEST_FILE, SplitManifest, lambda m: m.files)
    try:
        with (folder / SPLIT_FILE).open("rb") as stream:
            data = read_at_most(stream, MAX_SPLIT_BYTES + 1)
    except OSError as error:
        raise _bad(f"no se puede leer ({type(error).__name__})", SPLIT_FILE) from error
    if len(data) > MAX_SPLIT_BYTES:
        raise _bad("el archivo es demasiado grande", SPLIT_FILE)
    if sha256_bytes(data) != manifest.files.get(SPLIT_FILE):
        raise TrazabilidadError(ErrorCode.HASH_MISMATCH, "un archivo fue modificado", SPLIT_FILE)
    try:
        split = parse_split(json.loads(data.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise _bad(f"no es JSON válido ({type(error).__name__})", SPLIT_FILE) from error
    problems = split_self_issues(split)
    if problems:
        raise SplitInvalidError(cap_issues(problems))
    same = (
        split.split_id == manifest.split_id
        and split.seed == manifest.seed
        and _groups_of(split) == manifest.groups
        and _counts_of(split) == manifest.scenarios
        and set(manifest.files) == {SPLIT_FILE}
    )
    if not same:
        raise _bad("la partición no coincide con su manifiesto", SPLIT_FILE)
    return StoredSplit(manifest, split)


def validate_split(stored: StoredSplit, scenario_set: ScenarioSet) -> None:
    """La partición es la de este conjunto de escenarios y cumple todas las reglas.

    Raises:
        SplitInvalidError: con todos los problemas (SPLIT-C01 a SPLIT-C06 y el vínculo con el
            conjunto).
    """
    manifest, set_manifest = stored.manifest, scenario_set.manifest
    issues: list[CaseIssue] = []
    checks = (
        ("scenario_set_content_id", manifest.scenario_set_content_id, set_manifest.content_id),
        ("case_id", manifest.case_id, set_manifest.case_id),
        ("case_version", manifest.case_version, set_manifest.case_version),
    )
    issues.extend(
        CaseIssue(
            "SPLIT-C01",
            name,
            f"la partición es del valor «{wanted}» y el conjunto tiene «{found}»",
        )
        for name, wanted, found in checks
        if wanted != found
    )
    issues.extend(split_issues(stored.split, scenario_set.scenarios))
    if issues:
        raise SplitInvalidError(cap_issues(issues))
