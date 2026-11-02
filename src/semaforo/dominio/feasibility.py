"""Validador de factibilidad de un plan frente a las reglas temporales del caso (DEV13 F2, HU11).

Dice, regla por regla, si un plan (una duración por cada slot del caso) cumple todo lo que el caso
exige. No corrige nada: el corrector es de F3. Es puro: no lee archivos ni lanza procesos (ADR01).

Reglas, en el orden en que se evalúan:

- TIME-02: el plan dice ser del caso y de la versión que se está usando. Solo se evalúa si quien
  llama indica a qué caso y versión dice pertenecer; si no coinciden, no se evalúa nada más.
- TIME-01: hay un número finito y no negativo para cada slot y para ningún otro (``timing``).
- PLAN-01 a PLAN-05 (DEV03, ``case_plan``): duración finita por slot, dentro de los límites del
  slot (los slots fijos tienen mínimo igual al máximo, así que un fijo distinto de su valor
  incumple PLAN-02), múltiplo del tick, ciclo dentro del rango y verde de cada grupo dentro de sus
  límites. Los verdes de grupo se calculan sin doble conteo de solapes.

Cada regla queda **cumplida**, **violada** u **omitida**. Una regla se omite cuando una anterior
ya falló y evaluarla produciría mensajes sin sentido (sumar duraciones inválidas): PLAN-04 y
PLAN-05 se omiten si falla PLAN-02 o PLAN-03, y todo lo que sigue a TIME-01 o TIME-02 se omite si
ellas fallan. Una regla omitida no cuenta como cumplida: un plan solo es factible si todas las
reglas que se evaluaron quedaron cumplidas.

Las reglas del caso (CASE-C01 a C13) se comprueban una sola vez al preparar el caso con
``prepare``. Así la secuencia y los estados (C06, C07, C11) quedan garantizados: un plan trae solo
duraciones y no puede cambiarlos. Prepararlo una vez sirve a quien validará miles de planes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from semaforo.dominio.case import Case, CaseIssue
from semaforo.dominio.case_plan import (
    COMPLETE_RULE,
    CYCLE_RULE,
    GROUP_RULE,
    SLOT_LIMITS_RULE,
    TICK_RULE,
    plan_issues,
)
from semaforo.dominio.case_rules import require_consistent
from semaforo.dominio.timing import (
    INPUT_RULE,
    Timing,
    TimingInputError,
    duration_issues,
    reconstruct,
)

__all__ = [
    "CLAIM_RULE",
    "RULE_TITLES",
    "PlanCheck",
    "PreparedCase",
    "RuleOutcome",
    "RuleStatus",
    "check_plan",
    "prepare",
]

RuleStatus = Literal["satisfied", "violated", "skipped"]
CLAIM_RULE = "TIME-02"
RULE_TITLES = {
    CLAIM_RULE: "El plan es del caso y de la versión indicados",
    INPUT_RULE: "Una duración numérica y no negativa por slot",
    COMPLETE_RULE: "Una duración finita por slot del caso",
    SLOT_LIMITS_RULE: "Duración dentro de los límites del slot",
    TICK_RULE: "Duración múltiplo del tick",
    CYCLE_RULE: "Ciclo dentro del rango del caso",
    GROUP_RULE: "Verde de cada grupo dentro de sus límites",
}
# PLAN-01 a PLAN-05 se evalúan por etapas, como en ``plan_issues``: una etapa solo se evalúa si la
# anterior no encontró problemas.
PLAN_STAGES = (
    (COMPLETE_RULE,),
    (SLOT_LIMITS_RULE, TICK_RULE),
    (CYCLE_RULE, GROUP_RULE),
)


@dataclass(frozen=True)
class PreparedCase:
    """Un caso que ya pasó las reglas CASE-C01 a C13, listo para validar o corregir planes.

    ``slot_ids`` es la secuencia del caso (sin repetidos: lo garantiza CASE-C01), y
    ``variable_ids`` sus slots variables, en el mismo orden. ``warnings`` son los avisos de las
    reglas (CASE-C07), que no rechazan.
    """

    case: Case
    slot_ids: tuple[str, ...]
    variable_ids: tuple[str, ...]
    warnings: tuple[CaseIssue, ...]


@dataclass(frozen=True)
class RuleOutcome:
    """Resultado de una regla sobre un plan: cumplida, violada u omitida, y sus problemas."""

    rule_id: str
    title: str
    status: RuleStatus
    issues: tuple[CaseIssue, ...]


@dataclass(frozen=True)
class PlanCheck:
    """Resultado de validar un plan: cada regla evaluada y, si el plan es numérico, su ciclo.

    ``timing`` (ciclo, verdes y ventanas) está disponible siempre que TIME-01 se cumpla, aunque
    el plan viole límites: sirve para mostrar cuánto se pasó.
    """

    outcomes: tuple[RuleOutcome, ...]
    timing: Timing | None

    @property
    def feasible(self) -> bool:
        """Todas las reglas evaluadas quedaron cumplidas (no hay violadas ni omitidas)."""
        return all(outcome.status == "satisfied" for outcome in self.outcomes)

    @property
    def issues(self) -> tuple[CaseIssue, ...]:
        """Todos los problemas, en el orden de las reglas."""
        return tuple(issue for outcome in self.outcomes for issue in outcome.issues)

    @property
    def violated(self) -> tuple[str, ...]:
        """Las reglas violadas, en el orden en que se evalúan."""
        return tuple(o.rule_id for o in self.outcomes if o.status == "violated")


def prepare(case: Case) -> PreparedCase:
    """Comprueba el caso una vez y lo deja listo para validar planes.

    Raises:
        CaseInvalidError: si el caso incumple alguna regla de error CASE-C01 a C13 (lleva todos
            los problemas). Los avisos no rechazan: quedan en ``warnings``.
    """
    results = require_consistent(case)
    return PreparedCase(
        case,
        tuple(slot.id for slot in case.slots),
        tuple(slot.id for slot in case.slots if slot.kind == "variable"),
        tuple(issue for result in results if result.status == "warning" for issue in result.issues),
    )


def _outcome(rule_id: str, issues: list[CaseIssue]) -> RuleOutcome:
    return RuleOutcome(
        rule_id, RULE_TITLES[rule_id], "violated" if issues else "satisfied", tuple(issues)
    )


def _claim_issues(case: Case, case_id: str | None, case_version: str | None) -> list[CaseIssue]:
    issues: list[CaseIssue] = []
    if case_id is not None and case_id != case.case_id:
        issues.append(
            CaseIssue(
                CLAIM_RULE, "case_id", f"el plan es de {case_id!r} y el caso es {case.case_id!r}"
            )
        )
    if case_version is not None and case_version != case.case_version:
        issues.append(
            CaseIssue(
                CLAIM_RULE,
                "case_version",
                f"el plan es de la versión {case_version!r} y el caso es {case.case_version!r}",
            )
        )
    return issues


def _plan_outcomes(case: Case, durations: Mapping[str, float]) -> list[RuleOutcome]:
    """PLAN-01 a PLAN-05 por etapas; las etapas que siguen a una que falló no se evalúan."""
    by_rule: dict[str, list[CaseIssue]] = {}
    for issue in plan_issues(case, durations):
        by_rule.setdefault(issue.rule_id, []).append(issue)
    outcomes: list[RuleOutcome] = []
    for stage in PLAN_STAGES:
        evaluated = [_outcome(rule_id, by_rule.get(rule_id, [])) for rule_id in stage]
        outcomes.extend(evaluated)
        if any(outcome.status == "violated" for outcome in evaluated):
            break
    return outcomes


def check_plan(
    prepared: PreparedCase,
    durations: Mapping[str, float],
    *,
    case_id: str | None = None,
    case_version: str | None = None,
) -> PlanCheck:
    """Valida un plan completo (una duración por cada slot del caso) regla por regla.

    ``case_id`` y ``case_version`` son a lo que el plan dice pertenecer; si se indica alguno se
    evalúa TIME-02. Con datos hostiles (NaN, tipos raros, claves de más) no lanza: informa
    TIME-01.
    """
    case = prepared.case
    evaluated: list[RuleOutcome] = []
    timing: Timing | None = None
    claimed = case_id is not None or case_version is not None
    claim = _claim_issues(case, case_id, case_version)
    if claimed:
        evaluated.append(_outcome(CLAIM_RULE, claim))
    if not claim:
        problems = duration_issues(prepared.slot_ids, durations)
        if not problems:
            try:
                timing = reconstruct(case, durations)
            except TimingInputError as error:
                problems = list(error.issues)
        evaluated.append(_outcome(INPUT_RULE, problems))
        if not problems:
            evaluated.extend(_plan_outcomes(case, durations))
    done = {outcome.rule_id: outcome for outcome in evaluated}
    order = [*([CLAIM_RULE] if claimed else []), INPUT_RULE, *(r for s in PLAN_STAGES for r in s)]
    return PlanCheck(
        tuple(
            done.get(rule_id, RuleOutcome(rule_id, RULE_TITLES[rule_id], "skipped", ()))
            for rule_id in order
        ),
        timing,
    )
