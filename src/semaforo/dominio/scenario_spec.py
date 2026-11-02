"""Especificación de escenarios con rangos explícitos (DEV11 F1, HU06; decisiones D3 a D7 de F0).

Una especificación dice qué conjunto de escenarios generar sobre un caso: la ventana de tiempos y,
por cada **familia** (un patrón de demanda), el rango de flujo de cada movimiento, su composición
por clase y cuántas perturbaciones y semillas se piden. No es un contrato publicado (el paquete de
contratos fija nueve): es un archivo de entrada con ``schema_version`` y este modelo estricto,
como las rutas y los tipos de vehículo. Este módulo contiene solo reglas puras: no lee archivos ni
lanza procesos (ADR01).

Reglas de estructura:

- SPEC-S01: contrato v1.0 completo, sin campos desconocidos, con tipos exactos y sin NaN ni
  infinito.
- SPEC-S02: los identificadores no están vacíos ni llevan espacios en los extremos, caracteres de
  control o caracteres invisibles; ``spec_id`` y ``family_id`` además solo llevan letras, números,
  guion bajo y guion (hasta 32 caracteres, sin empezar por guion) porque dan nombre a archivos; y
  las familias no se repiten.
- SPEC-S03: ``case_version`` tiene el formato ``MAYOR.MENOR.PARCHE``.

Reglas de consistencia con el caso:

- SPEC-C01: el caso y su versión son los de la especificación.
- SPEC-C02: cada familia tiene una fila por cada movimiento del caso, una sola, y ninguna de
  movimientos que el caso no tiene. Una fila ausente no es un cero.
- SPEC-C03: cada rango va de un mínimo a un máximo (``min <= max``) y queda dentro del dominio de
  flujos del movimiento.
- SPEC-C04: la composición usa clases del caso, cada proporción está entre 0 y 1 y suman 1. Solo
  puede faltar si el rango del movimiento es de 0 a 0.
- SPEC-C05: cantidades dentro de los máximos: perturbaciones y semillas por familia, y escenarios
  en total.

Los tiempos (ventana de observación y múltiplos del tick) se revisan con la regla SCEN-C05 del
escenario, que es la misma que verá cada escenario generado. Los problemas se informan todos
juntos, cada uno con su regla, su campo y su motivo.
"""

import re
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, ValidationError
from pydantic_core import PydanticCustomError

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import (
    Case,
    CaseIssue,
    Identifier,
    Version,
    cap_issues,
    issues_of,
)
from semaforo.dominio.case_rules import EPSILON
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import DemandRow, Request, Scenario, scenario_issues

__all__ = [
    "MAX_SCENARIOS",
    "MAX_SEEDS",
    "MAX_VARIANTS",
    "Family",
    "FamilyRow",
    "FlowRange",
    "ScenarioSpec",
    "SpecInvalidError",
    "accept_spec",
    "parse_spec",
    "scenario_count",
    "spec_issues",
]

MAX_VARIANTS = 200
MAX_SEEDS = 100
MAX_SCENARIOS = 2000
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}")
TIMES_RULE = "SCEN-C05"


def _safe_id(value: str) -> str:
    """Solo letras, números, guion bajo y guion, hasta 32 caracteres y sin empezar por guion."""
    if SAFE_ID.fullmatch(value) is None:
        raise PydanticCustomError(
            "spec_s02",
            "el identificador solo puede tener letras, números, guion bajo y guion, hasta 32 "
            "caracteres, y no puede empezar por guion o guion bajo",
        )
    return value


def _sorted_composition(value: dict[str, float] | None) -> dict[str, float] | None:
    """La composición con sus clases en orden alfabético: el orden en que se escribieron no
    cambia los bytes de lo que se genera."""
    return None if value is None else dict(sorted(value.items()))


SafeId = Annotated[str, AfterValidator(_safe_id)]
Composition = Annotated[dict[str, float] | None, AfterValidator(_sorted_composition)]


class FlowRange(FrozenModel):
    """Rango de flujo de un movimiento en una familia, en veh/h."""

    min: float = Field(ge=0)
    max: float = Field(ge=0)


class FamilyRow(FrozenModel):
    """Rango de flujo y composición por clase de un movimiento en una familia."""

    movement_id: Identifier
    flow_vph: FlowRange
    composition: Composition


class Family(FrozenModel):
    """Un patrón de demanda. ``variants`` perturbaciones (flujos distintos dentro de los rangos),
    cada una con ``seeds`` semillas (las mismas cifras con otras llegadas)."""

    family_id: SafeId
    variants: int = Field(ge=1)
    seeds: int = Field(ge=1)
    demand: list[FamilyRow] = Field(min_length=1)


class ScenarioSpec(FrozenModel):
    """Especificación de un conjunto de escenarios (``schema_version`` 1.0.0)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    spec_id: SafeId
    case_id: Identifier
    case_version: Version
    origin: Literal["synthetic", "field_derived"]
    source_ids: list[Identifier] = Field(min_length=1)
    observation_start: str = Field(json_schema_extra={"format": "date-time"})
    observation_end: str = Field(json_schema_extra={"format": "date-time"})
    warmup_s: float = Field(ge=0)
    measure_s: float = Field(gt=0)
    drain_max_s: float = Field(ge=0)
    families: list[Family] = Field(min_length=1)


class SpecInvalidError(DomainError):
    """La especificación no cumple el contrato o no encaja con el caso. Lleva todos los problemas.

    El código es INPUT_SCHEMA, que la CLI traduce al código de salida 2.
    """

    def __init__(self, issues: Sequence[CaseIssue]) -> None:
        if not issues:
            raise ValueError("una especificación inválida tiene al menos un problema")
        first = issues[0]
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        where = "" if first.field is None else f" en {first.field}"
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"la especificación no es válida: {first.rule_id}{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


def scenario_count(spec: ScenarioSpec) -> int:
    """Cuántos escenarios genera la especificación: perturbaciones por semillas, por familia."""
    return sum(family.variants * family.seeds for family in spec.families)


def parse_spec(data: object) -> ScenarioSpec:
    """Valida ``data`` (el contenido ya leído del JSON) y devuelve la especificación.

    Raises:
        SpecInvalidError: si no cumple el contrato, con todos los problemas encontrados.
    """
    try:
        return ScenarioSpec.model_validate(data)
    except ValidationError as error:
        raise SpecInvalidError(
            [
                CaseIssue(issue.rule_id.replace("CASE-", "SPEC-", 1), issue.field, issue.message)
                for issue in issues_of(error)
            ]
        ) from None


def accept_spec(data: object, case: Case) -> ScenarioSpec:
    """Valida ``data`` y comprueba que encaja con ``case``.

    Raises:
        SpecInvalidError: si falla el contrato o alguna regla de consistencia.
    """
    spec = parse_spec(data)
    issues = spec_issues(spec, case)
    if issues:
        raise SpecInvalidError(cap_issues(issues))
    return spec


def spec_issues(spec: ScenarioSpec, case: Case) -> list[CaseIssue]:
    """Problemas de la especificación con el caso, en orden fijo."""
    return [
        *_same_case(spec, case),
        *_family_ids(spec),
        *_families(spec, case),
        *_sizes(spec),
        *_times(spec, case),
    ]


def _n(value: float) -> str:
    return f"{value:g}"


def _same_case(spec: ScenarioSpec, case: Case) -> list[CaseIssue]:
    """SPEC-C01: el caso y su versión coinciden."""
    checks = (
        ("case_id", spec.case_id, case.case_id, "el caso"),
        ("case_version", spec.case_version, case.case_version, "la versión del caso"),
    )
    return [
        CaseIssue("SPEC-C01", name, f"{label} es «{expected}» y la especificación dice «{actual}»")
        for name, actual, expected, label in checks
        if actual != expected
    ]


def _family_ids(spec: ScenarioSpec) -> list[CaseIssue]:
    """SPEC-S02: las familias no se repiten."""
    seen: set[str] = set()
    issues: list[CaseIssue] = []
    for index, family in enumerate(spec.families):
        if family.family_id in seen:
            issues.append(
                CaseIssue(
                    "SPEC-S02",
                    f"families[{index}].family_id",
                    f"la familia «{family.family_id}» está repetida",
                )
            )
        seen.add(family.family_id)
    return issues


def _families(spec: ScenarioSpec, case: Case) -> list[CaseIssue]:
    """SPEC-C02 a SPEC-C05 de cada familia, en el orden de la especificación."""
    issues: list[CaseIssue] = []
    for index, family in enumerate(spec.families):
        issues.extend(_coverage(family, index, case))
        issues.extend(_ranges(family, index, case))
        issues.extend(_compositions(family, index, case))
        issues.extend(_counts(family, index))
    return issues


def _coverage(family: Family, index: int, case: Case) -> list[CaseIssue]:
    """SPEC-C02: una fila por cada movimiento del caso y ninguna de más."""
    known = {movement.id for movement in case.movements}
    seen: set[str] = set()
    issues: list[CaseIssue] = []
    for position, row in enumerate(family.demand):
        field = f"families[{index}].demand[{position}].movement_id"
        if row.movement_id not in known:
            issues.append(
                CaseIssue("SPEC-C02", field, f"el caso no tiene el movimiento «{row.movement_id}»")
            )
        elif row.movement_id in seen:
            issues.append(
                CaseIssue("SPEC-C02", field, f"el movimiento «{row.movement_id}» está repetido")
            )
        seen.add(row.movement_id)
    issues.extend(
        CaseIssue(
            "SPEC-C02",
            f"families[{index}].demand",
            f"falta el rango del movimiento «{movement.id}» (una fila ausente no es un cero)",
        )
        for movement in case.movements
        if movement.id not in seen
    )
    return issues


def _ranges(family: Family, index: int, case: Case) -> list[CaseIssue]:
    """SPEC-C03: ``min <= max`` y dentro del dominio de flujos del movimiento."""
    domains = {movement.id: movement.flow_domain_vph for movement in case.movements}
    issues: list[CaseIssue] = []
    for position, row in enumerate(family.demand):
        field = f"families[{index}].demand[{position}].flow_vph"
        low, high = row.flow_vph.min, row.flow_vph.max
        if low > high:
            issues.append(
                CaseIssue(
                    "SPEC-C03",
                    field,
                    f"el mínimo {_n(low)} es mayor que el máximo {_n(high)}",
                )
            )
        domain = domains.get(row.movement_id)
        if domain is not None and (low < domain.min - EPSILON or high > domain.max + EPSILON):
            issues.append(
                CaseIssue(
                    "SPEC-C03",
                    field,
                    f"el rango de {_n(low)} a {_n(high)} veh/h sale del dominio del movimiento "
                    f"«{row.movement_id}»: de {_n(domain.min)} a {_n(domain.max)} veh/h",
                )
            )
    return issues


def _compositions(family: Family, index: int, case: Case) -> list[CaseIssue]:
    """SPEC-C04: clases del caso, proporciones entre 0 y 1 que suman 1."""
    classes = set(case.vehicle_classes)
    issues: list[CaseIssue] = []
    for position, row in enumerate(family.demand):
        field = f"families[{index}].demand[{position}].composition"
        if row.composition is None:
            if row.flow_vph.max > 0:
                issues.append(
                    CaseIssue(
                        "SPEC-C04",
                        field,
                        f"falta la composición del movimiento «{row.movement_id}», cuyo flujo "
                        f"puede llegar a {_n(row.flow_vph.max)} veh/h",
                    )
                )
            continue
        for name, share in row.composition.items():
            if name not in classes:
                issues.append(
                    CaseIssue("SPEC-C04", field, f"el caso no tiene la clase de vehículo «{name}»")
                )
            if share < -EPSILON or share > 1 + EPSILON:
                issues.append(
                    CaseIssue(
                        "SPEC-C04",
                        f"{field}.{name}",
                        f"la proporción {_n(share)} debe estar entre 0 y 1",
                    )
                )
        total = sum(row.composition.values())
        if abs(total - 1) > EPSILON:
            issues.append(
                CaseIssue("SPEC-C04", field, f"las proporciones suman {_n(total)} y deben sumar 1")
            )
    return issues


def _counts(family: Family, index: int) -> list[CaseIssue]:
    """SPEC-C05: perturbaciones y semillas dentro de los máximos."""
    issues: list[CaseIssue] = []
    if family.variants > MAX_VARIANTS:
        issues.append(
            CaseIssue(
                "SPEC-C05",
                f"families[{index}].variants",
                f"pide {family.variants} perturbaciones y el máximo es {MAX_VARIANTS}",
            )
        )
    if family.seeds > MAX_SEEDS:
        issues.append(
            CaseIssue(
                "SPEC-C05",
                f"families[{index}].seeds",
                f"pide {family.seeds} semillas y el máximo es {MAX_SEEDS}",
            )
        )
    return issues


def _sizes(spec: ScenarioSpec) -> list[CaseIssue]:
    """SPEC-C05: escenarios en total dentro del máximo."""
    total = scenario_count(spec)
    if total <= MAX_SCENARIOS:
        return []
    return [
        CaseIssue(
            "SPEC-C05",
            "families",
            f"la especificación genera {total} escenarios y el máximo es {MAX_SCENARIOS}",
        )
    ]


def _times(spec: ScenarioSpec, case: Case) -> list[CaseIssue]:
    """Ventana de observación y múltiplos del tick: la regla SCEN-C05 del escenario.

    Se arma un escenario de prueba con los tiempos de la especificación y se conserva solo lo que
    dice SCEN-C05, así la regla es la misma que verá cada escenario generado.
    """
    origin: Literal["synthetic", "field"] = "synthetic" if spec.origin == "synthetic" else "field"
    probe = Scenario(
        scenario_id="probe",
        case_id=spec.case_id,
        case_version=spec.case_version,
        origin=spec.origin,
        group_id="probe",
        source_ids=list(spec.source_ids),
        request=Request(
            request_id="probe",
            case_id=spec.case_id,
            case_version=spec.case_version,
            origin=origin,
            observation_start=spec.observation_start,
            observation_end=spec.observation_end,
            source_ids=list(spec.source_ids),
            demand=[DemandRow(movement_id=case.movements[0].id, flow_vph=0.0, composition=None)],
        ),
        boundary_policy_id=case.boundary_policy_id,
        warmup_s=spec.warmup_s,
        measure_s=spec.measure_s,
        drain_max_s=spec.drain_max_s,
        demand_seed=0,
        demand_artifact=None,
    )
    return [
        CaseIssue(
            issue.rule_id,
            None if issue.field is None else issue.field.removeprefix("request."),
            issue.message,
        )
        for issue in scenario_issues(probe, case)
        if issue.rule_id == TIMES_RULE
    ]
