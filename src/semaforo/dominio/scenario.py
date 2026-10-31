"""Modelo tipado del escenario (contrato ``scenario`` v1.0, DEV06 F1).

Un escenario dice qué demanda se simula sobre un caso: los flujos por movimiento, su composición,
los tiempos de calentamiento, medición y drenaje, y la semilla de la demanda. Este módulo contiene
solo reglas puras: no lee archivos ni lanza procesos (ADR01).

Reglas de estructura (mismas ideas que las del caso; ver ``semaforo.dominio.case``):

- SCEN-S01: contrato v1.0 completo, sin campos desconocidos, con tipos exactos y sin NaN ni
  infinito.
- SCEN-S02: los identificadores no están vacíos ni llevan espacios en los extremos, caracteres de
  control o caracteres invisibles.
- SCEN-S03: ``case_version`` tiene el formato ``MAYOR.MENOR.PARCHE``.

Reglas de consistencia con el caso (acta ``2026-10-31-dev06-f0-decisiones``, D16):

- SCEN-C01: el escenario y su solicitud son del mismo caso y versión que el caso, y el origen del
  escenario (``synthetic`` o ``field_derived``) corresponde al de su solicitud (``synthetic`` o
  ``field``). El origen del escenario es el de la demanda, no el del caso: una demanda sintética
  puede ejecutarse sobre un caso de campo.
- SCEN-C02: todos los movimientos del caso tienen una fila de demanda, una sola, y no hay filas de
  movimientos que el caso no tiene. Una fila ausente no es un cero.
- SCEN-C03: las clases de la composición existen en el caso, cada proporción está entre 0 y 1 y
  suman 1. La composición solo puede faltar si el flujo es cero. Una clase que no se nombra tiene
  proporción 0.
- SCEN-C04: el flujo de cada movimiento está dentro del dominio de flujos del caso.
- SCEN-C05: la ventana de observación de la solicitud tiene instantes ISO 8601 con zona horaria y
  el fin es posterior al inicio; el calentamiento, la medición y el drenaje son múltiplos del tick
  del caso.
- SCEN-C06: la política de frontera es la del caso.

Los problemas se informan todos juntos, cada uno con su regla, su campo y su motivo.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import Field, ValidationError

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import (
    Artifact,
    Case,
    CaseIssue,
    Identifier,
    Version,
    cap_issues,
    issues_of,
)
from semaforo.dominio.case_rules import EPSILON, TICK_EPSILON
from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "DemandRow",
    "Request",
    "Scenario",
    "ScenarioInvalidError",
    "accept_scenario",
    "parse_scenario",
    "scenario_issues",
]

ORIGINS_OF_REQUEST = {"synthetic": "synthetic", "field_derived": "field"}


class DemandRow(FrozenModel):
    """Flujo pedido para un movimiento y proporción de cada clase de vehículo."""

    movement_id: Identifier
    flow_vph: float = Field(ge=0)
    composition: dict[str, float] | None


class Request(FrozenModel):
    """Solicitud de la que sale el escenario (contrato ``request`` v1.0)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    request_id: Identifier
    case_id: Identifier
    case_version: Version
    origin: Literal["synthetic", "field"]
    observation_start: str = Field(json_schema_extra={"format": "date-time"})
    observation_end: str = Field(json_schema_extra={"format": "date-time"})
    source_ids: list[Identifier] = Field(min_length=1)
    demand: list[DemandRow] = Field(min_length=1)


class Scenario(FrozenModel):
    """Escenario versionado (contrato ``scenario`` v1.0)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    scenario_id: Identifier
    case_id: Identifier
    case_version: Version
    origin: Literal["synthetic", "field_derived"]
    group_id: Identifier
    source_ids: list[Identifier]
    request: Request
    boundary_policy_id: Identifier
    warmup_s: float = Field(ge=0)
    measure_s: float = Field(gt=0)
    drain_max_s: float = Field(ge=0)
    demand_seed: int = Field(ge=0)
    demand_artifact: Artifact | None


class ScenarioInvalidError(DomainError):
    """El escenario no cumple el contrato o no encaja con el caso. Lleva todos los problemas.

    El código es INPUT_SCHEMA, que la CLI traduce al código de salida 2.
    """

    def __init__(self, issues: Sequence[CaseIssue]) -> None:
        if not issues:
            raise ValueError("un escenario inválido tiene al menos un problema")
        first = issues[0]
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        where = "" if first.field is None else f" en {first.field}"
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"el escenario no es válido: {first.rule_id}{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


def parse_scenario(data: object) -> Scenario:
    """Valida ``data`` (el contenido ya leído del JSON) y devuelve el escenario.

    Raises:
        ScenarioInvalidError: si no cumple el contrato, con todos los problemas encontrados.
    """
    try:
        return Scenario.model_validate(data)
    except ValidationError as error:
        raise ScenarioInvalidError(
            [
                CaseIssue(issue.rule_id.replace("CASE-", "SCEN-", 1), issue.field, issue.message)
                for issue in issues_of(error)
            ]
        ) from None


def accept_scenario(data: object, case: Case) -> Scenario:
    """Valida ``data`` y comprueba que encaja con ``case``.

    Raises:
        ScenarioInvalidError: si falla el contrato o alguna regla de consistencia.
    """
    scenario = parse_scenario(data)
    issues = scenario_issues(scenario, case)
    if issues:
        raise ScenarioInvalidError(cap_issues(issues))
    return scenario


def scenario_issues(scenario: Scenario, case: Case) -> list[CaseIssue]:
    """Problemas de consistencia del escenario con el caso, en orden fijo (SCEN-C01 a C06)."""
    return [
        *_same_case(scenario, case),
        *_demand_rows(scenario, case),
        *_compositions(scenario, case),
        *_flow_domains(scenario, case),
        *_times(scenario, case),
        *_boundary(scenario, case),
    ]


def _n(value: float) -> str:
    return f"{value:g}"


def _same_case(scenario: Scenario, case: Case) -> list[CaseIssue]:
    """SCEN-C01: caso y versión coinciden en el escenario, su solicitud y el caso; el origen del
    escenario coincide con el de su solicitud."""
    request = scenario.request
    issues: list[CaseIssue] = []
    for prefix, case_id, case_version in (
        ("", scenario.case_id, scenario.case_version),
        ("request.", request.case_id, request.case_version),
    ):
        checks = (
            ("case_id", case_id, case.case_id, "el caso"),
            ("case_version", case_version, case.case_version, "la versión del caso"),
        )
        issues.extend(
            CaseIssue(
                "SCEN-C01",
                f"{prefix}{name}",
                f"{label} es «{expected}» y el escenario dice «{actual}»",
            )
            for name, actual, expected, label in checks
            if actual != expected
        )
    if ORIGINS_OF_REQUEST[scenario.origin] != request.origin:
        issues.append(
            CaseIssue(
                "SCEN-C01",
                "request.origin",
                f"el escenario es «{scenario.origin}» y su solicitud dice «{request.origin}»",
            )
        )
    return issues


def _demand_rows(scenario: Scenario, case: Case) -> list[CaseIssue]:
    """SCEN-C02: una fila de demanda por cada movimiento del caso y ninguna de más."""
    issues: list[CaseIssue] = []
    known = {movement.id for movement in case.movements}
    seen: set[str] = set()
    for index, row in enumerate(scenario.request.demand):
        field = f"request.demand[{index}].movement_id"
        if row.movement_id not in known:
            issues.append(
                CaseIssue("SCEN-C02", field, f"el caso no tiene el movimiento «{row.movement_id}»")
            )
        elif row.movement_id in seen:
            issues.append(
                CaseIssue("SCEN-C02", field, f"el movimiento «{row.movement_id}» está repetido")
            )
        seen.add(row.movement_id)
    issues.extend(
        CaseIssue(
            "SCEN-C02",
            "request.demand",
            f"falta la demanda del movimiento «{movement.id}» (una fila ausente no es un cero)",
        )
        for movement in case.movements
        if movement.id not in seen
    )
    return issues


def _compositions(scenario: Scenario, case: Case) -> list[CaseIssue]:
    """SCEN-C03: composición con clases del caso, proporciones válidas y suma 1."""
    issues: list[CaseIssue] = []
    classes = set(case.vehicle_classes)
    for index, row in enumerate(scenario.request.demand):
        field = f"request.demand[{index}].composition"
        if row.composition is None:
            if row.flow_vph > 0:
                issues.append(
                    CaseIssue(
                        "SCEN-C03",
                        field,
                        f"falta la composición del movimiento «{row.movement_id}», "
                        f"que tiene flujo {_n(row.flow_vph)}",
                    )
                )
            continue
        for name, share in row.composition.items():
            if name not in classes:
                issues.append(
                    CaseIssue("SCEN-C03", field, f"el caso no tiene la clase de vehículo «{name}»")
                )
            if share < -EPSILON or share > 1 + EPSILON:
                issues.append(
                    CaseIssue(
                        "SCEN-C03",
                        f"{field}.{name}",
                        f"la proporción {_n(share)} debe estar entre 0 y 1",
                    )
                )
        total = sum(row.composition.values())
        if abs(total - 1) > EPSILON:
            issues.append(
                CaseIssue("SCEN-C03", field, f"las proporciones suman {_n(total)} y deben sumar 1")
            )
    return issues


def _flow_domains(scenario: Scenario, case: Case) -> list[CaseIssue]:
    """SCEN-C04: el flujo está dentro del dominio de flujos del movimiento."""
    domains = {movement.id: movement.flow_domain_vph for movement in case.movements}
    issues: list[CaseIssue] = []
    for index, row in enumerate(scenario.request.demand):
        domain = domains.get(row.movement_id)
        if domain is None:
            continue
        if row.flow_vph < domain.min - EPSILON or row.flow_vph > domain.max + EPSILON:
            issues.append(
                CaseIssue(
                    "SCEN-C04",
                    f"request.demand[{index}].flow_vph",
                    f"el flujo {_n(row.flow_vph)} queda fuera del dominio del movimiento "
                    f"«{row.movement_id}»: de {_n(domain.min)} a {_n(domain.max)} veh/h",
                )
            )
    return issues


def _instant(text: str) -> datetime | None:
    """El instante ISO 8601 con zona horaria, o None si no lo es."""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _aligned(value: float, tick: float) -> bool:
    """``value`` es múltiplo entero de ``tick`` (tolerancia relativa para valores grandes)."""
    ratio = value / tick
    return abs(ratio - round(ratio)) <= TICK_EPSILON * max(1.0, abs(ratio))


def _times(scenario: Scenario, case: Case) -> list[CaseIssue]:
    """SCEN-C05: ventana de observación válida y tiempos alineados con el tick."""
    issues: list[CaseIssue] = []
    request = scenario.request
    start = _instant(request.observation_start)
    end = _instant(request.observation_end)
    for field, text, moment in (
        ("request.observation_start", request.observation_start, start),
        ("request.observation_end", request.observation_end, end),
    ):
        if moment is None:
            issues.append(
                CaseIssue(
                    "SCEN-C05",
                    field,
                    f"«{text}» no es un instante ISO 8601 con zona horaria, "
                    "por ejemplo 2026-10-18T08:00:00-05:00",
                )
            )
    if start is not None and end is not None and end <= start:
        issues.append(
            CaseIssue(
                "SCEN-C05",
                "request.observation_end",
                "el fin de la observación debe ser posterior a su inicio",
            )
        )
    for field, value in (
        ("warmup_s", scenario.warmup_s),
        ("measure_s", scenario.measure_s),
        ("drain_max_s", scenario.drain_max_s),
    ):
        if not _aligned(value, case.tick_s):
            issues.append(
                CaseIssue(
                    "SCEN-C05",
                    field,
                    f"{_n(value)} s no es múltiplo del tick del caso ({_n(case.tick_s)} s)",
                )
            )
    return issues


def _boundary(scenario: Scenario, case: Case) -> list[CaseIssue]:
    """SCEN-C06: la política de frontera del escenario es la del caso."""
    if scenario.boundary_policy_id == case.boundary_policy_id:
        return []
    return [
        CaseIssue(
            "SCEN-C06",
            "boundary_policy_id",
            f"el caso usa «{case.boundary_policy_id}» y el escenario dice "
            f"«{scenario.boundary_policy_id}»",
        )
    ]
