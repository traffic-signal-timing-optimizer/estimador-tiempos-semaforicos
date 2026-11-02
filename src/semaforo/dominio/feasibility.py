"""Validador y corrector de planes frente a las reglas temporales del caso (DEV13 F2 y F3, HU11).

``check_plan`` dice, regla por regla, si un plan (una duración por cada slot del caso) cumple todo
lo que el caso exige. ``correct`` recibe las duraciones variables que propone alguien (el modelo,
una persona) y devuelve un plan admisible o un rechazo trazable. Es puro: no lee archivos ni lanza
procesos (ADR01).

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

Corrección (diseño técnico, «Corrección determinista»; ADR06; decisiones D5 a D11 de F0):

1. La entrada debe ser del caso y la versión preparados (TIME-02) y traer un número finito para
   cada slot variable y para ningún otro (TIME-01, con negativos admitidos). Si no, el estado es
   ``invalid_input`` y no se corrige nada.
2. Cada duración se recorta a los límites de su slot, en segundos (así 1e308 no desborda).
3. Se pasa a ticks enteros con aritmética exacta: al tick más cercano y, a medio tick, hacia
   arriba. Como los límites ya son múltiplos del tick (CASE-C05), recortar y redondear en
   cualquier orden da lo mismo.
4. El ciclo se ajusta en ticks enteros a la ventana del caso (rango declarado cruzado con lo que
   pueden sumar los slots) con el **orden de ajuste** del caso: si sobra, se quita a los slots uno
   tras otro en ese orden, cada uno hasta su mínimo; si falta, se da a los slots en el orden de
   ganar, cada uno hasta su máximo (ver ``PreparedCase``). Son dos recorridos: el número de pasos
   tiene un tope fijo.
5. Se reconstruye y se comprueba el plan final con ``check_plan``. Si el original ya cumplía todo
   el estado es ``accepted``; si el final cumple todo, ``corrected``; si alguna regla sigue
   fallando (por ejemplo, el verde de un grupo con límites más estrictos que sus slots),
   ``rejected``: se registra con sus reglas y no hay plan admisible. No hay búsqueda ni
   simulación como sustitución.

El corrector no recibe flujos: la corrección es la misma para cualquier demanda (HU11).
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Literal

from semaforo.dominio.adjust_order import AdjustOrder, AdjustOrderInvalidError, order_issues
from semaforo.dominio.case import Case, CaseIssue
from semaforo.dominio.case_plan import (
    COMPLETE_RULE,
    CYCLE_RULE,
    GROUP_RULE,
    SLOT_LIMITS_RULE,
    TICK_RULE,
    plan_issues,
)
from semaforo.dominio.case_rules import cycle_window, require_consistent
from semaforo.dominio.timing import (
    INPUT_RULE,
    Timing,
    TimingInputError,
    duration_issues,
    reconstruct,
)

__all__ = [
    "ALGORITHM_VERSION",
    "CLAIM_RULE",
    "RULE_TITLES",
    "Correction",
    "CorrectionStatus",
    "OrderSource",
    "PlanCheck",
    "PreparedCase",
    "RuleOutcome",
    "RuleStatus",
    "check_plan",
    "correct",
    "prepare",
]

RuleStatus = Literal["satisfied", "violated", "skipped"]
CorrectionStatus = Literal["accepted", "corrected", "rejected", "invalid_input"]
OrderSource = Literal["declared", "sequence"]
# Versión del algoritmo de corrección: entra en la versión de reglas (D14). Cambiarla obliga a que
# lo corregido antes se pueda distinguir de lo corregido después.
ALGORITHM_VERSION = "1.0.0"
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

    ``cut_order`` es el orden en que los slots variables pierden tiempo si el ciclo se pasa, y
    ``give_order`` el orden en que lo ganan si se queda corto. Con el orden declarado en el archivo
    del caso (``order_source`` ``declared``), se gana en el orden inverso al de perder: el último
    en perder es el primero en ganar (D6). Sin archivo (``sequence``) los dos son el orden de la
    secuencia, como dice el diseño técnico al pie de la letra.

    ``rules_version`` es la huella SHA-256 de la parte temporal del caso (tick, ciclo, slots y
    grupos), de los órdenes de ajuste y de la versión del algoritmo: cambia si cambia cualquiera
    de ellos, y no si cambian la descripción, los movimientos o los flujos.
    """

    case: Case
    slot_ids: tuple[str, ...]
    variable_ids: tuple[str, ...]
    warnings: tuple[CaseIssue, ...]
    cut_order: tuple[str, ...]
    give_order: tuple[str, ...]
    order_source: OrderSource
    rules_version: str


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


def _rules_version(case: Case, cut_order: tuple[str, ...], give_order: tuple[str, ...]) -> str:
    payload = {
        "algorithm": ALGORITHM_VERSION,
        "tick_s": case.tick_s,
        "cycle_s": case.cycle_s.model_dump(mode="json"),
        "slots": [slot.model_dump(mode="json") for slot in case.slots],
        "green_groups": [group.model_dump(mode="json") for group in case.green_groups],
        "cut_order": list(cut_order),
        "give_order": list(give_order),
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare(case: Case, order: AdjustOrder | None = None) -> PreparedCase:
    """Comprueba el caso (y su orden de ajuste, si lo tiene) una vez y lo deja listo.

    Raises:
        CaseInvalidError: si el caso incumple alguna regla de error CASE-C01 a C13 (lleva todos
            los problemas). Los avisos no rechazan: quedan en ``warnings``.
        AdjustOrderInvalidError: si el orden no es de este caso y versión, le falta o le sobra
            algún slot variable, o nombra un slot fijo o desconocido (ORDER-C01 a C03).
    """
    results = require_consistent(case)
    variable_ids = tuple(slot.id for slot in case.slots if slot.kind == "variable")
    source: OrderSource = "sequence"
    cut_order = give_order = variable_ids
    if order is not None:
        issues = order_issues(case, order)
        if issues:
            raise AdjustOrderInvalidError(issues)
        cut_order, source = tuple(order.cut_order), "declared"
        give_order = cut_order[::-1]
    return PreparedCase(
        case,
        tuple(slot.id for slot in case.slots),
        variable_ids,
        tuple(issue for result in results if result.status == "warning" for issue in result.issues),
        cut_order,
        give_order,
        source,
        _rules_version(case, cut_order, give_order),
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


@dataclass(frozen=True)
class Correction:
    """Registro de una corrección: qué llegó, qué salió, cuánto cambió y qué reglas cumple.

    - ``original_s``: las duraciones variables recibidas (None si la entrada no sirve).
    - ``final_s``: el plan completo después de corregir, con los fijos del caso. Está también en
      un rechazo, para que se vea qué se intentó; pero solo ``plan`` es admisible.
    - ``changes_s``: final menos original, por slot variable.
    - ``check``: las reglas sobre el plan final (ciclo, verdes y ventanas en ``check.timing``).
    - ``issues``: por qué la entrada no sirve (solo en ``invalid_input``).
    """

    status: CorrectionStatus
    case_id: str
    case_version: str
    rules_version: str
    order_source: OrderSource
    original_s: Mapping[str, float] | None
    final_s: Mapping[str, float] | None
    changes_s: Mapping[str, float]
    check: PlanCheck | None
    issues: tuple[CaseIssue, ...]

    @property
    def admissible(self) -> bool:
        """El plan final se puede usar: el original cumplía todo o se corrigió y cumple todo."""
        return self.status in ("accepted", "corrected")

    @property
    def plan(self) -> Mapping[str, float] | None:
        """El plan completo admisible, o None si se rechazó o la entrada no servía."""
        return self.final_s if self.admissible else None


def _exact(value: float) -> Fraction:
    """El número como decimal tal como se escribió (``repr``), sin el ruido del binario."""
    return Fraction(repr(float(value)))


def _ticks(seconds: Fraction, tick: Fraction) -> int:
    """Ticks enteros más cercanos a ``seconds``; a medio tick, hacia arriba."""
    return math.floor(seconds / tick + Fraction(1, 2))


def _full_plan(case: Case, variable: Mapping[str, float]) -> dict[str, float]:
    """Plan completo: las duraciones variables dadas y los fijos del caso."""
    return {
        slot.id: variable[slot.id] if slot.kind == "variable" else slot.min_s for slot in case.slots
    }


def _adjusted_ticks(prepared: PreparedCase, original: Mapping[str, Fraction]) -> dict[str, int]:
    """Pasos 2 a 4: recortar, pasar a ticks y ajustar el ciclo con el orden del caso."""
    case = prepared.case
    tick = _exact(case.tick_s)
    slots = {slot.id: slot for slot in case.slots}
    low = {i: _ticks(_exact(slots[i].min_s), tick) for i in prepared.variable_ids}
    high = {i: _ticks(_exact(slots[i].max_s), tick) for i in prepared.variable_ids}
    ticks = {
        i: _ticks(min(max(original[i], _exact(slots[i].min_s)), _exact(slots[i].max_s)), tick)
        for i in prepared.variable_ids
    }
    window = cycle_window(case)
    if window is None:  # no ocurre en un caso preparado (CASE-C10); el control final lo rechaza
        return ticks
    shortest, longest = _ticks(_exact(window.min), tick), _ticks(_exact(window.max), tick)
    cycle = sum(ticks.values()) + sum(
        _ticks(_exact(slot.min_s), tick) for slot in case.slots if slot.kind == "fixed"
    )
    for slot_id in prepared.cut_order:
        taken = min(max(cycle - longest, 0), ticks[slot_id] - low[slot_id])
        ticks[slot_id] -= taken
        cycle -= taken
    for slot_id in prepared.give_order:
        given = min(max(shortest - cycle, 0), high[slot_id] - ticks[slot_id])
        ticks[slot_id] += given
        cycle += given
    return ticks


def correct(
    prepared: PreparedCase,
    durations: Mapping[str, float],
    *,
    case_id: str,
    case_version: str,
) -> Correction:
    """Corrige las duraciones variables propuestas y devuelve el registro (ver el módulo).

    ``durations`` lleva los segundos de cada slot variable del caso (los fijos salen del caso).
    ``case_id`` y ``case_version`` son a lo que dice pertenecer la propuesta. Con datos hostiles
    no lanza: el estado es ``invalid_input`` con sus problemas. Misma entrada, mismo resultado.
    """
    case = prepared.case
    problems = _claim_issues(case, case_id, case_version) or duration_issues(
        prepared.variable_ids, durations, allow_negative=True
    )
    if problems:
        return Correction(
            "invalid_input",
            case.case_id,
            case.case_version,
            prepared.rules_version,
            prepared.order_source,
            None,
            None,
            MappingProxyType({}),
            None,
            tuple(problems),
        )
    original = {slot_id: float(durations[slot_id]) for slot_id in prepared.variable_ids}
    exact = {slot_id: _exact(value) for slot_id, value in original.items()}
    tick = _exact(case.tick_s)
    ticks = _adjusted_ticks(prepared, exact)
    final = _full_plan(case, {i: float(ticks[i] * tick) for i in prepared.variable_ids})
    before = check_plan(prepared, _full_plan(case, original))
    after = check_plan(prepared, final)
    status: CorrectionStatus
    if not after.feasible:
        status = "rejected"
    else:
        status = "accepted" if before.feasible else "corrected"
    return Correction(
        status,
        case.case_id,
        case.case_version,
        prepared.rules_version,
        prepared.order_source,
        MappingProxyType(original),
        MappingProxyType(final),
        MappingProxyType({i: float(ticks[i] * tick - exact[i]) for i in prepared.variable_ids}),
        after,
        (),
    )
