"""Comparadores publicados: plan vigente y Webster de un escenario (DEV15 F4, HU08 y HU12).

``compute_comparators`` junta, para un escenario, el plan vigente (dato observado) y el plan de
Webster con su aplicabilidad. ``publish_comparators`` los escribe de una vez, sin sobrescribir, en
``<datos>/derivados/comparadores/<caso>/<AAAAMMDDTHHMMSSZ>_<huella8>/``:

- ``comparadores.json``: los dos planes, la aplicabilidad de Webster y sus motivos;
- ``parametros.json``: los parámetros de Webster con los que se calculó (siguen provisionales
  mientras no los apruebe un especialista, DEC08);
- ``manifiesto.json``: identidad, huellas de los dos archivos y la red del caso.

``read_comparators`` los vuelve a leer comprobando la carpeta, las huellas y que el manifiesto
coincida con el contenido. Un Webster que no aplica queda registrado con su motivo y no se
reemplaza por ningún valor (HU12: «fallos no reemplazados»).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import ValidationError, model_validator

from semaforo.datos.scenario_set import SAFE_FOLDER
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import PreparedCase
from semaforo.dominio.scenario import Scenario, evidence_origin
from semaforo.referencias.baselines import (
    CriticalPath,
    ObservedPlan,
    WebsterParameters,
    WebsterPlan,
    crossing_structure,
    read_current_plan,
    webster_plan,
)
from semaforo.referencias.errors import ReferenciasError
from semaforo.trazabilidad.fs import publish_files, read_at_most
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import TrazabilidadError, utc_now
from semaforo.trazabilidad.verify import read_verified

__all__ = [
    "COMPARATORS",
    "ComparatorsFile",
    "ComparatorsManifest",
    "ComparatorsResult",
    "StoredComparators",
    "compute_comparators",
    "publish_comparators",
    "read_comparators",
]

COMPARATORS = "derivados/comparadores"
COMPARATORS_FILE = "comparadores.json"
PARAMETERS_FILE = "parametros.json"
MANIFEST_FILE = "manifiesto.json"
SHORT_HASH_CHARS = 8
MAX_FILE_BYTES = 4 * 1024 * 1024
Status = Literal["applicable", "not_applicable"]


# --- contenido de comparadores.json ------------------------------------------------------------


class ProblemRow(FrozenModel):
    """Por qué Webster no aplica."""

    code: str
    subject: str
    message: str


class PathRow(FrozenModel):
    """El recorrido crítico de Webster."""

    y: float
    lost_time_s: float
    cycle_s: float
    lane_ids: list[str]
    lost_slot_ids: list[str]


class PlanRow(FrozenModel):
    """Un plan: la duración de cada tramo y su ciclo."""

    durations_s: dict[str, float]
    cycle_s: float


class CurrentSection(FrozenModel):
    """El plan vigente con su fuente, y las reglas del caso que incumple (ninguna si cumple)."""

    plan: PlanRow
    source: str
    hourly_variation: str
    confirmed_by: str
    program_folder: str
    violated: list[str]


class WebsterSection(FrozenModel):
    """Webster: su aplicabilidad, su plan (el propuesto, aunque incumpla) y los motivos.

    ``webster_cycle_s`` es el ciclo que da la fórmula; ``plan.cycle_s``, el del plan ya redondeado.
    """

    status: Status
    adaptation: str
    parameter_set: str
    provisional: bool
    webster_cycle_s: float | None
    plan: PlanRow | None
    violated: list[str]
    problems: list[ProblemRow]
    critical_path: PathRow | None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status == "applicable" and (
            self.plan is None or self.problems or self.violated or self.webster_cycle_s is None
        ):
            raise ValueError("un Webster aplicable tiene plan y ciclo, y ningún problema")
        if self.status == "not_applicable" and not self.problems:
            raise ValueError("un Webster que no aplica dice por qué")
        return self


Origin = Literal["synthetic", "field"]


class ComparatorsFile(FrozenModel):
    """Contenido de ``comparadores.json``.

    ``case_origin`` es el del caso, ``demand_origin`` el de la demanda del escenario con que se
    calculó Webster y ``evidence_origin`` el que debe mostrar cualquier tabla (auditoría A03).
    """

    schema_version: Literal["2.0.0"] = "2.0.0"
    case_id: str
    case_version: str
    scenario_id: str
    case_origin: Origin
    demand_origin: Origin
    evidence_origin: Origin
    current_plan: CurrentSection
    webster: WebsterSection

    @model_validator(mode="after")
    def _origins_agree(self) -> Self:
        if self.evidence_origin != evidence_origin(self.case_origin, self.demand_origin):
            raise ValueError(
                "el origen de la evidencia no sale del origen del caso y de la demanda"
            )
        return self


class ComparatorsManifest(FrozenModel):
    """Manifiesto de los comparadores publicados."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    created_at: datetime
    case_id: str
    case_version: str
    scenario_id: str
    case_origin: Origin
    demand_origin: Origin
    evidence_origin: Origin
    parameter_set: str
    provisional: bool
    adaptation: str
    webster_status: Status
    current_plan_feasible: bool
    network_sha256: str | None
    files: dict[str, str]


# --- cálculo -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ComparatorsResult:
    """Los comparadores de un escenario, tal como se publican."""

    case: Case
    scenario_id: str
    current: ObservedPlan
    webster: WebsterPlan
    parameters: WebsterParameters
    demand_origin: Origin

    @property
    def search_current_plan(self) -> Mapping[str, float]:
        """El plan vigente para la búsqueda de DEV14 (que lo excluye si incumple las reglas)."""
        return self.current.durations_s

    @property
    def search_webster_plan(self) -> Mapping[str, float] | None:
        """El plan de Webster para la búsqueda, solo si aplica. Si no, no entra como candidato."""
        if self.webster.status != "applicable":
            return None
        return self.webster.durations_s


def compute_comparators(
    prepared: PreparedCase,
    scenario: Scenario,
    parameters: WebsterParameters,
    program_folder: Path,
) -> ComparatorsResult:
    """El plan vigente y el de Webster de ``scenario``.

    Raises:
        ReferenciasError: INPUT_SCHEMA si el escenario o los parámetros son de otro caso, o lo que
            lanza la lectura del plan vigente.
        TrazabilidadError: si la carpeta del programa vigente no está completa o cambió.
    """
    case = prepared.case
    if (scenario.case_id, scenario.case_version) != (case.case_id, case.case_version):
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA, "el escenario es de otro caso o de otra versión", "scenario"
        )
    current = read_current_plan(program_folder, prepared, parameters)
    webster = webster_plan(crossing_structure(case), prepared, scenario.request, parameters)
    return ComparatorsResult(
        case, scenario.scenario_id, current, webster, parameters, scenario.request.origin
    )


def _plan_row(durations: Mapping[str, float], cycle_s: float) -> PlanRow:
    return PlanRow(durations_s=dict(durations), cycle_s=cycle_s)


def _path_row(path: CriticalPath | None) -> PathRow | None:
    if path is None:
        return None
    return PathRow(
        y=path.y,
        lost_time_s=path.lost_time_s,
        cycle_s=path.cycle_s,
        lane_ids=list(path.lane_ids),
        lost_slot_ids=list(path.lost_slot_ids),
    )


def _file_of(result: ComparatorsResult) -> ComparatorsFile:
    current, webster = result.current, result.webster
    return ComparatorsFile(
        case_id=result.case.case_id,
        case_version=result.case.case_version,
        scenario_id=result.scenario_id,
        case_origin=result.case.origin,
        demand_origin=result.demand_origin,
        evidence_origin=evidence_origin(result.case.origin, result.demand_origin),
        current_plan=CurrentSection(
            plan=_plan_row(current.durations_s, current.cycle_s),
            source=current.source,
            hourly_variation=current.hourly_variation,
            confirmed_by=current.confirmed_by,
            program_folder=current.program_folder,
            violated=list(current.violated),
        ),
        webster=WebsterSection(
            status=webster.status,
            adaptation=webster.adaptation,
            parameter_set=webster.parameter_set,
            provisional=webster.provisional,
            webster_cycle_s=webster.webster_cycle_s,
            plan=None
            if webster.durations_s is None or webster.cycle_s is None
            else _plan_row(webster.durations_s, webster.cycle_s),
            violated=list(webster.violated),
            problems=[
                ProblemRow(code=p.code, subject=p.subject, message=p.message)
                for p in webster.problems
            ],
            critical_path=_path_row(webster.critical_path),
        ),
    )


def _bytes(model: FrozenModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode("utf-8")


def publish_comparators(
    workspace: Path, result: ComparatorsResult, now: datetime | None = None
) -> Path:
    """Publica los comparadores en ``workspace/derivados/comparadores/<caso>/``.

    Raises:
        ReferenciasError: PATH_NOT_ALLOWED si el identificador del caso no sirve como nombre de
            carpeta; RUN_EXISTS si ya hay unos idénticos publicados en el mismo instante.
    """
    case = result.case
    if SAFE_FOLDER.fullmatch(case.case_id) is None:
        raise ReferenciasError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el identificador del caso solo puede tener letras, números, punto, guion bajo y "
            "guion para usarse como nombre de carpeta",
            "case_id",
        )
    content = _file_of(result)
    content_bytes = _bytes(content)
    parameters_bytes = _bytes(result.parameters)
    moment = (utc_now() if now is None else now).astimezone(UTC)
    manifest = ComparatorsManifest(
        created_at=moment,
        case_id=case.case_id,
        case_version=case.case_version,
        scenario_id=result.scenario_id,
        case_origin=content.case_origin,
        demand_origin=content.demand_origin,
        evidence_origin=content.evidence_origin,
        parameter_set=result.parameters.parameter_set,
        provisional=result.parameters.provisional,
        adaptation=content.webster.adaptation,
        webster_status=content.webster.status,
        current_plan_feasible=not content.current_plan.violated,
        network_sha256=None if case.network is None else case.network.sha256,
        files={
            COMPARATORS_FILE: sha256_bytes(content_bytes),
            PARAMETERS_FILE: sha256_bytes(parameters_bytes),
        },
    )
    final = (
        workspace
        / COMPARATORS
        / case.case_id
        / f"{moment:%Y%m%dT%H%M%SZ}_{sha256_bytes(content_bytes)[:SHORT_HASH_CHARS]}"
    )
    try:
        publish_files(
            final,
            {
                COMPARATORS_FILE: content_bytes,
                PARAMETERS_FILE: parameters_bytes,
                MANIFEST_FILE: _bytes(manifest),
            },
        )
    except FileExistsError as error:
        raise ReferenciasError(
            ErrorCode.RUN_EXISTS,
            "ya existen unos comparadores publicados con estos datos",
            "folder",
        ) from error
    return final


# --- lectura verificada ------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredComparators:
    """Comparadores leídos y verificados."""

    manifest: ComparatorsManifest
    comparators: ComparatorsFile
    parameters: WebsterParameters


def _bad(message: str, field: str | None = None) -> TrazabilidadError:
    return TrazabilidadError(ErrorCode.INPUT_SCHEMA, message, field)


def _read_file(folder: Path, name: str) -> bytes:
    try:
        with (folder / name).open("rb") as stream:
            data = read_at_most(stream, MAX_FILE_BYTES + 1)
    except OSError as error:
        raise _bad(f"no se puede leer ({type(error).__name__})", name) from error
    if len(data) > MAX_FILE_BYTES:
        raise _bad("el archivo es demasiado grande", name)
    return data


def read_comparators(folder: Path) -> StoredComparators:
    """Los comparadores de ``folder``, después de verificar la carpeta, las huellas y el manifiesto.

    Raises:
        TrazabilidadError: PATH_NOT_ALLOWED si hay enlaces; INPUT_SCHEMA si la carpeta, el
            manifiesto o un archivo no existen o no son válidos, o no coinciden entre sí;
            HASH_MISMATCH si un archivo sobra, falta o cambió.
    """
    manifest = read_verified(folder, MANIFEST_FILE, ComparatorsManifest, lambda m: m.files)
    if set(manifest.files) != {COMPARATORS_FILE, PARAMETERS_FILE}:
        raise _bad("el manifiesto no lista los archivos de unos comparadores", MANIFEST_FILE)
    try:
        content = ComparatorsFile.model_validate_json(_read_file(folder, COMPARATORS_FILE))
    except ValidationError as error:
        raise _bad(
            f"los comparadores no son válidos ({error.error_count()} problemas)", COMPARATORS_FILE
        ) from error
    try:
        parameters = WebsterParameters.model_validate_json(_read_file(folder, PARAMETERS_FILE))
    except ValidationError as error:
        raise _bad(
            f"los parámetros no son válidos ({error.error_count()} problemas)", PARAMETERS_FILE
        ) from error
    webster = content.webster
    same = (
        content.case_id == manifest.case_id
        and content.case_version == manifest.case_version
        and content.scenario_id == manifest.scenario_id
        and (content.case_origin, content.demand_origin, content.evidence_origin)
        == (manifest.case_origin, manifest.demand_origin, manifest.evidence_origin)
        and webster.status == manifest.webster_status
        and webster.adaptation == manifest.adaptation
        and webster.parameter_set == manifest.parameter_set == parameters.parameter_set
        and webster.provisional == manifest.provisional == parameters.provisional
        and (not content.current_plan.violated) == manifest.current_plan_feasible
        and (parameters.case_id, parameters.case_version)
        == (manifest.case_id, manifest.case_version)
    )
    if not same:
        raise _bad("los comparadores no coinciden con su manifiesto", COMPARATORS_FILE)
    return StoredComparators(manifest, content, parameters)
