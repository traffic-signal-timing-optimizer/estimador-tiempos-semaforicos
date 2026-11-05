"""Comparadores de DEV15: plan vigente y Webster (HU08, HU12).

- ``read_parameters``: los parámetros de Webster (``configs/webster``), marcados como provisionales
  mientras no los apruebe un especialista (DEC08).
- ``read_current_plan``: el plan vigente como dato observado, con su fuente, leído de la carpeta del
  programa publicado (verificada) y revisado con las reglas del caso (DEV13).
- ``crossing_structure``: en qué tramos tiene cada carril verde con prioridad (``G``).
- ``webster_inputs``: el flujo equivalente de cada carril, su relación de flujo y el recorrido
  crítico (F1 y F2).
- ``webster_timing``: el ciclo de Webster y el verde efectivo de cada carril (F2).
- ``webster_plan``: esos verdes como plan de tramos, redondeado a ticks y revisado con las reglas
  del caso (F3). Lo que no cabe queda «no aplicable»; no se corrige.

Regla de ``webster-solapes-v1``:

- Un carril se atiende en los tramos seguidos donde alguno de sus movimientos tiene ``G``.
- Un *recorrido* del ciclo pasa por todos sus tramos: cada tramo variable lo atiende uno de sus
  carriles y cada tramo fijo lo atiende uno de ellos o se pierde. Su Y es la suma de las relaciones
  de flujo de sus carriles y su L, la de los tramos fijos que pierde. El verde de un tramo que
  atiende a dos carriles a la vez no se cuenta dos veces.
- El recorrido crítico es el que exige el ciclo de Webster más largo, C0 = (1,5 L + 5) / (1 - Y).
- Webster no aplica si un carril con flujo solo tiene verde que cede el paso (``g``), no tiene
  verde o tiene su atención partida; si falta un dato; si ningún recorrido cubre el ciclo; si Y es 0
  o llega al límite; o si C0 sale de los límites del caso. Nunca se inventa ni se recorta un valor.
"""

import math
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
    "WebsterPlan",
    "WebsterTiming",
    "crossing_structure",
    "read_current_plan",
    "read_parameters",
    "webster_cycle",
    "webster_inputs",
    "webster_plan",
    "webster_timing",
]

ADAPTATION = "webster-solapes-v1"
PROTECTED = "G"
GREEN = frozenset("Ggs")
CYCLE_TOLERANCE_S = 1e-6
# Fórmula de Webster: C0 = (1,5 L + 5) / (1 - Y).
LOST_TIME_FACTOR = Fraction(3, 2)
LOST_TIME_EXTRA_S = Fraction(5)

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
    "no_covering_path",
    "no_demand",
    "oversaturated",
    "cycle_out_of_bounds",
    "path_without_variable_slot",
    "path_green_too_short",
    "lane_not_served",
    "plan_infeasible",
]


# --- parámetros --------------------------------------------------------------------------------


class Approval(FrozenModel):
    """Quién aprobó los parámetros; ``especialista`` vacío mientras no haya uno."""

    decision: str = Field(min_length=1)
    especialista: str | None
    nota: str


class ApplicabilityRules(FrozenModel):
    """Cuándo Webster deja de aplicar. No se recorta nunca (diseño técnico)."""

    y_must_be_below: Annotated[float, Field(gt=0, le=1)]
    cycle_must_be_inside_bounds: Literal[True]
    clipping_allowed: Literal[False]


class CurrentPlanRecord(FrozenModel):
    """Lo que se sabe del plan vigente además de sus tiempos: fuente, variación y confirmación."""

    source: str = Field(min_length=1)
    cycle_s: Positive
    hourly_variation: str = Field(min_length=1)
    confirmed_by: str = Field(min_length=1)


class WebsterParameters(FrozenModel):
    """Parámetros de Webster de un caso (``configs/webster/parametros-v2.json``).

    El tiempo perdido no es un número: lo da la regla ``lost_time_rule`` sobre el camino crítico.
    Los límites del ciclo son los del caso.
    """

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
    lost_time_rule: Literal["intergreens_outside_critical_path"]
    lost_time_note: str = Field(min_length=1)
    applicability: ApplicabilityRules
    current_plan: CurrentPlanRecord

    @model_validator(mode="after")
    def _consistent(self) -> Self:
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
    """El recorrido del ciclo que exige el ciclo de Webster más largo.

    Un recorrido pasa por todos los tramos del ciclo: cada tramo variable lo atiende uno de sus
    carriles, y cada tramo fijo lo atiende uno de ellos o se pierde. ``y`` es la suma de las
    relaciones de flujo de sus carriles (Y), ``lost_time_s`` la de los tramos fijos que pierde (L)
    y ``cycle_s`` el ciclo de Webster de ese par. Los carriles y tramos van en el orden del ciclo.
    """

    y: float
    lost_time_s: float
    cycle_s: float
    lane_ids: tuple[str, ...]
    lost_slot_ids: tuple[str, ...]


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


@dataclass(frozen=True)
class _Path:
    """Un recorrido (o el resto de uno) con cifras exactas."""

    y: Fraction
    lost: Fraction
    lanes: tuple[str, ...]
    lost_slots: tuple[str, ...]


def webster_cycle(y: Fraction, lost_time_s: Fraction) -> Fraction:
    """Ciclo de Webster C0 = (1,5 L + 5) / (1 - Y), con 0 <= Y < 1 y L >= 0."""
    return (LOST_TIME_FACTOR * lost_time_s + LOST_TIME_EXTRA_S) / (1 - y)


def _pareto(paths: Sequence[_Path]) -> list[_Path]:
    """Los recorridos que ningún otro supera a la vez en Y y en L (los demás piden menos ciclo)."""
    kept: list[_Path] = []
    for path in sorted(paths, key=lambda p: (-p.y, -p.lost, p.lanes, p.lost_slots)):
        if not any(other.y >= path.y and other.lost >= path.lost for other in kept):
            kept.append(path)
    return kept


def _covering_paths(
    case: Case, structure: CrossingStructure, ratios: Mapping[str, Fraction]
) -> list[_Path]:
    """Recorridos del ciclo que atienden todos los tramos variables, sin repetir un tramo.

    Por cada tramo de atención basta el carril de mayor relación de flujo: los demás con el mismo
    tramo tienen la misma pérdida y menos Y.
    """
    count = len(case.slots)
    best: dict[tuple[int, int], tuple[Fraction, str]] = {}
    for lane in structure.lanes:
        if lane.span is None:
            continue
        ratio = ratios[lane.lane_id]
        current = best.get(lane.span)
        if current is None or (-ratio, lane.lane_id) < (-current[0], current[1]):
            best[lane.span] = (ratio, lane.lane_id)
    starting: dict[int, list[tuple[int, Fraction, str]]] = {}
    for (start, end), (ratio, lane_id) in sorted(best.items()):
        starting.setdefault(start, []).append((end, ratio, lane_id))
    suffix: list[list[_Path]] = [[] for _ in range(count + 1)]
    suffix[count] = [_Path(Fraction(0), Fraction(0), (), ())]
    for position in range(count - 1, -1, -1):
        options = [
            _Path(rest.y + ratio, rest.lost, (lane_id, *rest.lanes), rest.lost_slots)
            for end, ratio, lane_id in starting.get(position, [])
            for rest in suffix[end + 1]
        ]
        slot = case.slots[position]
        if slot.kind == "fixed":
            options.extend(
                _Path(
                    rest.y,
                    rest.lost + Fraction(slot.min_s),
                    rest.lanes,
                    (slot.id, *rest.lost_slots),
                )
                for rest in suffix[position + 1]
            )
        suffix[position] = _pareto(options)
    return suffix[0]


@dataclass(frozen=True)
class _Evaluation:
    """Lo calculado con cifras exactas, antes de pasarlo a los resultados."""

    ratios: dict[str, Fraction]
    problems: list[Problem]
    path: _Path | None


def _choose(paths: Sequence[_Path], parameters: WebsterParameters) -> _Path | Problem:
    if not paths:
        return Problem(
            "no_covering_path",
            "ciclo",
            "ningún recorrido del ciclo atiende todos los tramos variables",
        )
    highest = max(path.y for path in paths)
    if highest == 0:
        return Problem("no_demand", "ciclo", "ningún carril del recorrido tiene flujo (Y = 0)")
    if highest >= Fraction(parameters.applicability.y_must_be_below):
        return Problem(
            "oversaturated",
            "ciclo",
            f"Y = {float(highest):.3f}: el cruce está saturado y Webster no da un ciclo",
        )
    return min(
        paths,
        key=lambda path: (-webster_cycle(path.y, path.lost), -path.y, path.lanes, path.lost_slots),
    )


def _evaluate(
    structure: CrossingStructure, case: Case, request: Request, parameters: WebsterParameters
) -> _Evaluation:
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
    if problems:
        return _Evaluation(ratios, problems, None)
    chosen = _choose(_covering_paths(case, structure, ratios), parameters)
    if isinstance(chosen, Problem):
        return _Evaluation(ratios, [chosen], None)
    return _Evaluation(ratios, [], chosen)


def _public_path(path: _Path) -> CriticalPath:
    return CriticalPath(
        y=float(path.y),
        lost_time_s=float(path.lost),
        cycle_s=float(webster_cycle(path.y, path.lost)),
        lane_ids=path.lanes,
        lost_slot_ids=path.lost_slots,
    )


def webster_inputs(
    structure: CrossingStructure, case: Case, request: Request, parameters: WebsterParameters
) -> WebsterInputs:
    """Relación de flujo de cada carril y recorrido crítico, o por qué Webster no aplica.

    Raises:
        ReferenciasError: INPUT_SCHEMA si la solicitud o los parámetros son de otro caso.
    """
    evaluation = _evaluate(structure, case, request, parameters)
    return WebsterInputs(
        status="not_applicable" if evaluation.problems else "applicable",
        problems=tuple(evaluation.problems),
        flow_ratios={k: float(v) for k, v in evaluation.ratios.items() if v > 0},
        critical_path=None if evaluation.path is None else _public_path(evaluation.path),
        parameter_set=parameters.parameter_set,
        provisional=parameters.provisional,
    )


# --- ciclo y verdes de Webster -----------------------------------------------------------------


@dataclass(frozen=True)
class WebsterTiming:
    """Ciclo de Webster y verde efectivo que pide cada carril con flujo, o por qué no aplica.

    El verde efectivo reparte C0 - L en proporción a la relación de flujo de cada carril, así que
    todos los carriles del recorrido crítico quedan con el mismo grado de saturación. Si el ciclo
    sale fuera de los límites del caso, se informa y no se recorta (D6).
    """

    status: Literal["applicable", "not_applicable"]
    problems: tuple[Problem, ...]
    cycle_s: float | None
    effective_green_s: Mapping[str, float]
    critical_path: CriticalPath | None
    parameter_set: str
    provisional: bool
    adaptation: str = ADAPTATION


@dataclass(frozen=True)
class _ExactTiming:
    path: _Path | None
    problems: list[Problem]
    cycle: Fraction | None
    greens: dict[str, Fraction]


def _exact_timing(
    structure: CrossingStructure, case: Case, request: Request, parameters: WebsterParameters
) -> _ExactTiming:
    evaluation = _evaluate(structure, case, request, parameters)
    problems = list(evaluation.problems)
    path = evaluation.path
    cycle: Fraction | None = None
    greens: dict[str, Fraction] = {}
    if path is not None:
        cycle = webster_cycle(path.y, path.lost)
        low, high = Fraction(case.cycle_s.min), Fraction(case.cycle_s.max)
        if not low <= cycle <= high:
            problems.append(
                Problem(
                    "cycle_out_of_bounds",
                    "ciclo",
                    f"Webster da {float(cycle):.1f} s y el caso admite de {case.cycle_s.min:g} "
                    f"a {case.cycle_s.max:g} s; no se recorta",
                )
            )
        else:
            usable = cycle - path.lost
            greens = {
                lane_id: ratio * usable / path.y
                for lane_id, ratio in evaluation.ratios.items()
                if ratio > 0
            }
    return _ExactTiming(path, problems, cycle, greens)


def webster_timing(
    structure: CrossingStructure, case: Case, request: Request, parameters: WebsterParameters
) -> WebsterTiming:
    """El ciclo de Webster y el verde efectivo de cada carril para ``request``.

    Raises:
        ReferenciasError: INPUT_SCHEMA si la solicitud o los parámetros son de otro caso.
    """
    exact = _exact_timing(structure, case, request, parameters)
    return WebsterTiming(
        status="not_applicable" if exact.problems else "applicable",
        problems=tuple(exact.problems),
        cycle_s=None if exact.cycle is None else float(exact.cycle),
        effective_green_s={lane_id: float(green) for lane_id, green in exact.greens.items()},
        critical_path=None if exact.path is None else _public_path(exact.path),
        parameter_set=parameters.parameter_set,
        provisional=parameters.provisional,
    )


# --- plan de tramos de Webster (F3) ------------------------------------------------------------


@dataclass(frozen=True)
class WebsterPlan:
    """El plan de tramos que sale de Webster, o por qué no hay uno.

    ``durations_s`` es la propuesta ya redondeada a ticks, cuando se pudo traducir; si incumple
    las reglas del caso, ``status`` es ``not_applicable`` y ``violated`` dice cuáles. Nunca se
    corrige: se informa.
    """

    status: Literal["applicable", "not_applicable"]
    problems: tuple[Problem, ...]
    durations_s: Mapping[str, float] | None
    cycle_s: float | None
    webster_cycle_s: float | None
    violated: tuple[str, ...]
    critical_path: CriticalPath | None
    parameter_set: str
    provisional: bool
    adaptation: str = ADAPTATION


def _variable_in(case: Case, span: tuple[int, int]) -> list[int]:
    return [k for k in range(span[0], span[1] + 1) if case.slots[k].kind == "variable"]


def _fixed_in(case: Case, span: tuple[int, int]) -> Fraction:
    return sum(
        (
            Fraction(case.slots[k].min_s)
            for k in range(span[0], span[1] + 1)
            if case.slots[k].kind == "fixed"
        ),
        Fraction(0),
    )


def _span(lanes: Mapping[str, LaneService], lane_id: str) -> tuple[int, int]:
    span = lanes[lane_id].span
    if span is None:  # el recorrido y los verdes solo tienen carriles con atención seguida
        raise _bad(f"el carril {lane_id} no tiene una atención seguida", "lanes")
    return span


def _split(
    case: Case,
    lanes: Mapping[str, LaneService],
    lane_id: str,
    greens: Mapping[str, Fraction],
    on_path: frozenset[str],
) -> dict[int, Fraction] | Problem:
    """Reparte el verde de un carril del recorrido entre sus tramos variables.

    Cada tramo parte de su mínimo o de lo que pida un carril que se atiende solo dentro de este
    carril; lo que sobra va al tramo que atienden menos carriles con flujo (si empatan, al último).
    Un carril del recorrido sin flujo no pide verde: sus tramos quedan en ese mínimo y el plan
    puede pasar el ciclo de Webster, algo que revisan después las reglas del caso.
    """
    span = _span(lanes, lane_id)
    own = _variable_in(case, span)
    if not own:
        return Problem(
            "path_without_variable_slot",
            lane_id,
            "un carril del recorrido crítico solo tiene tramos fijos: su verde no se puede ajustar",
        )
    lower = {k: Fraction(case.slots[k].min_s) for k in own}
    inner = [
        lanes[other]
        for other in greens
        if other not in on_path
        and span[0] <= _span(lanes, other)[0]
        and _span(lanes, other)[1] <= span[1]
    ]
    for other in sorted(inner, key=lambda lane: (_span(lanes, lane.lane_id), lane.lane_id)):
        mine = _variable_in(case, _span(lanes, other.lane_id))
        if mine:
            need = greens[other.lane_id] - _fixed_in(case, _span(lanes, other.lane_id))
            missing = need - sum((lower[k] for k in mine), Fraction(0))
            if missing > 0:
                lower[mine[0]] += missing
    required = greens.get(lane_id)
    if required is None:
        return lower
    extra = required - _fixed_in(case, span) - sum(lower.values(), Fraction(0))
    if extra < 0:
        return Problem(
            "path_green_too_short",
            lane_id,
            f"su verde de Webster ({float(required):.1f} s) no alcanza para los mínimos de "
            "sus tramos y los carriles que atiende con ellos",
        )
    served = {
        k: sum(1 for other in greens if _span(lanes, other)[0] <= k <= _span(lanes, other)[1])
        for k in own
    }
    target = min(own, key=lambda k: (served[k], -k))
    lower[target] += extra
    return lower


def _translate(
    case: Case, structure: CrossingStructure, path: _Path, greens: Mapping[str, Fraction]
) -> dict[str, Fraction] | Problem:
    """Duración exacta de cada tramo, o el problema que impide traducir los verdes."""
    lanes = {lane.lane_id: lane for lane in structure.lanes}
    durations = {
        k: Fraction(slot.min_s) for k, slot in enumerate(case.slots) if slot.kind == "fixed"
    }
    on_path = frozenset(path.lanes)
    for lane_id in path.lanes:
        split = _split(case, lanes, lane_id, greens, on_path)
        if isinstance(split, Problem):
            return split
        durations.update(split)
    for lane_id, need in sorted(greens.items()):
        start, end = _span(lanes, lane_id)
        got = sum((durations[k] for k in range(start, end + 1)), Fraction(0))
        if got < need:
            return Problem(
                "lane_not_served",
                lane_id,
                f"el plan le da {float(got):.1f} s de verde y Webster le pide {float(need):.1f} s",
            )
    return {slot.id: durations[k] for k, slot in enumerate(case.slots)}


def _rounded(case: Case, durations: Mapping[str, Fraction]) -> dict[str, float]:
    """Los tramos variables al tick más cercano (la mitad hacia arriba); los fijos, igual."""
    tick = Fraction(case.tick_s)
    result: dict[str, float] = {}
    for slot in case.slots:
        value = durations[slot.id]
        if slot.kind == "variable":
            value = math.floor(value / tick + Fraction(1, 2)) * tick
        result[slot.id] = float(value)
    return result


def webster_plan(
    structure: CrossingStructure,
    prepared: PreparedCase,
    request: Request,
    parameters: WebsterParameters,
) -> WebsterPlan:
    """El plan de tramos de Webster para ``request``, revisado con las reglas del caso.

    Raises:
        ReferenciasError: INPUT_SCHEMA si la solicitud o los parámetros son de otro caso.
    """
    case = prepared.case
    exact = _exact_timing(structure, case, request, parameters)
    problems = list(exact.problems)
    durations: dict[str, float] | None = None
    violated: tuple[str, ...] = ()
    if not problems and exact.path is not None:
        translated = _translate(case, structure, exact.path, exact.greens)
        if isinstance(translated, Problem):
            problems.append(translated)
        else:
            durations = _rounded(case, translated)
            violated = check_plan(prepared, durations).violated
            if violated:
                problems.append(
                    Problem(
                        "plan_infeasible",
                        "plan",
                        f"el plan de Webster incumple {', '.join(violated)}; no se corrige",
                    )
                )
    return WebsterPlan(
        status="not_applicable" if problems else "applicable",
        problems=tuple(problems),
        durations_s=durations,
        cycle_s=None if durations is None else math.fsum(durations.values()),
        webster_cycle_s=None if exact.cycle is None else float(exact.cycle),
        violated=violated,
        critical_path=None if exact.path is None else _public_path(exact.path),
        parameter_set=parameters.parameter_set,
        provisional=parameters.provisional,
    )
