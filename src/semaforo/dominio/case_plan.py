"""Comprobación de unas duraciones frente a los límites del caso (DEV03, F2).

Un plan es una duración en segundos por cada slot del caso. Esta comprobación es pura: no lee
archivos ni lanza procesos (ADR01). La usa el compilador del programa derivado y la podrá usar
cualquier otro módulo que necesite saber si unas duraciones son admisibles.

Reglas (los problemas se informan todos juntos, cada uno con su regla y su campo):

- PLAN-01: hay una duración finita para cada slot del caso y para ningún otro.
- PLAN-02: cada duración está dentro de los límites de su slot.
- PLAN-03: cada duración es múltiplo del tick del caso.
- PLAN-04: el ciclo (la suma de los slots) está dentro del rango del caso.
- PLAN-05: el verde de cada grupo está dentro de sus límites.

PLAN-04 y PLAN-05 solo se evalúan si las tres primeras pasan: sumar duraciones inválidas
produciría mensajes sin sentido.
"""

import math
from collections.abc import Mapping

from semaforo.dominio.case import Case, CaseIssue
from semaforo.dominio.case_rules import EPSILON, TICK_EPSILON

__all__ = ["plan_issues"]

COMPLETE_RULE = "PLAN-01"
SLOT_LIMITS_RULE = "PLAN-02"
TICK_RULE = "PLAN-03"
CYCLE_RULE = "PLAN-04"
GROUP_RULE = "PLAN-05"


def plan_issues(case: Case, durations: Mapping[str, float]) -> list[CaseIssue]:
    """Problemas de ``durations`` (segundos por ID de slot) frente a los límites de ``case``."""
    issues = _completeness_issues(case, durations)
    if issues:
        return issues
    issues = _slot_issues(case, durations)
    if issues:
        return issues
    return [*_cycle_issues(case, durations), *_group_issues(case, durations)]


def _completeness_issues(case: Case, durations: Mapping[str, float]) -> list[CaseIssue]:
    known = {slot.id for slot in case.slots}
    issues = [
        CaseIssue(COMPLETE_RULE, f"durations[{slot_id}]", "no es un slot del caso")
        for slot_id in durations
        if slot_id not in known
    ]
    for slot in case.slots:
        value = durations.get(slot.id)
        field = f"durations[{slot.id}]"
        if value is None:
            issues.append(CaseIssue(COMPLETE_RULE, field, "falta la duración del slot"))
        elif not math.isfinite(value):
            issues.append(CaseIssue(COMPLETE_RULE, field, "la duración debe ser un número finito"))
    return issues


def _slot_issues(case: Case, durations: Mapping[str, float]) -> list[CaseIssue]:
    issues: list[CaseIssue] = []
    for slot in case.slots:
        value = durations[slot.id]
        field = f"durations[{slot.id}]"
        if value < slot.min_s - EPSILON or value > slot.max_s + EPSILON:
            issues.append(
                CaseIssue(
                    SLOT_LIMITS_RULE,
                    field,
                    f"{value:g} s está fuera de los límites del slot ({slot.min_s:g} a "
                    f"{slot.max_s:g} s)",
                )
            )
        if not _aligned(value, case.tick_s):
            issues.append(
                CaseIssue(
                    TICK_RULE,
                    field,
                    f"{value:g} s no es múltiplo del tick de {case.tick_s:g} s",
                )
            )
    return issues


def _cycle_issues(case: Case, durations: Mapping[str, float]) -> list[CaseIssue]:
    cycle = sum(durations[slot.id] for slot in case.slots)
    if cycle < case.cycle_s.min - EPSILON or cycle > case.cycle_s.max + EPSILON:
        return [
            CaseIssue(
                CYCLE_RULE,
                "durations",
                f"el ciclo de {cycle:g} s está fuera del rango del caso "
                f"({case.cycle_s.min:g} a {case.cycle_s.max:g} s)",
            )
        ]
    return []


def _group_issues(case: Case, durations: Mapping[str, float]) -> list[CaseIssue]:
    issues: list[CaseIssue] = []
    for index, group in enumerate(case.green_groups):
        total = sum(durations.get(slot_id, 0.0) for slot_id in dict.fromkeys(group.slot_ids))
        if total < group.min_s - EPSILON or total > group.max_s + EPSILON:
            issues.append(
                CaseIssue(
                    GROUP_RULE,
                    f"green_groups[{index}]",
                    f"el verde de {total:g} s del grupo {group.id!r} está fuera de sus límites "
                    f"({group.min_s:g} a {group.max_s:g} s)",
                )
            )
    return issues


def _aligned(value: float, tick: float) -> bool:
    """``value`` es múltiplo entero de ``tick`` (tolerancia relativa para valores grandes)."""
    ratio = value / tick
    return abs(ratio - round(ratio)) <= TICK_EPSILON * max(1.0, abs(ratio))
