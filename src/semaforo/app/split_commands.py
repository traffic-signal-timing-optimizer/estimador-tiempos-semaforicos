"""Casos de uso de ``splits create`` y ``splits validate`` (DEV12 F3, decisión D11).

``create`` lee el conjunto de escenarios con verificación, lee la política (opcional; sin archivo se
usan las proporciones provisionales de DEC07 pendiente), crea la partición y la publica sin
sobrescribir nunca. ``validate`` lee la partición y su conjunto, ambos verificados, y comprueba
todas las reglas. Si algo no es válido, no se publica nada y se lanza un error con su código de
salida.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal

from semaforo.aprendizaje.split_store import (
    MANIFEST_FILE,
    SplitManifest,
    publish_split,
    read_split,
    validate_split,
)
from semaforo.aprendizaje.splits import PROVISIONAL_POLICY
from semaforo.caso.json_input import read_json
from semaforo.datos.scenario_set import read_scenario_set
from semaforo.datos.scenarios import MAX_SEED
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.split import PARTITIONS, SplitPolicy, parse_policy
from semaforo.trazabilidad.store import utc_now

__all__ = ["MAX_SEED", "SplitResult", "create_split_set", "validate_split_set"]


class SplitResult(FrozenModel):
    """Resumen de una partición publicada o validada.

    ``folder`` y ``manifest`` (relativos al espacio de trabajo) solo van al publicar.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["published", "valid"]
    split_id: str
    case_id: str
    scenario_set_content_id: str
    policy_id: str
    provisional: bool
    seed: int
    groups: dict[str, int]
    scenarios: dict[str, int]
    folder: str | None
    manifest: str | None


def _result(
    manifest: SplitManifest,
    status: Literal["published", "valid"],
    folder: str | None,
    manifest_path: str | None,
) -> SplitResult:
    return SplitResult(
        status=status,
        split_id=manifest.split_id,
        case_id=manifest.case_id,
        scenario_set_content_id=manifest.scenario_set_content_id,
        policy_id=manifest.policy_id,
        provisional=manifest.provisional,
        seed=manifest.seed,
        groups={partition: len(manifest.groups[partition]) for partition in PARTITIONS},
        scenarios={partition: manifest.scenarios[partition] for partition in PARTITIONS},
        folder=folder,
        manifest=manifest_path,
    )


def create_split_set(
    workspace: Path,
    scenarios_folder: Path,
    seed: int,
    policy_path: Path | None = None,
    now: datetime | None = None,
) -> SplitResult:
    """Crea y publica la partición del conjunto de ``scenarios_folder``.

    Raises:
        DomainError: lo que lanzan la lectura verificada del conjunto, la lectura de la política y
            ``publish_split``: INPUT_SCHEMA si el conjunto, la política o la partición no son
            válidos; HASH_MISMATCH o PATH_NOT_ALLOWED si el conjunto está alterado o es un enlace;
            RUN_EXISTS si el conjunto ya tiene su partición.
    """
    scenario_set = read_scenario_set(scenarios_folder)
    policy: SplitPolicy = (
        PROVISIONAL_POLICY
        if policy_path is None
        else parse_policy(read_json(policy_path, "política"))
    )
    moment = utc_now() if now is None else now
    published = publish_split(workspace, scenario_set, policy, seed, clock=lambda: moment)
    return _result(
        published.manifest,
        "published",
        published.folder.relative_to(workspace).as_posix(),
        (published.folder / MANIFEST_FILE).relative_to(workspace).as_posix(),
    )


def validate_split_set(split_folder: Path, scenarios_folder: Path) -> SplitResult:
    """Valida la partición de ``split_folder`` contra el conjunto de ``scenarios_folder``.

    Raises:
        DomainError: INPUT_SCHEMA si alguna regla no se cumple (SplitInvalidError, con todos los
            problemas) o los archivos no son válidos; HASH_MISMATCH o PATH_NOT_ALLOWED si algo está
            alterado o es un enlace.
    """
    stored = read_split(split_folder)
    scenario_set = read_scenario_set(scenarios_folder)
    validate_split(stored, scenario_set)
    return _result(stored.manifest, "valid", None, None)
