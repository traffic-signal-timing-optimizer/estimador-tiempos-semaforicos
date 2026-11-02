"""Modelo de la partición y sus reglas (contrato ``split`` v1.0, DEV12 F1; decisiones D3 a D7).

Una partición dice a cuál de las tres partes (entrenamiento, validación o prueba) va cada
escenario. La unidad es la **familia completa**: el ``group_id`` de los escenarios. Este módulo
contiene solo reglas puras: no lee archivos ni lanza procesos (ADR01).

Reglas de estructura:

- SPLIT-S01: contrato v1.0 completo, sin campos desconocidos, con tipos exactos y sin NaN ni
  infinito.
- SPLIT-S02: los identificadores no están vacíos ni llevan espacios en los extremos, caracteres de
  control o caracteres invisibles.

Reglas de consistencia con los escenarios del conjunto:

- SPLIT-C01: cada escenario del conjunto está asignado una vez, y no hay asignaciones de
  escenarios que el conjunto no tiene.
- SPLIT-C02: un grupo está en una sola partición (no se puede mezclar una variante de una familia
  con otra partición).
- SPLIT-C03: el grupo de cada asignación es el del escenario.
- SPLIT-C04: las tres particiones tienen al menos un grupo.
- SPLIT-C05: la partición está congelada (``frozen``).
- SPLIT-C06: procedencia compartida: dos escenarios derivados de campo de particiones distintas no
  comparten fuente.

Reglas de la política (archivo de proporciones):

- SPLIT-P01: las proporciones de grupos de entrenamiento, validación y prueba están entre 0 y 1
  (sin incluirlos) y suman 1.

Los problemas se informan todos juntos, cada uno con su regla, su campo y su motivo.
"""

from collections.abc import Sequence
from typing import Literal

from pydantic import Field, ValidationError

from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import CaseIssue, Identifier, cap_issues, issues_of
from semaforo.dominio.case_rules import EPSILON
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import Scenario
from semaforo.dominio.scenario_spec import SafeId

__all__ = [
    "PARTITIONS",
    "Assignment",
    "Partition",
    "Proportions",
    "Split",
    "SplitInvalidError",
    "SplitPolicy",
    "accept_split",
    "parse_policy",
    "parse_split",
    "split_issues",
    "split_self_issues",
]

Partition = Literal["train", "validation", "test"]
PARTITIONS: tuple[Partition, ...] = ("train", "validation", "test")


class Assignment(FrozenModel):
    """A qué partición va un escenario y de qué grupo (familia) es."""

    scenario_id: Identifier
    group_id: Identifier
    partition: Partition


class Split(FrozenModel):
    """Partición versionada (contrato ``split`` v1.0)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    split_id: Identifier
    policy: str
    seed: int = Field(ge=0)
    frozen: bool
    assignments: list[Assignment] = Field(min_length=1)


class Proportions(FrozenModel):
    """Proporción de los grupos que va a cada partición."""

    train: float = Field(gt=0, lt=1)
    validation: float = Field(gt=0, lt=1)
    test: float = Field(gt=0, lt=1)


class SplitPolicy(FrozenModel):
    """Política de partición (archivo de entrada, ``schema_version`` 1.0.0).

    ``provisional`` dice que las proporciones no están aprobadas todavía (DEC07 pendiente).
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_id: SafeId
    proportions: Proportions
    provisional: bool = False


class SplitInvalidError(DomainError):
    """La partición, la política o la asignación no son válidas. Lleva todos los problemas.

    El código es INPUT_SCHEMA, que la CLI traduce al código de salida 2.
    """

    def __init__(self, issues: Sequence[CaseIssue]) -> None:
        if not issues:
            raise ValueError("una partición inválida tiene al menos un problema")
        first = issues[0]
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        where = "" if first.field is None else f" en {first.field}"
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"la partición no es válida: {first.rule_id}{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


def _structure_issues(error: ValidationError) -> list[CaseIssue]:
    return [
        CaseIssue(
            issue.rule_id.replace("CASE-", "SPLIT-", 1).replace("SPEC-", "SPLIT-", 1),
            issue.field,
            issue.message,
        )
        for issue in issues_of(error)
    ]


def parse_split(data: object) -> Split:
    """Valida ``data`` (el contenido ya leído del JSON) y devuelve la partición.

    Raises:
        SplitInvalidError: si no cumple el contrato, con todos los problemas encontrados.
    """
    try:
        return Split.model_validate(data)
    except ValidationError as error:
        raise SplitInvalidError(_structure_issues(error)) from None


def parse_policy(data: object) -> SplitPolicy:
    """Valida ``data`` como política: contrato, proporciones entre 0 y 1 y suma 1.

    Raises:
        SplitInvalidError: con todos los problemas encontrados.
    """
    try:
        policy = SplitPolicy.model_validate(data)
    except ValidationError as error:
        raise SplitInvalidError(_structure_issues(error)) from None
    p = policy.proportions
    total = p.train + p.validation + p.test
    if abs(total - 1) > EPSILON:
        raise SplitInvalidError(
            [
                CaseIssue(
                    "SPLIT-P01",
                    "proportions",
                    f"las proporciones suman {total:g} y deben sumar 1",
                )
            ]
        )
    return policy


def accept_split(data: object, scenarios: Sequence[Scenario]) -> Split:
    """Valida ``data`` y comprueba que encaja con los escenarios del conjunto.

    Raises:
        SplitInvalidError: si falla el contrato o alguna regla de consistencia.
    """
    split = parse_split(data)
    issues = split_issues(split, scenarios)
    if issues:
        raise SplitInvalidError(cap_issues(issues))
    return split


def split_issues(split: Split, scenarios: Sequence[Scenario]) -> list[CaseIssue]:
    """Problemas de la partición con los escenarios del conjunto, en orden fijo (SPLIT-C01..C06)."""
    by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    return [
        *_coverage(split, by_id),
        *_one_partition_per_group(split),
        *_groups_match(split, by_id),
        *_partitions_used(split),
        *_frozen(split),
        *_provenance(split, by_id),
    ]


def split_self_issues(split: Split) -> list[CaseIssue]:
    """Lo que se puede comprobar sin los escenarios: SPLIT-C02, SPLIT-C04 y SPLIT-C05."""
    return [*_one_partition_per_group(split), *_partitions_used(split), *_frozen(split)]


def _names(partitions: Sequence[Partition]) -> str:
    """Los nombres de las particiones en el orden fijo de entrenamiento, validación y prueba."""
    return ", ".join(sorted(partitions, key=PARTITIONS.index))


def _coverage(split: Split, by_id: dict[str, Scenario]) -> list[CaseIssue]:
    """SPLIT-C01: cada escenario del conjunto, una vez, y ninguno desconocido."""
    issues: list[CaseIssue] = []
    seen: set[str] = set()
    for index, assignment in enumerate(split.assignments):
        field = f"assignments[{index}].scenario_id"
        if assignment.scenario_id not in by_id:
            issues.append(
                CaseIssue(
                    "SPLIT-C01",
                    field,
                    f"el conjunto no tiene el escenario «{assignment.scenario_id}»",
                )
            )
        elif assignment.scenario_id in seen:
            issues.append(
                CaseIssue(
                    "SPLIT-C01",
                    field,
                    f"el escenario «{assignment.scenario_id}» está asignado más de una vez",
                )
            )
        seen.add(assignment.scenario_id)
    issues.extend(
        CaseIssue("SPLIT-C01", "assignments", f"falta asignar el escenario «{scenario_id}»")
        for scenario_id in by_id
        if scenario_id not in seen
    )
    return issues


def _one_partition_per_group(split: Split) -> list[CaseIssue]:
    """SPLIT-C02: todas las asignaciones de un grupo van a la misma partición."""
    partitions: dict[str, list[Partition]] = {}
    for assignment in split.assignments:
        found = partitions.setdefault(assignment.group_id, [])
        if assignment.partition not in found:
            found.append(assignment.partition)
    return [
        CaseIssue(
            "SPLIT-C02",
            "assignments",
            f"el grupo «{group_id}» está en varias particiones: {_names(found)}",
        )
        for group_id, found in partitions.items()
        if len(found) > 1
    ]


def _groups_match(split: Split, by_id: dict[str, Scenario]) -> list[CaseIssue]:
    """SPLIT-C03: el grupo de la asignación es el del escenario."""
    return [
        CaseIssue(
            "SPLIT-C03",
            f"assignments[{index}].group_id",
            f"el escenario «{assignment.scenario_id}» es del grupo "
            f"«{by_id[assignment.scenario_id].group_id}» y la asignación dice "
            f"«{assignment.group_id}»",
        )
        for index, assignment in enumerate(split.assignments)
        if assignment.scenario_id in by_id
        and by_id[assignment.scenario_id].group_id != assignment.group_id
    ]


def _partitions_used(split: Split) -> list[CaseIssue]:
    """SPLIT-C04: las tres particiones tienen al menos un grupo."""
    used = {assignment.partition for assignment in split.assignments}
    return [
        CaseIssue("SPLIT-C04", "assignments", f"la partición «{partition}» no tiene ningún grupo")
        for partition in PARTITIONS
        if partition not in used
    ]


def _frozen(split: Split) -> list[CaseIssue]:
    """SPLIT-C05: la partición está congelada."""
    if split.frozen:
        return []
    return [CaseIssue("SPLIT-C05", "frozen", "la partición no está congelada")]


def _provenance(split: Split, by_id: dict[str, Scenario]) -> list[CaseIssue]:
    """SPLIT-C06: una fuente de campo no puede aparecer en dos particiones."""
    found: dict[str, list[Partition]] = {}
    for assignment in split.assignments:
        scenario = by_id.get(assignment.scenario_id)
        if scenario is None or scenario.origin != "field_derived":
            continue
        for source in scenario.source_ids:
            partitions = found.setdefault(source, [])
            if assignment.partition not in partitions:
                partitions.append(assignment.partition)
    return [
        CaseIssue(
            "SPLIT-C06",
            "assignments",
            f"la fuente de campo «{source}» aparece en varias particiones: {_names(partitions)}",
        )
        for source, partitions in found.items()
        if len(partitions) > 1
    ]
