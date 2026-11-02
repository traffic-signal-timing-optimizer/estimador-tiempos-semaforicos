"""Generación repetible de escenarios controlados (DEV11 F2, HU06; decisiones D5 y D6 de F0).

Dado un caso, una especificación (``semaforo.dominio.scenario_spec``) y una semilla maestra, produce
la lista de escenarios del conjunto. No lee ni escribe archivos: es una función pura, así que
**la misma especificación y la misma semilla dan siempre los mismos escenarios, byte a byte**.

- **Perturbaciones.** Cada familia tiene ``variants`` perturbaciones: vectores de flujo distintos,
  cada uno dentro de los rangos de la familia. El flujo de un movimiento sale de un generador
  derivado con SHA-256 del texto ``<semilla>|flujo|<familia>|<perturbación>|<movimiento>``: se toma
  un valor uniforme entre el mínimo y el máximo, se redondea a 0.1 veh/h y se deja dentro del rango.
  Un rango de un solo valor da ese valor.
- **Semillas.** Cada perturbación se repite ``seeds`` veces con las mismas cifras de flujo y otra
  ``demand_seed``: 31 bits del SHA-256 de
  ``<semilla>|semilla|<familia>|<perturbación>|<repetición>|<intento>``, con ``intento`` desde 0
  hasta que no se repita dentro de la familia. Las repeticiones cambian las llegadas, no la
  demanda.
- **Familia = grupo.** Todos los escenarios de una familia llevan ``group_id = family_id``, con el
  origen, la ventana, los tiempos y las fuentes de la especificación, y la política de frontera del
  caso. Las perturbaciones nunca salen de su familia.
- **Independencia.** Cada familia usa solo su propio nombre en las derivaciones: agregar, quitar o
  reordenar otras familias no cambia sus escenarios.
- **Nombres.** ``<familia>-V<nn>-S<nn>`` (perturbación y repetición con ceros a la izquierda, al
  menos dos cifras).

Cada escenario generado se valida con las reglas SCEN-C01 a SCEN-C06; si alguna falla, es un
defecto del generador y se informa con el error de escenario.
"""

import hashlib
import random
from dataclasses import dataclass

from semaforo.dominio.case import Case, cap_issues
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import (
    DemandRow,
    Request,
    Scenario,
    ScenarioInvalidError,
    scenario_issues,
)
from semaforo.dominio.scenario_spec import (
    Family,
    FamilyRow,
    ScenarioSpec,
    SpecInvalidError,
    spec_issues,
)

__all__ = [
    "MAX_SEED",
    "GeneratedScenario",
    "demand_seed_for",
    "derivation_digest",
    "flow_for",
    "generate_scenarios",
]

MAX_SEED = 2**63 - 1
FLOW_DECIMALS = 1
DEMAND_SEED_MASK = 0x7FFFFFFF
DEMAND_SEED_BYTES = 4
MIN_WIDTH = 2


@dataclass(frozen=True)
class GeneratedScenario:
    """Un escenario del conjunto y de dónde salió.

    ``variant`` y ``repetition`` cuentan desde 1. ``flows`` son los flujos usados (veh/h) por
    movimiento: sirven para dejar los rangos trazables en el manifiesto.
    """

    scenario: Scenario
    family_id: str
    variant: int
    repetition: int
    flows: dict[str, float]


def derivation_digest(text: str) -> bytes:
    """Huella SHA-256 del texto de derivación (flujo o semilla), base de todo el azar."""
    return hashlib.sha256(text.encode("utf-8")).digest()


def flow_for(seed: int, family_id: str, variant: int, row: FamilyRow) -> float:
    """Flujo (veh/h) de un movimiento en una perturbación de una familia, dentro de su rango."""
    low, high = row.flow_vph.min, row.flow_vph.max
    if low == high:
        return float(low)
    stream = random.Random(  # noqa: S311 - simulación, no seguridad
        int.from_bytes(
            derivation_digest(f"{seed}|flujo|{family_id}|{variant}|{row.movement_id}"), "big"
        )
    )
    value = round(low + (high - low) * stream.random(), FLOW_DECIMALS)
    return min(max(value, low), high)


def demand_seed_for(
    seed: int, family_id: str, variant: int, repetition: int, taken: frozenset[int]
) -> int:
    """Semilla de la demanda de una repetición, distinta de las ya usadas en ``taken``."""
    attempt = 0
    while True:
        digest = derivation_digest(f"{seed}|semilla|{family_id}|{variant}|{repetition}|{attempt}")
        candidate = int.from_bytes(digest[:DEMAND_SEED_BYTES], "big") & DEMAND_SEED_MASK
        if candidate not in taken:
            return candidate
        attempt += 1


def generate_scenarios(spec: ScenarioSpec, case: Case, seed: int) -> tuple[GeneratedScenario, ...]:
    """Los escenarios de la especificación sobre el caso, en el orden de familia, perturbación y
    repetición.

    Raises:
        DomainError: INPUT_SCHEMA si la semilla no es un entero de 0 a ``MAX_SEED``.
        SpecInvalidError: si la especificación no encaja con el caso.
        ScenarioInvalidError: si un escenario generado no cumple las reglas (defecto del generador).
    """
    if not 0 <= seed <= MAX_SEED:
        raise DomainError(
            ErrorCode.INPUT_SCHEMA,
            f"la semilla debe ser un entero de 0 a {MAX_SEED} y es {seed}",
            "seed",
        )
    issues = spec_issues(spec, case)
    if issues:
        raise SpecInvalidError(cap_issues(issues))
    members: list[GeneratedScenario] = []
    for family in spec.families:
        members.extend(_family_scenarios(spec, case, family, seed))
    return tuple(members)


def _family_scenarios(
    spec: ScenarioSpec, case: Case, family: Family, seed: int
) -> list[GeneratedScenario]:
    variant_width = max(MIN_WIDTH, len(str(family.variants)))
    repetition_width = max(MIN_WIDTH, len(str(family.seeds)))
    members: list[GeneratedScenario] = []
    taken: set[int] = set()
    for variant in range(1, family.variants + 1):
        flows = {
            row.movement_id: flow_for(seed, family.family_id, variant, row) for row in family.demand
        }
        for repetition in range(1, family.seeds + 1):
            demand_seed = demand_seed_for(
                seed, family.family_id, variant, repetition, frozenset(taken)
            )
            taken.add(demand_seed)
            name = (
                f"{family.family_id}-V{variant:0{variant_width}d}"
                f"-S{repetition:0{repetition_width}d}"
            )
            scenario = _scenario(spec, case, family, name, _Draw(flows, demand_seed))
            problems = scenario_issues(scenario, case)
            if problems:
                raise ScenarioInvalidError(cap_issues(problems))
            members.append(
                GeneratedScenario(scenario, family.family_id, variant, repetition, flows)
            )
    return members


@dataclass(frozen=True)
class _Draw:
    """Lo que se sortea para un escenario: los flujos de la perturbación y la semilla."""

    flows: dict[str, float]
    demand_seed: int


def _scenario(
    spec: ScenarioSpec, case: Case, family: Family, scenario_id: str, draw: _Draw
) -> Scenario:
    request = Request(
        request_id=f"{scenario_id}-REQ",
        case_id=spec.case_id,
        case_version=spec.case_version,
        origin="synthetic" if spec.origin == "synthetic" else "field",
        observation_start=spec.observation_start,
        observation_end=spec.observation_end,
        source_ids=list(spec.source_ids),
        demand=[
            DemandRow(
                movement_id=row.movement_id,
                flow_vph=draw.flows[row.movement_id],
                composition=None if row.composition is None else dict(row.composition),
            )
            for row in family.demand
        ],
    )
    return Scenario(
        scenario_id=scenario_id,
        case_id=spec.case_id,
        case_version=spec.case_version,
        origin=spec.origin,
        group_id=family.family_id,
        source_ids=list(spec.source_ids),
        request=request,
        boundary_policy_id=case.boundary_policy_id,
        warmup_s=spec.warmup_s,
        measure_s=spec.measure_s,
        drain_max_s=spec.drain_max_s,
        demand_seed=draw.demand_seed,
        demand_artifact=None,
    )
