"""Conjunto de escenarios publicado, con su manifiesto y lectura verificada (DEV11 F4, D9 a D11).

``publish_scenario_set`` genera los escenarios (``semaforo.datos.scenarios``), escribe sus llegadas
(``semaforo.datos.scenario_demand``) y publica todo de una vez en
``<workspace>/derivados/escenarios/<caso>/<fecha>_<huella8>/``:

- ``spec.json``: la especificación, en su forma canónica;
- ``escenarios/<escenario>.json``: cada escenario (contrato ``scenario`` v1.0) con su archivo de
  llegadas enlazado en ``demand_artifact``;
- ``demanda/<escenario>.csv``: sus llegadas;
- ``manifiesto.json``: caso (versión y huella), especificación, semilla, origen, fecha, huella de
  contenido, resumen por familia (rangos, perturbaciones, semillas) y, por escenario, familia,
  perturbación, repetición, ``demand_seed``, flujos usados y vehículos. Lista todos los archivos con
  su huella.

La huella de contenido (``content_id``, ADR09) cubre todos los archivos menos el manifiesto: dos
generaciones iguales la tienen igual aunque sus carpetas lleven fecha distinta. Nunca se
sobrescribe una carpeta publicada.

``read_scenario_set`` la vuelve a leer comprobando que tiene exactamente los archivos del
manifiesto con su huella, que cada escenario cumple su contrato y coincide con su entrada, y que su
archivo de llegadas es el enlazado y tiene los vehículos anotados.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from semaforo.datos.scenario_demand import MAX_DEMAND_BYTES, load_demand, materialize_all
from semaforo.datos.scenarios import generate_scenarios
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case, canonical_sha256
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import Scenario, ScenarioInvalidError, parse_scenario
from semaforo.dominio.scenario_spec import FamilyRow, ScenarioSpec, SpecInvalidError, parse_spec
from semaforo.trazabilidad.fs import publish_files, read_at_most
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.ids import content_id
from semaforo.trazabilidad.store import TrazabilidadError, utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "MANIFEST_FILE",
    "SCENARIO_SETS",
    "FamilyEntry",
    "PublishedSet",
    "ScenarioEntry",
    "ScenarioSet",
    "ScenarioSetManifest",
    "publish_scenario_set",
    "read_scenario_set",
]

SCENARIO_SETS = "derivados/escenarios"
MANIFEST_FILE = "manifiesto.json"
SPEC_FILE = "spec.json"
SCENARIOS_DIR = "escenarios"
SHORT_HASH = 8
MAX_JSON_FILE_BYTES = 1024 * 1024
SAFE_FOLDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA256_PATTERN = r"^[a-f0-9]{64}$"


class ScenarioEntry(FrozenModel):
    """Un escenario del conjunto y de dónde salió (rangos trazables)."""

    scenario_id: str
    family_id: str
    variant: int
    repetition: int
    demand_seed: int
    flows: dict[str, float]
    vehicles: int
    measured: int


class FamilyEntry(FrozenModel):
    """Una familia del conjunto: sus rangos, cuántas perturbaciones y semillas y sus escenarios."""

    family_id: str
    variants: int
    seeds: int
    demand: list[FamilyRow]
    scenario_ids: list[str]


class ScenarioSetManifest(FrozenModel):
    """Manifiesto de un conjunto de escenarios publicado."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    case_id: str
    case_version: str
    case_sha256: str = Field(pattern=SHA256_PATTERN)
    spec_id: str
    spec_sha256: str = Field(pattern=SHA256_PATTERN)
    seed: int
    origin: Literal["synthetic", "field_derived"]
    created_at: datetime
    content_id: str = Field(pattern=SHA256_PATTERN)
    families: list[FamilyEntry]
    scenarios: list[ScenarioEntry]
    files: dict[str, str]


@dataclass(frozen=True)
class PublishedSet:
    """El conjunto recién publicado: su carpeta y su manifiesto."""

    folder: Path
    manifest: ScenarioSetManifest


@dataclass(frozen=True)
class ScenarioSet:
    """Un conjunto leído y verificado."""

    manifest: ScenarioSetManifest
    spec: ScenarioSpec
    scenarios: tuple[Scenario, ...]


def _scenario_path(scenario_id: str) -> str:
    return f"{SCENARIOS_DIR}/{scenario_id}.json"


def _json_bytes(model: FrozenModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode("utf-8")


# --- publicar ---------------------------------------------------------------------------------


def publish_scenario_set(
    workspace: Path,
    case: Case,
    spec: ScenarioSpec,
    seed: int,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> PublishedSet:
    """Genera y publica el conjunto de escenarios de ``spec`` sobre ``case``.

    Raises:
        DomainError: PATH_NOT_ALLOWED si el identificador del caso no sirve como nombre de carpeta;
            RUN_EXISTS si la carpeta del conjunto ya existe; INPUT_SCHEMA (SpecInvalidError,
            ScenarioInvalidError, ScenarioDemandError) si la especificación, la semilla o un
            escenario no son válidos o el conjunto es demasiado grande.
    """
    if SAFE_FOLDER.fullmatch(case.case_id) is None:
        raise DomainError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el identificador del caso solo puede tener letras, números, punto, guion bajo y "
            "guion para usarse como nombre de carpeta",
            "case_id",
        )
    members = generate_scenarios(spec, case, seed)
    items = materialize_all(members, case)
    files: dict[str, bytes] = {SPEC_FILE: _json_bytes(spec)}
    entries: list[ScenarioEntry] = []
    for member, item in zip(members, items, strict=True):
        scenario_id = member.scenario.scenario_id
        files[_scenario_path(scenario_id)] = _json_bytes(item.scenario)
        files[item.path] = item.data
        entries.append(
            ScenarioEntry(
                scenario_id=scenario_id,
                family_id=member.family_id,
                variant=member.variant,
                repetition=member.repetition,
                demand_seed=member.scenario.demand_seed,
                flows=dict(member.flows),
                vehicles=item.vehicles,
                measured=item.measured,
            )
        )
    digests = {path: sha256_bytes(data) for path, data in files.items()}
    created_at = clock()
    manifest = ScenarioSetManifest(
        case_id=case.case_id,
        case_version=case.case_version,
        case_sha256=canonical_sha256(case),
        spec_id=spec.spec_id,
        spec_sha256=digests[SPEC_FILE],
        seed=seed,
        origin=spec.origin,
        created_at=created_at,
        content_id=content_id(digests.items()),
        families=[
            FamilyEntry(
                family_id=family.family_id,
                variants=family.variants,
                seeds=family.seeds,
                demand=list(family.demand),
                scenario_ids=[e.scenario_id for e in entries if e.family_id == family.family_id],
            )
            for family in spec.families
        ],
        scenarios=entries,
        files=digests,
    )
    stamp = f"{created_at.astimezone(UTC):%Y%m%dT%H%M%SZ}_{manifest.content_id[:SHORT_HASH]}"
    folder = workspace / SCENARIO_SETS / case.case_id / stamp
    try:
        publish_files(folder, {**files, MANIFEST_FILE: _json_bytes(manifest)})
    except FileExistsError as error:
        raise DomainError(
            ErrorCode.RUN_EXISTS, "ya existe ese conjunto de escenarios", "seed"
        ) from error
    return PublishedSet(folder, manifest)


# --- leer -------------------------------------------------------------------------------------


def _bad(message: str, field: str | None = None) -> TrazabilidadError:
    return TrazabilidadError(ErrorCode.INPUT_SCHEMA, message, field)


def _read_checked(folder: Path, name: str, expected: str, limit: int) -> bytes:
    """Los bytes de ``name``, leídos una vez y comparados con su huella del manifiesto."""
    try:
        with (folder / name).open("rb") as stream:
            data = read_at_most(stream, limit + 1)
    except OSError as error:
        raise _bad(f"no se puede leer ({type(error).__name__})", name) from error
    if len(data) > limit:
        raise _bad("el archivo es demasiado grande", name)
    if sha256_bytes(data) != expected:
        raise TrazabilidadError(ErrorCode.HASH_MISMATCH, "un archivo fue modificado", name)
    return data


def _json(data: bytes, name: str) -> object:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise _bad(f"no es JSON válido ({type(error).__name__})", name) from error


def read_scenario_set(folder: Path) -> ScenarioSet:
    """El conjunto de ``folder``, después de verificar que es el que publicó el generador.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si la carpeta, el
            manifiesto, la especificación o un escenario no existen o no son válidos, o el
            manifiesto no coincide con sus escenarios; HASH_MISMATCH si un archivo sobra, falta o
            cambió.
        ScenarioDemandError: si un archivo de llegadas no es válido para su escenario.
    """
    manifest = read_verified(folder, MANIFEST_FILE, ScenarioSetManifest, lambda m: m.files)
    if content_id(manifest.files.items()) != manifest.content_id:
        raise TrazabilidadError(
            ErrorCode.HASH_MISMATCH, "la huella de contenido no corresponde a los archivos", None
        )
    _check_files(manifest)
    spec = _read_spec(folder, manifest)
    scenarios = tuple(_read_scenario(folder, manifest, entry) for entry in manifest.scenarios)
    _check_families(manifest, spec)
    return ScenarioSet(manifest, spec, scenarios)


def _read_spec(folder: Path, manifest: ScenarioSetManifest) -> ScenarioSpec:
    data = _read_checked(folder, SPEC_FILE, manifest.files.get(SPEC_FILE, ""), MAX_JSON_FILE_BYTES)
    try:
        spec = parse_spec(_json(data, SPEC_FILE))
    except SpecInvalidError as error:
        raise _bad(error.message, SPEC_FILE) from error
    same = sha256_bytes(data) == manifest.spec_sha256 and (
        spec.spec_id,
        spec.case_id,
        spec.case_version,
        spec.origin,
    ) == (manifest.spec_id, manifest.case_id, manifest.case_version, manifest.origin)
    if not same:
        raise _bad("la especificación no corresponde a su manifiesto", SPEC_FILE)
    return spec


def _read_scenario(folder: Path, manifest: ScenarioSetManifest, entry: ScenarioEntry) -> Scenario:
    path = _scenario_path(entry.scenario_id)
    data = _read_checked(folder, path, manifest.files.get(path, ""), MAX_JSON_FILE_BYTES)
    try:
        scenario = parse_scenario(_json(data, path))
    except ScenarioInvalidError as error:
        raise _bad(error.message, path) from error
    artifact = scenario.demand_artifact
    demand_file = f"demanda/{entry.scenario_id}.csv"
    if artifact is None or artifact.path != demand_file:
        raise _bad("el escenario no enlaza su archivo de llegadas", path)
    demand = _read_checked(
        folder, demand_file, manifest.files.get(demand_file, ""), MAX_DEMAND_BYTES
    )
    vehicles = load_demand(scenario, demand)
    flows = {row.movement_id: row.flow_vph for row in scenario.request.demand}
    same = (
        (scenario.scenario_id, scenario.group_id, scenario.demand_seed)
        == (entry.scenario_id, entry.family_id, entry.demand_seed)
        and (scenario.case_id, scenario.case_version, scenario.origin)
        == (manifest.case_id, manifest.case_version, manifest.origin)
        and flows == entry.flows
        and (len(vehicles), sum(1 for v in vehicles if v.in_cohort))
        == (entry.vehicles, entry.measured)
    )
    if not same:
        raise _bad("el escenario no coincide con su entrada del manifiesto", path)
    return scenario


def _check_files(manifest: ScenarioSetManifest) -> None:
    """El manifiesto lista la especificación y, por cada escenario, su archivo y sus llegadas."""
    expected = {SPEC_FILE}
    for entry in manifest.scenarios:
        expected |= {_scenario_path(entry.scenario_id), f"demanda/{entry.scenario_id}.csv"}
    if len(manifest.scenarios) != len({e.scenario_id for e in manifest.scenarios}):
        raise _bad("hay escenarios repetidos en el manifiesto", "scenarios")
    if set(manifest.files) != expected:
        raise _bad("los archivos del manifiesto no corresponden a sus escenarios", "files")


def _check_families(manifest: ScenarioSetManifest, spec: ScenarioSpec) -> None:
    """Las familias del manifiesto son las de la especificación, con todos sus escenarios."""
    expected: Mapping[str, list[str]] = {
        family.family_id: [
            e.scenario_id for e in manifest.scenarios if e.family_id == family.family_id
        ]
        for family in spec.families
    }
    summary = [
        FamilyEntry(
            family_id=family.family_id,
            variants=family.variants,
            seeds=family.seeds,
            demand=list(family.demand),
            scenario_ids=expected[family.family_id],
        )
        for family in spec.families
    ]
    counted = sum(f.variants * f.seeds for f in spec.families)
    if manifest.families != summary or len(manifest.scenarios) != counted:
        raise _bad("las familias del manifiesto no corresponden a la especificación", "families")
