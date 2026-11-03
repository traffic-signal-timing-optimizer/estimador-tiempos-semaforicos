"""Comparadores de DEV15: plan vigente y Webster (HU08, HU12).

Primera parte (F1), sin calcular todavía el ciclo:

- ``read_parameters``: los parámetros de Webster (``configs/webster``), marcados como provisionales
  mientras no los apruebe un especialista (DEC08).
- ``read_current_plan``: el plan vigente como dato observado, con su fuente, leído de la carpeta del
  programa publicado (verificada) y revisado con las reglas del caso (DEV13).
- ``crossing_structure``: en qué tramos tiene cada carril verde con prioridad (``G``).
- ``webster_inputs``: el flujo equivalente de cada carril, su relación de flujo y el camino crítico.

Regla de conteo de ``webster-solapes-v1``: un carril se atiende en los tramos seguidos donde
alguno de sus movimientos tiene ``G``. Y es la mayor suma de relaciones de flujo entre carriles
cuyos tramos de atención no se tocan (el camino crítico). Es el mínimo verde que el ciclo debe dar:
el verde de un tramo que atiende a dos carriles a la vez no se cuenta dos veces. Un carril con
flujo y solo verde que cede el paso (``g``), sin verde, o con su atención partida, deja a Webster
«no aplicable»: la fórmula no sabe dimensionarlo y no se inventa un valor.
"""

import math
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from semaforo.caso.json_input import read_json
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case, Movement
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import PreparedCase, check_plan
from semaforo.dominio.scenario import Request
from semaforo.referencias.errors import ReferenciasError
from semaforo.simulacion.compiler import SLOTS_FILE, read_program

__all__ = [
    "ADAPTATION",
    "CriticalPath",
    "CrossingStructure",
    "LaneService",
    "ObservedPlan",
    "Problem",
    "WebsterInputs",
    "WebsterParameters",
    "crossing_structure",
    "read_current_plan",
    "read_parameters",
    "webster_inputs",
]

ADAPTATION = "webster-solapes-v1"
PROTECTED = "G"
GREEN = frozenset("Ggs")
BOUNDS = 2
CYCLE_TOLERANCE_S = 1e-6

Positive = Annotated[float, Field(gt=0)]
NonNegative = Annotated[float, Field(ge=0)]
Shape = Literal["contiguous", "wrapping", "split", "none"]
ProblemCode = Literal[
    "missing_flow",
    "missing_composition",
    "missing_equivalence",
    "lane_never_green",
    "permissive_only",
    "split_service",
    "wrapping_service",
]


# --- parámetros --------------------------------------------------------------------------------


class Approval(FrozenModel):
    """Quién aprobó los parámetros; ``especialista`` vacío mientras no haya uno."""

    decision: str = Field(min_length=1)
    especialista: str | None
    nota: str


class ApplicabilityRules(FrozenModel):
    """Cuándo Webster deja de aplicar. No se recorta nunca (diseño técnico)."""

    y_must_be_below: Positive
    cycle_must_be_inside_bounds: Literal[True]
    clipping_allowed: Literal[False]


class CurrentPlanRecord(FrozenModel):
    """Lo que se sabe del plan vigente además de sus tiempos: fuente, variación y confirmación."""

    source: str = Field(min_length=1)
    cycle_s: Positive
    hourly_variation: str = Field(min_length=1)
    confirmed_by: str = Field(min_length=1)


class WebsterParameters(FrozenModel):
    """Parámetros de Webster de un caso (``configs/webster/parametros-v1.json``)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    parameter_set: str = Field(min_length=1)
    status: Literal["provisional", "approved"]
    approval: Approval
    case_id: str
    case_version: str
    adaptation: Literal["webster-solapes-v1"]
    saturation_flow_veh_h_lane: Positive
    saturation_flow_sensitivity_veh_h_lane: list[Positive]
    vehicle_equivalence: dict[str, NonNegative]
    lost_time_s: NonNegative
    lost_time_source: str = Field(min_length=1)
    cycle_bounds_s: list[Positive]
    applicability: ApplicabilityRules
    current_plan: CurrentPlanRecord

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        bounds = self.cycle_bounds_s
        if len(bounds) != BOUNDS or bounds[0] > bounds[1]:
            raise ValueError("cycle_bounds_s debe ser [mínimo, máximo] con el mínimo primero")
        if self.status == "approved" and self.approval.especialista is None:
            raise ValueError("unos parámetros aprobados necesitan al especialista que los aprobó")
        return self

    @property
    def provisional(self) -> bool:
        return self.status != "approved"


def read_parameters(path: Path, case: Case) -> WebsterParameters:
    """Los parámetros de Webster de ``path``, que deben ser de ``case``.

    Raises:
        CasoError: lo que lanza la lectura del JSON (enlace, tamaño, UTF-8, JSON inválido).
        ReferenciasError: INPUT_SCHEMA si no cumplen su modelo o son de otro caso o versión.
    """
    data = read_json(path, "parámetros de Webster")
    try:
        parameters = WebsterParameters.model_validate(data)
    except ValidationError as error:
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA,
            f"los parámetros de Webster no son válidos ({error.error_count()} problemas)",
            "parameters",
        ) from error
    if (parameters.case_id, parameters.case_version) != (case.case_id, case.case_version):
        raise ReferenciasError(
            ErrorCode.INPUT_SCHEMA,
            "los parámetros de Webster son de otro caso o de otra versión del caso",
            "case_id",
        )
    return parameters


# --- plan vigente ------------------------------------------------------------------------------


class _SlotRow(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True, allow_inf_nan=False)

    id: str
    duration_s: Positive


class _SlotsFile(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True, allow_inf_nan=False)

    slots: list[_SlotRow]


@dataclass(frozen=True)
class ObservedPlan:
    """El plan vigente como dato observado: sus tiempos, su fuente y las reglas que incumple."""

    durations_s: Mapping[str, float]
    cycle_s: float
    source: str
    hourly_variation: str
    confirmed_by: str
    program_folder: str
    violated: tuple[str, ...]

    @property
    def feasible(self) -> bool:
        return not self.violated


def _bad(message: str, field: str) -> ReferenciasError:
    return ReferenciasError(ErrorCode.INPUT_SCHEMA, message, field)


def read_current_plan(
    program_folder: Path, prepared: PreparedCase, parameters: WebsterParameters
) -> ObservedPlan:
    """El plan vigente del programa publicado en ``program_folder``.

    Un plan que incumple las reglas del caso se devuelve igual, con las reglas incumplidas: es lo
    que se observó y no se corrige.

    Raises:
        TrazabilidadError: si la carpeta del programa no está completa o cambió.
        ReferenciasError: INPUT_SCHEMA si el programa es de otro caso, sus tramos no son los del
            caso o su ciclo no es el que registran los parámetros.
    """
    case = prepared.case
    manifest = read_program(program_folder)
    if (manifest.case_id, manifest.case_version) != (case.case_id, case.case_version):
        raise _bad("el programa del plan vigente es de otro caso o versión", "program")
    try:
        rows = _SlotsFile.model_validate(read_json(program_folder / SLOTS_FILE, "tramos")).slots
    except ValidationError as error:
        raise _bad("los tramos del plan vigente no son válidos", SLOTS_FILE) from error
    durations = {row.id: row.duration_s for row in rows}
    if [row.id for row in rows] != [slot.id for slot in case.slots]:
        raise _bad("los tramos del plan vigente no son los del caso", SLOTS_FILE)
    cycle = math.fsum(durations.values())
    if abs(cycle - parameters.current_plan.cycle_s) > CYCLE_TOLERANCE_S:
        raise _bad("el ciclo del plan vigente no es el registrado en los parámetros", "cycle_s")
    record = parameters.current_plan
    return ObservedPlan(
        durations_s=durations,
        cycle_s=cycle,
        source=record.source,
        hourly_variation=record.hourly_variation,
        confirmed_by=record.confirmed_by,
        program_folder=program_folder.name,
        violated=check_plan(prepared, durations).violated,
    )


# --- estructura del cruce ----------------------------------------------------------------------


@dataclass(frozen=True)
class LaneService:
    """Un carril de entrada: sus movimientos y los tramos en que se atiende.

    ``protected`` son los tramos (en el orden del ciclo) donde alguno de sus movimientos tiene
    ``G``; ``permissive``, los que solo tienen verde que cede el paso. ``span`` es el primer y el
    último índice de ``protected`` cuando son seguidos (``shape`` = ``contiguous``).
    """

    lane_id: str
    approach_id: str
    movement_ids: tuple[str, ...]
    protected: tuple[str, ...]
    permissive: tuple[str, ...]
    shape: Shape
    span: tuple[int, int] | None


@dataclass(frozen=True)
class CrossingStructure:
    """Los tramos del caso, en orden, y cómo se atiende cada carril de entrada."""

    slot_ids: tuple[str, ...]
    lanes: tuple[LaneService, ...]


def _letters(case: Case, movement: Movement) -> list[str]:
    """La letra de las señales de ``movement`` en cada tramo: ``G``, verde que cede o rojo."""
    letters: list[str] = []
    for slot in case.slots:
        state = next((s.state for s in slot.states if s.tls_id == movement.tls_id), None)
        if state is None or any(index >= len(state) for index in movement.link_indices):
            raise _bad(
                f"el tramo {slot.id} no tiene la señal del movimiento {movement.id}", "slots"
            )
        signals = [state[index] for index in movement.link_indices]
        if all(signal == PROTECTED for signal in signals):
            letters.append(PROTECTED)
        elif any(signal in GREEN for signal in signals):
            letters.append("g")
        else:
            letters.append("r")
    return letters


def _shape(indices: Sequence[int], count: int) -> tuple[Shape, tuple[int, int] | None]:
    if not indices:
        return "none", None
    first, last = indices[0], indices[-1]
    if list(indices) == list(range(first, last + 1)):
        return "contiguous", (first, last)
    chosen = set(indices)
    ends = sum(1 for index in chosen if (index + 1) % count not in chosen)
    return ("wrapping" if ends == 1 else "split"), None


def crossing_structure(case: Case) -> CrossingStructure:
    """Cómo se atiende cada carril de entrada del caso, tramo por tramo.

    Raises:
        ReferenciasError: INPUT_SCHEMA si un tramo no tiene la señal de un movimiento.
    """
    slot_ids = tuple(slot.id for slot in case.slots)
    by_lane: dict[str, list[tuple[Movement, list[str]]]] = {}
    for movement in case.movements:
        letters = _letters(case, movement)
        for lane in movement.incoming_lanes:
            by_lane.setdefault(lane, []).append((movement, letters))
    lanes: list[LaneService] = []
    for lane_id, served in by_lane.items():
        protected = [
            index
            for index in range(len(slot_ids))
            if any(letters[index] == PROTECTED for _, letters in served)
        ]
        permissive = [
            index
            for index in range(len(slot_ids))
            if index not in protected and any(letters[index] == "g" for _, letters in served)
        ]
        shape, span = _shape(protected, len(slot_ids))
        lanes.append(
            LaneService(
                lane_id=lane_id,
                approach_id=served[0][0].approach_id,
                movement_ids=tuple(movement.id for movement, _ in served),
                protected=tuple(slot_ids[index] for index in protected),
                permissive=tuple(slot_ids[index] for index in permissive),
                shape=shape,
                span=span,
            )
        )
    return CrossingStructure(slot_ids, tuple(lanes))


# --- flujos y camino crítico -------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    """Por qué Webster no aplica: un código estable, de qué se trata y un mensaje."""

    code: ProblemCode
    subject: str
    message: str


@dataclass(frozen=True)
class CriticalPath:
    """Los carriles cuyos tramos de atención no se tocan y cuya suma de relaciones de flujo es la
    mayor. ``y`` es esa suma, Y de Webster. Los carriles van en el orden del ciclo."""

    y: float
    lane_ids: tuple[str, ...]


@dataclass(frozen=True)
class WebsterInputs:
    """Lo que Webster necesita de un escenario, o por qué no aplica."""

    status: Literal["applicable", "not_applicable"]
    problems: tuple[Problem, ...]
    flow_ratios: Mapping[str, float]
    critical_path: CriticalPath | None
    parameter_set: str
    provisional: bool
    adaptation: str = ADAPTATION


def _movement_flows(
    case: Case, request: Request, parameters: WebsterParameters
) -> tuple[dict[str, Fraction], list[Problem]]:
    """Flujo equivalente (autos por hora) de cada movimiento, sin inventar los que faltan."""
    rows = {row.movement_id: row for row in request.demand}
    flows: dict[str, Fraction] = {}
    problems: list[Problem] = []
    for movement in case.movements:
        row = rows.get(movement.id)
        if row is None:
            problems.append(Problem("missing_flow", movement.id, "el escenario no trae su flujo"))
            continue
        if row.flow_vph == 0:
            flows[movement.id] = Fraction(0)
            continue
        if row.composition is None:
            problems.append(
                Problem("missing_composition", movement.id, "tiene flujo y no trae su composición")
            )
            continue
        factor = Fraction(0)
        for vehicle_class, share in sorted(row.composition.items()):
            if share == 0:
                continue
            equivalence = parameters.vehicle_equivalence.get(vehicle_class)
            if equivalence is None:
                problems.append(
                    Problem(
                        "missing_equivalence",
                        vehicle_class,
                        f"la clase {vehicle_class} no tiene equivalencia en los parámetros",
                    )
                )
                break
            factor += Fraction(share) * Fraction(equivalence)
        else:
            flows[movement.id] = Fraction(row.flow_vph) * factor
    return flows, problems


def _lane_problem(lane: LaneService) -> Problem | None:
    if lane.shape == "contiguous":
        return None
    if lane.shape == "none":
        if lane.permissive:
            return Problem(
                "permissive_only",
                lane.lane_id,
                "tiene flujo y solo verde que cede el paso: Webster no sabe dimensionarlo",
            )
        return Problem("lane_never_green", lane.lane_id, "tiene flujo y nunca recibe verde")
    if lane.shape == "wrapping":
        return Problem(
            "wrapping_service",
            lane.lane_id,
            "su verde cruza el fin del ciclo; esta versión no lo admite",
        )
    return Problem("split_service", lane.lane_id, "su verde está partido en tramos no seguidos")


def _better(
    first: tuple[Fraction, tuple[str, ...]], second: tuple[Fraction, tuple[str, ...]]
) -> bool:
    """Mayor suma; si empatan, los carriles con nombres menores (para que el orden no cambie)."""
    return first[0] > second[0] or (first[0] == second[0] and sorted(first[1]) < sorted(second[1]))


def _critical_path(lanes: Sequence[tuple[LaneService, Fraction]]) -> tuple[Fraction, list[str]]:
    """Mayor suma de relaciones de flujo entre carriles cuyos tramos no se tocan."""
    items: list[tuple[tuple[int, int], Fraction, str]] = sorted(
        (
            (lane.span, ratio, lane.lane_id)
            for lane, ratio in lanes
            if lane.span is not None and ratio > 0
        ),
        key=lambda item: (item[0][1], item[0][0], item[2]),
    )
    ends = [span[1] for span, _, _ in items]
    best: list[tuple[Fraction, tuple[str, ...]]] = [(Fraction(0), ())]
    for position, (span, ratio, lane_id) in enumerate(items):
        before = bisect_left(ends, span[0], 0, position)
        take = (best[before][0] + ratio, (*best[before][1], lane_id))
        best.append(take if _better(take, best[position]) else best[position])
    total, chosen = best[-1]
    starts = {lane_id: span[0] for span, _, lane_id in items}
    return total, sorted(chosen, key=lambda lane_id: (starts[lane_id], lane_id))


def webster_inputs(
    structure: CrossingStructure, case: Case, request: Request, parameters: WebsterParameters
) -> WebsterInputs:
    """Relación de flujo de cada carril y camino crítico, o por qué Webster no aplica.

    Raises:
        ReferenciasError: INPUT_SCHEMA si la solicitud o los parámetros son de otro caso.
    """
    pair = (case.case_id, case.case_version)
    if (request.case_id, request.case_version) != pair:
        raise _bad("la solicitud es de otro caso o versión", "request")
    if (parameters.case_id, parameters.case_version) != pair:
        raise _bad("los parámetros de Webster son de otro caso o versión", "parameters")
    flows, problems = _movement_flows(case, request, parameters)
    saturation = Fraction(parameters.saturation_flow_veh_h_lane)
    lane_count = {movement.id: len(movement.incoming_lanes) for movement in case.movements}
    ratios: dict[str, Fraction] = {}
    for lane in structure.lanes:
        flow = sum(
            (flows.get(movement_id, Fraction(0)) / lane_count[movement_id])
            for movement_id in lane.movement_ids
        )
        ratios[lane.lane_id] = Fraction(flow) / saturation
        if flow > 0:
            problem = _lane_problem(lane)
            if problem is not None:
                problems.append(problem)
    flow_ratios = {lane_id: float(ratio) for lane_id, ratio in ratios.items() if ratio > 0}
    path = None
    if not problems:
        total, chosen = _critical_path([(lane, ratios[lane.lane_id]) for lane in structure.lanes])
        path = CriticalPath(float(total), tuple(chosen))
    return WebsterInputs(
        status="not_applicable" if problems else "applicable",
        problems=tuple(problems),
        flow_ratios=flow_ratios,
        critical_path=path,
        parameter_set=parameters.parameter_set,
        provisional=parameters.provisional,
    )
