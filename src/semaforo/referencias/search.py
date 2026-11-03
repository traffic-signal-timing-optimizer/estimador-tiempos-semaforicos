"""Candidatos de la búsqueda de referencias (DEV14 F1, HU08, QA16).

Diseño técnico, «Búsqueda propuesta reproducible»: para cada escenario se enumeran los planes de
una grilla de ticks factibles si caben en el presupuesto B; si no caben, se toma una muestra
uniforme y reproducible de duraciones dentro de sus límites, con rechazo de los inviables,
deduplicación por vector y un máximo de intentos declarado. No se garantiza el óptimo global.

Reglas de este módulo (acta de DEV14 F0):

- Un plan es el vector de ticks enteros de los slots variables del caso; los slots fijos van con
  su valor. Dos planes con el mismo vector son el mismo plan.
- Cada candidato pasa por ``check_plan`` (DEV13): ciclo, límites de slot, tick y verde de cada
  grupo. Un plan inviable no es candidato; se cuenta por la primera regla que viola.
- **Grilla:** si la caja de ticks (producto de los valores posibles de cada slot variable) tiene
  como mucho ``GRID_SCAN_LIMIT`` vectores, se recorre entera; si los factibles caben en B, son los
  candidatos, en orden lexicográfico. Si no, o si la caja es mayor, se muestrea.
- **Muestreo:** cada intento elige, para cada slot variable, un número de ticks uniforme entre su
  mínimo y su máximo. El azar sale de SHA-256 de la semilla, el escenario, el intento y el slot:
  no depende de la versión de Python. Un caso con los mismos límites da la misma muestra. Un
  vector ya visto (factible o no) es un duplicado y no se vuelve a evaluar. Se para al llenar B
  o al agotar los intentos (``exhausted``): entonces hay menos candidatos que B, y queda
  registrado.
- **B cuenta candidatos únicos y factibles** generados por la búsqueda. El plan vigente, si se da
  y es factible, entra como candidato auxiliar que **no consume B**; si es inviable, queda
  excluido con sus reglas. Un vector muestreado igual al vigente es un duplicado.

Es puro: no lee archivos, no lanza procesos y no simula (ADR01). La evaluación con SUMO es de F2.
"""

import hashlib
import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import PreparedCase, check_plan
from semaforo.dominio.timing import shown
from semaforo.referencias.errors import ReferenciasError

__all__ = [
    "GRID_SCAN_LIMIT",
    "SEARCH_VERSION",
    "Candidate",
    "CandidateOrigin",
    "CandidateSet",
    "CurrentPlanStatus",
    "SearchMethod",
    "generate_candidates",
]

SearchMethod = Literal["grid", "sampling"]
CandidateOrigin = Literal["grid", "sampled", "current_plan"]
CurrentPlanStatus = Literal["absent", "included", "excluded"]
# Versión del algoritmo de candidatos: entra en la traza. Cambiarla obliga a distinguir lo buscado
# antes de lo buscado después.
SEARCH_VERSION = "1.0.0"
# Tamaño máximo de caja que se recorre entera para ver si la grilla factible cabe en B.
GRID_SCAN_LIMIT = 20_000
_DIGEST_SPACE = 1 << 256


@dataclass(frozen=True)
class Candidate:
    """Un plan candidato: su vector de ticks, sus duraciones y de dónde salió.

    ``candidate_id`` es la huella del vector (no del orden de aparición): el mismo plan tiene el
    mismo identificador en cualquier búsqueda del mismo caso.
    """

    candidate_id: str
    origin: CandidateOrigin
    consumes_budget: bool
    ticks: Mapping[str, int]
    durations_s: Mapping[str, float]


@dataclass(frozen=True)
class CandidateSet:
    """Los candidatos de un escenario y la traza de cómo se obtuvieron."""

    scenario_id: str
    rules_version: str
    seed: int
    method: SearchMethod
    budget: int
    attempt_limit: int
    space_size: int
    grid_feasible: int | None
    attempts: int
    duplicates: int
    infeasible: int
    infeasible_by_rule: Mapping[str, int]
    exhausted: bool
    current_plan: CurrentPlanStatus
    current_plan_violated: tuple[str, ...]
    candidates: tuple[Candidate, ...]

    @property
    def budget_used(self) -> int:
        """Candidatos que consumen B (los de la búsqueda, no el plan vigente)."""
        return sum(1 for candidate in self.candidates if candidate.consumes_budget)

    def trace(self) -> dict[str, object]:
        """La traza en forma de JSON, con todos los candidatos y los conteos de la búsqueda."""
        return {
            "search_version": SEARCH_VERSION,
            "scenario_id": self.scenario_id,
            "rules_version": self.rules_version,
            "seed": self.seed,
            "method": self.method,
            "budget": self.budget,
            "budget_counts": "unique_feasible_search_candidates",
            "budget_used": self.budget_used,
            "attempt_limit": self.attempt_limit,
            "grid_scan_limit": GRID_SCAN_LIMIT,
            "space_size": self.space_size,
            "grid_feasible": self.grid_feasible,
            "attempts": self.attempts,
            "duplicates": self.duplicates,
            "infeasible": self.infeasible,
            "infeasible_by_rule": dict(self.infeasible_by_rule),
            "exhausted": self.exhausted,
            "current_plan": {
                "status": self.current_plan,
                "violated": list(self.current_plan_violated),
            },
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "origin": candidate.origin,
                    "consumes_budget": candidate.consumes_budget,
                    "ticks": dict(candidate.ticks),
                    "durations_s": dict(candidate.durations_s),
                }
                for candidate in self.candidates
            ],
        }


def _invalid(message: str, field: str) -> ReferenciasError:
    return ReferenciasError(ErrorCode.INPUT_SCHEMA, message, field)


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} debe ser un entero mayor que cero, no {shown(value)!r}", field)
    return value


def _exact(value: float) -> Fraction:
    return Fraction(repr(float(value)))


@dataclass(frozen=True)
class _Space:
    """Los valores posibles de cada slot variable, en ticks enteros, y los fijos."""

    prepared: PreparedCase
    tick: Fraction
    ranges: tuple[tuple[str, int, int], ...]
    fixed: Mapping[str, float]

    @property
    def size(self) -> int:
        return math.prod(high - low + 1 for _, low, high in self.ranges)

    def durations(self, vector: tuple[int, ...]) -> dict[str, float]:
        durations = dict(self.fixed)
        for (slot_id, _, _), ticks in zip(self.ranges, vector, strict=True):
            durations[slot_id] = float(ticks * self.tick)
        return {slot_id: durations[slot_id] for slot_id in self.prepared.slot_ids}

    def candidate(
        self, vector: tuple[int, ...], origin: CandidateOrigin, consumes_budget: bool
    ) -> Candidate:
        ticks = {slot_id: value for (slot_id, _, _), value in zip(self.ranges, vector, strict=True)}
        key = "|".join(f"{slot_id}={value}" for slot_id, value in ticks.items())
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return Candidate(f"cand-{digest}", origin, consumes_budget, ticks, self.durations(vector))


def _space(prepared: PreparedCase) -> _Space:
    case = prepared.case
    tick = _exact(case.tick_s)
    slots = {slot.id: slot for slot in case.slots}
    ranges = tuple(
        (
            slot_id,
            math.ceil(_exact(slots[slot_id].min_s) / tick),
            math.floor(_exact(slots[slot_id].max_s) / tick),
        )
        for slot_id in prepared.variable_ids
    )
    fixed = {slot.id: slot.min_s for slot in case.slots if slot.kind == "fixed"}
    return _Space(prepared, tick, ranges, fixed)


def _first_violation(prepared: PreparedCase, durations: Mapping[str, float]) -> str | None:
    """La primera regla que viola el plan, o ``None`` si es factible.

    Una regla solo se omite si otra anterior quedó violada, así que un plan inviable siempre tiene
    al menos una violada.
    """
    result = check_plan(prepared, durations)
    return None if result.feasible else result.violated[0]


def _current_vector(
    space: _Space, current_plan: Mapping[str, float]
) -> tuple[tuple[int, ...] | None, tuple[str, ...]]:
    """El vector del plan vigente si es factible; si no, las reglas que viola."""
    result = check_plan(space.prepared, current_plan)
    if not result.feasible:
        return None, result.violated
    vector = tuple(
        math.floor(_exact(current_plan[slot_id]) / space.tick + Fraction(1, 2))
        for slot_id, _, _ in space.ranges
    )
    return vector, ()


def _draw(key: str, upper: int) -> int:
    """Entero uniforme en [0, upper) a partir de SHA-256, sin sesgo (rechazo exacto)."""
    limit = _DIGEST_SPACE - _DIGEST_SPACE % upper
    counter = 0
    while True:
        value = int.from_bytes(hashlib.sha256(f"{key}|{counter}".encode()).digest(), "big")
        if value < limit:
            return value % upper
        counter += 1  # pragma: no cover - probabilidad menor que upper / 2**256


@dataclass
class _Tally:
    """Conteos de una búsqueda mientras se hace."""

    attempts: int = 0
    duplicates: int = 0
    infeasible: int = 0
    by_rule: dict[str, int] = field(default_factory=dict[str, int])

    def reject(self, rule: str) -> None:
        self.infeasible += 1
        self.by_rule[rule] = self.by_rule.get(rule, 0) + 1


def _grid(
    space: _Space, seen: set[tuple[int, ...]], budget: int
) -> tuple[int | None, list[tuple[int, ...]] | None, _Tally]:
    """Factibles de la grilla y, si los nuevos caben en B, la lista y sus conteos.

    Devuelve ``(None, None, …)`` si la caja es mayor que ``GRID_SCAN_LIMIT``, y
    ``(factibles, None, …)`` si se recorrió pero los nuevos no caben en B.
    """
    tally = _Tally()
    if space.size > GRID_SCAN_LIMIT:
        return None, None, tally
    feasible: list[tuple[int, ...]] = []
    for vector in itertools.product(*(range(low, high + 1) for _, low, high in space.ranges)):
        tally.attempts += 1
        rule = _first_violation(space.prepared, space.durations(vector))
        if rule is None:
            feasible.append(vector)
        else:
            tally.reject(rule)
    fresh = [vector for vector in feasible if vector not in seen]
    tally.duplicates = len(feasible) - len(fresh)
    return len(feasible), (fresh if len(fresh) <= budget else None), tally


def _sample(
    space: _Space, seen: set[tuple[int, ...]], budget: int, attempt_limit: int, base: str
) -> tuple[list[tuple[int, ...]], _Tally]:
    """Muestra uniforme reproducible hasta llenar B o agotar los intentos."""
    tally = _Tally()
    accepted: list[tuple[int, ...]] = []
    while len(accepted) < budget and tally.attempts < attempt_limit:
        vector = tuple(
            low + _draw(f"{base}|{tally.attempts}|{slot_id}", high - low + 1)
            for slot_id, low, high in space.ranges
        )
        tally.attempts += 1
        if vector in seen:
            tally.duplicates += 1
            continue
        seen.add(vector)
        rule = _first_violation(space.prepared, space.durations(vector))
        if rule is None:
            accepted.append(vector)
        else:
            tally.reject(rule)
    return accepted, tally


def _seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"seed debe ser un entero, no {shown(value)!r}", "seed")
    return value


def _scenario(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid("el escenario necesita un identificador", "scenario_id")
    return value


def generate_candidates(  # noqa: PLR0913  (todos son de solo palabra clave)
    prepared: PreparedCase,
    *,
    scenario_id: str,
    budget: int,
    attempt_limit: int,
    seed: int,
    current_plan: Mapping[str, float] | None = None,
) -> CandidateSet:
    """Genera los candidatos de un escenario: grilla si cabe en B, si no muestra reproducible.

    ``current_plan`` es el plan vigente (una duración por slot del caso); si se da y es factible,
    va primero, como candidato auxiliar que no consume B.

    Raises:
        ReferenciasError: si B, el límite de intentos o la semilla no son enteros válidos, o si el
            escenario no tiene identificador.
    """
    budget = _positive_int(budget, "budget")
    attempt_limit = _positive_int(attempt_limit, "attempt_limit")
    seed = _seed(seed)
    scenario_id = _scenario(scenario_id)
    space = _space(prepared)

    candidates: list[Candidate] = []
    seen: set[tuple[int, ...]] = set()
    status: CurrentPlanStatus = "absent"
    violated: tuple[str, ...] = ()
    if current_plan is not None:
        vector, violated = _current_vector(space, current_plan)
        status = "excluded" if vector is None else "included"
        if vector is not None:
            seen.add(vector)
            candidates.append(space.candidate(vector, "current_plan", False))

    grid_feasible, grid, tally = _grid(space, seen, budget)
    method: SearchMethod = "grid"
    exhausted = False
    if grid is None:
        method = "sampling"
        base = f"{SEARCH_VERSION}|{seed}|{scenario_id}"
        sampled, tally = _sample(space, seen, budget, attempt_limit, base)
        candidates.extend(space.candidate(vector, "sampled", True) for vector in sampled)
        exhausted = len(sampled) < budget
    else:
        candidates.extend(space.candidate(vector, "grid", True) for vector in grid)

    return CandidateSet(
        scenario_id=scenario_id,
        rules_version=prepared.rules_version,
        seed=seed,
        method=method,
        budget=budget,
        attempt_limit=attempt_limit,
        space_size=space.size,
        grid_feasible=grid_feasible,
        attempts=tally.attempts,
        duplicates=tally.duplicates,
        infeasible=tally.infeasible,
        infeasible_by_rule=dict(sorted(tally.by_rule.items())),
        exhausted=exhausted,
        current_plan=status,
        current_plan_violated=violated,
        candidates=tuple(candidates),
    )
