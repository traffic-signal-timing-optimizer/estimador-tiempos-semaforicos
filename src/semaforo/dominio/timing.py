"""Reconstrucción del ciclo, los verdes y las ventanas desde las duraciones (DEV13 F1, HU11).

Un plan es una duración en segundos por cada slot del caso. A partir de ellas se reconstruye lo que
el modelo no predice (ADR05): el ciclo, el momento en que empieza y termina cada slot, y el verde
de cada grupo con sus ventanas. Es puro: no lee archivos ni lanza procesos (ADR01).

Cómo se cuenta (acta ``2026-11-02-dev13-f0-decisiones.md``):

- El ciclo suma cada slot una sola vez. Los grupos de verde se solapan sobre los slots (en
  caso-001, el grupo «recto» usa t1, t2 y t3, que comparten con otros dos grupos), así que sumar
  por grupos contaría dos veces el mismo tiempo.
- El verde de un grupo es la suma de sus slots, cada uno una vez, aunque el grupo los repita.
- Una **ventana** es una racha de slots del grupo que van seguidos en la secuencia. Si el grupo
  tiene el último slot y el primero, esas dos rachas son una sola ventana que cruza el fin del
  ciclo (``wraps``). Si las rachas están separadas se conserva cada una con su duración y el total
  del grupo no supone continuidad (diseño técnico, «Modelo de fases»). Las ventanas van ordenadas
  por su inicio en el ciclo.
- Las sumas son exactas: cada número se lee como decimal tal como se escribió (0.1 y 0.2 suman
  0.3, no 0.30000000000000004) y solo se pasa a ``float`` al final.

Esta reconstrucción no valida límites: dice cuánto vale cada cosa, no si es admisible. Solo
rechaza lo que no tiene sentido como duración (falta, sobra, no es un número, no es finito o es
negativa), con la regla TIME-01. La comprobación contra los límites del caso es de
``feasibility`` (F2).
"""

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import islice
from typing import Literal, cast

from semaforo.dominio.case import (
    MAX_ISSUES,
    Case,
    CaseIssue,
    GreenGroup,
    omitted_issue,
)
from semaforo.dominio.errors import DomainError, ErrorCode

__all__ = [
    "INPUT_RULE",
    "GreenWindow",
    "GroupTiming",
    "SlotTiming",
    "Timing",
    "TimingInputError",
    "duration_issues",
    "reconstruct",
]

INPUT_RULE = "TIME-01"
MAX_SHOWN_CHARS = 40


@dataclass(frozen=True)
class SlotTiming:
    """Cuándo empieza y termina un slot dentro del ciclo, en segundos desde su inicio."""

    slot_id: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class GreenWindow:
    """Una racha de slots seguidos de un grupo.

    ``start_s`` es el inicio dentro del ciclo. Si ``wraps`` es verdadero la ventana cruza el fin
    del ciclo: empieza en el último slot y sigue en el primero, así que ``start_s + duration_s``
    pasa del ciclo y el resto cae al comienzo del ciclo siguiente.
    """

    slot_ids: tuple[str, ...]
    start_s: float
    duration_s: float
    wraps: bool


@dataclass(frozen=True)
class GroupTiming:
    """Verde de un grupo: su total (cada slot una vez) y sus ventanas."""

    group_id: str
    purpose: Literal["vehicle", "pedestrian"]
    total_s: float
    windows: tuple[GreenWindow, ...]


@dataclass(frozen=True)
class Timing:
    """Lo que se reconstruye de un plan: ciclo, tiempos de cada slot y verde de cada grupo."""

    cycle_s: float
    slots: tuple[SlotTiming, ...]
    groups: tuple[GroupTiming, ...]

    @property
    def greens_s(self) -> dict[str, float]:
        """Verde total por grupo, como el campo ``greens_s`` del plan de la respuesta."""
        return {group.group_id: group.total_s for group in self.groups}


class TimingInputError(DomainError):
    """Las duraciones no tienen sentido como plan. Lleva todos los problemas.

    El código es INPUT_SCHEMA, que la CLI traduce al código de salida 2.
    """

    def __init__(self, issues: Sequence[CaseIssue]) -> None:
        if not issues:
            raise ValueError("una entrada inválida tiene al menos un problema")
        first = issues[0]
        extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
        where = "" if first.field is None else f" en {first.field}"
        super().__init__(
            ErrorCode.INPUT_SCHEMA,
            f"las duraciones no son válidas: {first.rule_id}{where}: {first.message}{extra}",
            first.field,
        )
        self.issues = tuple(issues)


def _shown(key: object) -> str:
    """Una clave tal como se muestra en un mensaje: acotada, porque puede ser hostil."""
    text = key if isinstance(key, str) else repr(key)
    return text if len(text) <= MAX_SHOWN_CHARS else f"{text[:MAX_SHOWN_CHARS]}…"


def _value_problem(value: object) -> str | None:
    """Por qué ``value`` no sirve como duración; None si sirve (cero incluido)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "debe ser un número"
    try:
        number = float(value)
    except OverflowError:
        return "es demasiado grande para ser una duración"
    if not math.isfinite(number):
        return "debe ser un número finito (sin NaN ni infinito)"
    if number < 0:
        return "no puede ser negativa"
    return None


def _problems(expected: Sequence[str], durations: object) -> Iterator[CaseIssue]:
    """Los problemas de ``durations`` frente a los slots esperados: sobrantes, luego cada slot."""
    if not isinstance(durations, Mapping):
        yield CaseIssue(INPUT_RULE, "durations", "debe ser un objeto con la duración de cada slot")
        return
    given = cast("Mapping[object, object]", durations)
    known = set(expected)
    for key in given:
        if not isinstance(key, str) or key not in known:
            yield CaseIssue(INPUT_RULE, f"durations[{_shown(key)}]", "no es un slot esperado")
    for slot_id in expected:
        field = f"durations[{_shown(slot_id)}]"
        if slot_id not in given:
            yield CaseIssue(INPUT_RULE, field, "falta la duración del slot")
            continue
        problem = _value_problem(given[slot_id])
        if problem is not None:
            yield CaseIssue(INPUT_RULE, field, problem)


def duration_issues(expected: Sequence[str], durations: object) -> list[CaseIssue]:
    """Problemas de ``durations`` como entrada de un plan, o lista vacía si sirve.

    ``durations`` debe tener un número finito y no negativo (``int`` o ``float``, nunca un
    booleano) para cada ID de ``expected`` y ninguna otra clave. Se informan todos los problemas,
    hasta ``MAX_ISSUES``; si hay más, el último dice cuántos no se muestran. Los límites del caso
    no se miran.
    """
    found = _problems(expected, durations)
    issues = list(islice(found, MAX_ISSUES))
    omitted = sum(1 for _ in found)
    if omitted:
        issues.append(omitted_issue(omitted, INPUT_RULE))
    return issues


def _exact(value: float) -> Fraction:
    """El número como decimal tal como se escribió (``repr``), sin el ruido del binario."""
    return Fraction(repr(float(value)))


def _runs(members: Sequence[int]) -> list[list[int]]:
    """Agrupa posiciones ordenadas en rachas de posiciones seguidas."""
    runs: list[list[int]] = []
    for position in members:
        if runs and runs[-1][-1] + 1 == position:
            runs[-1].append(position)
        else:
            runs.append([position])
    return runs


def _group_timing(
    group: GreenGroup,
    order: Sequence[str],
    position: Mapping[str, int],
    exact: Mapping[str, Fraction],
    starts: Sequence[Fraction],
) -> GroupTiming:
    members = sorted({position[slot_id] for slot_id in group.slot_ids if slot_id in position})
    runs = _runs(members)
    wraps = len(runs) > 1 and runs[0][0] == 0 and runs[-1][-1] == len(order) - 1
    merged = [*runs[-1], *runs[0]] if wraps else []
    ordered = [*runs[1:-1], merged] if wraps else runs
    windows = tuple(
        GreenWindow(
            tuple(order[index] for index in run),
            float(starts[run[0]]),
            float(sum((exact[order[index]] for index in run), Fraction(0))),
            wraps=wraps and run is merged,
        )
        for run in ordered
    )
    total = sum((exact[order[index]] for index in members), Fraction(0))
    return GroupTiming(group.id, group.purpose, float(total), windows)


def reconstruct(case: Case, durations: Mapping[str, float]) -> Timing:
    """Ciclo, tiempos de cada slot y verde de cada grupo para las ``durations`` dadas.

    ``durations`` lleva los segundos de cada slot del caso (variables y fijos). El resultado no
    depende del orden de las claves: se recorre siempre la secuencia del caso. Si el caso repite
    el ID de un slot se usa el primero; si un grupo nombra un slot que no existe, se ignora.

    Raises:
        TimingInputError: si las duraciones no son un plan (TIME-01), o si su suma es tan grande
            que no cabe en un número.
    """
    order = list(dict.fromkeys(slot.id for slot in case.slots))
    issues = duration_issues(order, durations)
    if issues:
        raise TimingInputError(issues)
    exact = {slot_id: _exact(durations[slot_id]) for slot_id in order}
    position = {slot_id: index for index, slot_id in enumerate(order)}
    starts: list[Fraction] = []
    elapsed = Fraction(0)
    for slot_id in order:
        starts.append(elapsed)
        elapsed += exact[slot_id]
    try:
        return Timing(
            float(elapsed),
            tuple(
                SlotTiming(slot_id, float(start), float(start + exact[slot_id]))
                for slot_id, start in zip(order, starts, strict=True)
            ),
            tuple(
                _group_timing(group, order, position, exact, starts) for group in case.green_groups
            ),
        )
    except OverflowError:
        raise TimingInputError(
            [
                CaseIssue(
                    INPUT_RULE, "durations", "las duraciones suman más de lo que cabe en un número"
                )
            ]
        ) from None
