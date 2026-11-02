"""Asignación de familias completas a entrenamiento, validación y prueba (DEV12 F1, HU07).

Decisiones D3, D4 y D5 de F0. La unidad es el **grupo** (``group_id`` del escenario, que DEV11 pone
igual a la familia): un grupo va entero a una sola partición, con todas sus perturbaciones y
semillas. Nunca se asigna por fila ni por escenario suelto.

- **Cuántos grupos a cada partición.** Las proporciones de la política se aplican a la cantidad de
  grupos con el método del mayor resto (con las fracciones exactas de lo que se escribió, no de su
  aproximación binaria; en un empate gana el primero de entrenamiento, validación y prueba), y
  cada partición tiene al menos un grupo, así que hacen falta tres grupos como mínimo.
- **Cuáles.** Los grupos se ordenan por el SHA-256 de ``<semilla>|<política>|<grupo>``; los primeros
  van a prueba, los siguientes a validación y el resto a entrenamiento. Misma entrada y semilla
  dan siempre la misma partición, que no depende del orden en que lleguen los escenarios.
- **Congelada.** Toda partición creada lleva ``frozen = true``. Antes de devolverla se revisan las
  reglas SPLIT-C01 a SPLIT-C06 (en particular, que una fuente de campo no quede en dos partes).

No lee ni escribe archivos.
"""

import hashlib
import math
from collections.abc import Sequence
from fractions import Fraction

from semaforo.datos.scenarios import MAX_SEED
from semaforo.dominio.case import CaseIssue, Identifier, cap_issues
from semaforo.dominio.scenario import Scenario
from semaforo.dominio.split import (
    PARTITIONS,
    Assignment,
    Partition,
    Proportions,
    Split,
    SplitInvalidError,
    SplitPolicy,
    split_issues,
)

__all__ = [
    "MIN_GROUPS",
    "PROVISIONAL_POLICY",
    "assign_groups",
    "create_split",
    "partition_counts",
]

MIN_GROUPS = len(PARTITIONS)
PROVISIONAL_POLICY = SplitPolicy(
    policy_id="family_holdout",
    proportions=Proportions(train=0.6, validation=0.2, test=0.2),
    provisional=True,
)


def _exact(value: float) -> Fraction:
    """El número como lo escribió quien lo dio (0.6 es seis décimos, no su aproximación binaria)."""
    return Fraction(repr(float(value)))


def partition_counts(groups: int, proportions: Proportions) -> dict[Partition, int]:
    """Cuántos grupos van a cada partición: mayor resto y al menos uno en cada una.

    Raises:
        ValueError: si hay menos de ``MIN_GROUPS`` grupos.
    """
    if groups < MIN_GROUPS:
        raise ValueError(f"hacen falta al menos {MIN_GROUPS} grupos y hay {groups}")
    shares: dict[Partition, Fraction] = {
        "train": _exact(proportions.train),
        "validation": _exact(proportions.validation),
        "test": _exact(proportions.test),
    }
    quotas: dict[Partition, Fraction] = {name: groups * share for name, share in shares.items()}
    counts: dict[Partition, int] = {name: math.floor(quota) for name, quota in quotas.items()}
    leftover = groups - sum(counts.values())
    by_remainder = sorted(PARTITIONS, key=lambda name: -(quotas[name] - counts[name]))
    for name in by_remainder[:leftover]:
        counts[name] += 1
    for name in PARTITIONS:
        if counts[name] == 0:
            donor = max(PARTITIONS, key=lambda other: counts[other])
            counts[donor] -= 1
            counts[name] = 1
    return counts


def assign_groups(group_ids: Sequence[str], policy: SplitPolicy, seed: int) -> dict[str, Partition]:
    """La partición de cada grupo según la política y la semilla.

    Raises:
        ValueError: si hay menos de ``MIN_GROUPS`` grupos o un grupo se repite.
    """
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("hay grupos repetidos")
    counts = partition_counts(len(group_ids), policy.proportions)

    def rank(group_id: str) -> tuple[str, str]:
        text = f"{seed}|{policy.policy_id}|{group_id}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest(), group_id

    ordered = sorted(group_ids, key=rank)
    edges = {"test": counts["test"], "validation": counts["test"] + counts["validation"]}
    assigned: dict[str, Partition] = {}
    for position, group_id in enumerate(ordered):
        if position < edges["test"]:
            assigned[group_id] = "test"
        elif position < edges["validation"]:
            assigned[group_id] = "validation"
        else:
            assigned[group_id] = "train"
    return assigned


def _policy_text(policy: SplitPolicy) -> str:
    p = policy.proportions
    note = "proporciones provisionales (DEC07 pendiente)" if policy.provisional else "proporciones"
    return (
        f"{policy.policy_id}: familias completas; {note} de grupos "
        f"{p.train:g}/{p.validation:g}/{p.test:g} (entrenamiento/validación/prueba)"
    )


def create_split(
    scenarios: Sequence[Scenario], policy: SplitPolicy, seed: int, split_id: Identifier
) -> Split:
    """La partición congelada de ``scenarios`` según la política y la semilla.

    Raises:
        SplitInvalidError: si no hay escenarios, un escenario se repite, hay menos de tres grupos o
            la partición resultante incumple alguna regla (por ejemplo, una fuente de campo
            compartida entre dos partes).
    """
    problems = _input_issues(scenarios, seed)
    if problems:
        raise SplitInvalidError(problems)
    group_ids = sorted({scenario.group_id for scenario in scenarios})
    assigned = assign_groups(group_ids, policy, seed)
    split = Split(
        split_id=split_id,
        policy=_policy_text(policy),
        seed=seed,
        frozen=True,
        assignments=[
            Assignment(
                scenario_id=scenario.scenario_id,
                group_id=scenario.group_id,
                partition=assigned[scenario.group_id],
            )
            for scenario in scenarios
        ],
    )
    issues = split_issues(split, scenarios)
    if issues:
        raise SplitInvalidError(cap_issues(issues))
    return split


def _input_issues(scenarios: Sequence[Scenario], seed: int) -> list[CaseIssue]:
    issues: list[CaseIssue] = []
    if not 0 <= seed <= MAX_SEED:
        issues.append(
            CaseIssue(
                "SPLIT-S01",
                "seed",
                f"la semilla debe ser un entero de 0 a {MAX_SEED} y es {seed}",
            )
        )
    if not scenarios:
        return [*issues, CaseIssue("SPLIT-C01", "scenarios", "no hay escenarios que asignar")]
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        if scenario.scenario_id in seen:
            issues.append(
                CaseIssue(
                    "SPLIT-C01",
                    f"scenarios[{index}]",
                    f"el escenario «{scenario.scenario_id}» está repetido",
                )
            )
        seen.add(scenario.scenario_id)
    groups = {scenario.group_id for scenario in scenarios}
    if len(groups) < MIN_GROUPS:
        issues.append(
            CaseIssue(
                "SPLIT-C04",
                "scenarios",
                f"hacen falta al menos {MIN_GROUPS} grupos (uno por partición) y hay {len(groups)}",
            )
        )
    return issues
