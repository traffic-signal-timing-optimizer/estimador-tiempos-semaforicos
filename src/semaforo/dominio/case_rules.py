"""Reglas de consistencia del caso, CASE-C01 a C13 (DEV02).

Completan las reglas de estructura de ``semaforo.dominio.case``: un caso con la forma correcta
puede seguir siendo incoherente (dos slots con el mismo ID, un grupo que usa un slot que no existe,
un ciclo que los slots no pueden alcanzar). Cada regla revisa el caso entero, devuelve todos sus
problemas con campo y motivo, y es pura: no lee archivos ni lanza procesos (ADR01).

Las reglas se evalúan siempre en el mismo orden. CASE-C07 es un aviso: el caso es válido, pero dos
slots seguidos con los mismos estados deberían unirse. Las demás son errores.

Para no repetir la misma causa, una regla no se apoya en datos que otra ya declaró rotos: la
alcanzabilidad de un grupo (C09) se omite si el grupo usa un slot inexistente, repetido o con los
límites invertidos (C03), o si su propia ventana está invertida; la del ciclo (C10), si su rango
está invertido (C02) o algún slot tiene los límites invertidos (C03). Si un ID de slot está
repetido (C01), las demás reglas usan el primero.

Los comparadores toleran 1e-9 s de ruido de coma flotante; la alineación con el tick, 1e-8 ticks.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from semaforo.dominio.case import Case, CaseInvalidError, CaseIssue, Slot, cap_issues, parse_case

__all__ = [
    "RULES",
    "Rule",
    "RuleResult",
    "Window",
    "accept_case",
    "cycle_window",
    "evaluate_rules",
    "group_window",
]

RuleStatus = Literal["passed", "warning", "failed"]
Severity = Literal["error", "warning"]
EPSILON = 1e-9
TICK_EPSILON = 1e-8
GREEN_LETTERS = frozenset("gG")
MIN_SLOTS_TO_COMPARE = 2
MIN_SLOTS_FOR_WRAP = 3


@dataclass(frozen=True)
class Window:
    """Intervalo cerrado de duraciones, en segundos."""

    min: float
    max: float


@dataclass(frozen=True)
class Rule:
    """Una regla: su código, su título y quien la revisa."""

    rule_id: str
    title: str
    severity: Severity
    check: Callable[[Case], list[CaseIssue]]


@dataclass(frozen=True)
class RuleResult:
    """Resultado de una regla sobre un caso. Los avisos también llevan sus problemas."""

    rule_id: str
    title: str
    status: RuleStatus
    issues: tuple[CaseIssue, ...]


def _n(value: float) -> str:
    return f"{value:g}"


def _beyond(value: float, limit: float) -> bool:
    """``value`` supera a ``limit`` más allá del ruido de coma flotante."""
    return value > limit + EPSILON


def _aligned(value: float, tick: float) -> bool:
    """``value`` es múltiplo entero de ``tick`` (tolerancia relativa para valores grandes)."""
    ratio = value / tick
    return abs(ratio - round(ratio)) <= TICK_EPSILON * max(1.0, abs(ratio))


def _tls_lengths(case: Case) -> dict[str, int]:
    """Largo del estado de cada semáforo, el de su primera aparición, en el orden de aparición."""
    lengths: dict[str, int] = {}
    for slot in case.slots:
        for state in slot.states:
            lengths.setdefault(state.tls_id, len(state.state))
    return lengths


def _slots_by_id(case: Case) -> dict[str, Slot]:
    """Slots por ID. Si un ID se repite (CASE-C01), vale el primero."""
    by_id: dict[str, Slot] = {}
    for slot in case.slots:
        by_id.setdefault(slot.id, slot)
    return by_id


def _inverted(slot: Slot) -> bool:
    """El mínimo del slot supera a su máximo (CASE-C03)."""
    return _beyond(slot.min_s, slot.max_s)


def cycle_window(case: Case) -> Window | None:
    """Ciclo factible: la intersección del rango declarado con lo que suman los slots.

    Cada slot cuenta una sola vez. Los grupos de verde se solapan sobre los slots, así que sumar
    por grupos contaría dos veces el mismo tiempo. None si la intersección es vacía.
    """
    low = max(case.cycle_s.min, sum(slot.min_s for slot in case.slots))
    high = min(case.cycle_s.max, sum(slot.max_s for slot in case.slots))
    return None if _beyond(low, high) else Window(low, high)


def group_window(case: Case, group_index: int) -> Window | None:
    """Verde alcanzable de un grupo: el rango declarado cruzado con la suma de sus slots.

    Los slots repetidos cuentan una vez y los inexistentes no cuentan. None si es vacío.
    """
    group = case.green_groups[group_index]
    by_id = _slots_by_id(case)
    used = [by_id[slot_id] for slot_id in dict.fromkeys(group.slot_ids) if slot_id in by_id]
    low = max(group.min_s, sum(slot.min_s for slot in used))
    high = min(group.max_s, sum(slot.max_s for slot in used))
    return None if _beyond(low, high) else Window(low, high)


def _unique_ids(case: Case) -> list[CaseIssue]:
    """CASE-C01: identificadores únicos en clases, movimientos, slots y grupos."""
    issues: list[CaseIssue] = []

    def scan(ids: Sequence[str], field: Callable[[int], str]) -> None:
        first: dict[str, int] = {}
        for index, value in enumerate(ids):
            if value not in first:
                first[value] = index
                continue
            issues.append(
                CaseIssue(
                    "CASE-C01",
                    field(index),
                    f"el identificador {value!r} está repetido (ya está en {field(first[value])})",
                )
            )

    scan(case.vehicle_classes, lambda i: f"vehicle_classes[{i}]")
    scan([m.id for m in case.movements], lambda i: f"movements[{i}].id")
    scan([s.id for s in case.slots], lambda i: f"slots[{i}].id")
    scan([g.id for g in case.green_groups], lambda i: f"green_groups[{i}].id")
    return issues


def _ordered_ranges(case: Case) -> list[CaseIssue]:
    """CASE-C02: el mínimo de cada rango no supera a su máximo."""
    issues: list[CaseIssue] = []
    ranges = [("cycle_s", case.cycle_s)]
    ranges += [
        (f"movements[{i}].flow_domain_vph", m.flow_domain_vph) for i, m in enumerate(case.movements)
    ]
    for field, window in ranges:
        if _beyond(window.min, window.max):
            issues.append(
                CaseIssue(
                    "CASE-C02",
                    field,
                    f"el mínimo ({_n(window.min)}) supera al máximo ({_n(window.max)})",
                )
            )
    return issues


def _slot_bounds(case: Case) -> list[CaseIssue]:
    """CASE-C03: mínimo ≤ máximo en cada slot, e igualdad en los fijos."""
    issues: list[CaseIssue] = []
    for index, slot in enumerate(case.slots):
        if _beyond(slot.min_s, slot.max_s):
            issues.append(
                CaseIssue(
                    "CASE-C03",
                    f"slots[{index}].min_s",
                    f"el mínimo ({_n(slot.min_s)}) supera al máximo ({_n(slot.max_s)})",
                )
            )
        elif slot.kind == "fixed" and _beyond(slot.max_s, slot.min_s):
            issues.append(
                CaseIssue(
                    "CASE-C03",
                    f"slots[{index}].kind",
                    f"un slot fijo necesita mínimo igual a máximo "
                    f"({_n(slot.min_s)} y {_n(slot.max_s)})",
                )
            )
    return issues


def _variable_slot(case: Case) -> list[CaseIssue]:
    """CASE-C04: al menos un slot variable, porque el modelo aprende las duraciones variables."""
    if any(slot.kind == "variable" for slot in case.slots):
        return []
    return [CaseIssue("CASE-C04", "slots", "no hay ningún slot variable: no habría qué estimar")]


def _tick_alignment(case: Case) -> list[CaseIssue]:
    """CASE-C05: límites de slots, del ciclo y de los grupos múltiplos de ``tick_s``."""
    issues: list[CaseIssue] = []
    tick = case.tick_s
    values: list[tuple[str, float]] = []
    for i, slot in enumerate(case.slots):
        values += [(f"slots[{i}].min_s", slot.min_s), (f"slots[{i}].max_s", slot.max_s)]
    values += [("cycle_s.min", case.cycle_s.min), ("cycle_s.max", case.cycle_s.max)]
    for i, group in enumerate(case.green_groups):
        values += [
            (f"green_groups[{i}].min_s", group.min_s),
            (f"green_groups[{i}].max_s", group.max_s),
        ]
    for field, value in values:
        if not _aligned(value, tick):
            issues.append(
                CaseIssue("CASE-C05", field, f"{_n(value)} no es múltiplo de tick_s ({_n(tick)})")
            )
    return issues


def _states_per_tls(case: Case) -> list[CaseIssue]:
    """CASE-C06: un estado por semáforo en cada slot, del mismo largo en todos los slots."""
    issues: list[CaseIssue] = []
    lengths = _tls_lengths(case)
    for index, slot in enumerate(case.slots):
        seen: set[str] = set()
        for position, state in enumerate(slot.states):
            field = f"slots[{index}].states[{position}]"
            if state.tls_id in seen:
                issues.append(
                    CaseIssue(
                        "CASE-C06",
                        f"{field}.tls_id",
                        f"el semáforo {state.tls_id!r} aparece dos veces en el slot",
                    )
                )
            elif len(state.state) != lengths[state.tls_id]:
                issues.append(
                    CaseIssue(
                        "CASE-C06",
                        f"{field}.state",
                        f"el estado mide {len(state.state)} y el de {state.tls_id!r} mide "
                        f"{lengths[state.tls_id]} en el primer slot que lo usa",
                    )
                )
            seen.add(state.tls_id)
        issues.extend(
            CaseIssue(
                "CASE-C06",
                f"slots[{index}].states",
                f"falta el estado del semáforo {tls_id!r}",
            )
            for tls_id in lengths
            if tls_id not in seen
        )
    return issues


def _repeated_states(case: Case) -> list[CaseIssue]:
    """CASE-C07 (aviso): dos slots seguidos, o el último con el primero, con los mismos estados."""
    count = len(case.slots)
    if count < MIN_SLOTS_TO_COMPARE:
        return []
    signatures = [
        tuple(sorted((state.tls_id, state.state) for state in slot.states)) for slot in case.slots
    ]
    pairs = [(i, i + 1) for i in range(count - 1)]
    if count >= MIN_SLOTS_FOR_WRAP:
        pairs.append((count - 1, 0))
    return [
        CaseIssue(
            "CASE-C07",
            f"slots[{later}]",
            f"el slot {case.slots[later].id!r} tiene los mismos estados que "
            f"{case.slots[earlier].id!r}, que lo precede en el ciclo; podrían unirse",
        )
        for earlier, later in pairs
        if signatures[earlier] == signatures[later]
    ]


def _movement_links(case: Case) -> list[CaseIssue]:
    """CASE-C08: el semáforo de cada movimiento existe y sus índices de enlace son válidos."""
    issues: list[CaseIssue] = []
    lengths = _tls_lengths(case)
    owner: dict[tuple[str, int], str] = {}
    for index, movement in enumerate(case.movements):
        base = f"movements[{index}]"
        known = movement.tls_id in lengths
        if not known:
            issues.append(
                CaseIssue(
                    "CASE-C08",
                    f"{base}.tls_id",
                    f"el semáforo {movement.tls_id!r} no aparece en ningún slot",
                )
            )
        own: set[int] = set()
        for position, link in enumerate(movement.link_indices):
            field = f"{base}.link_indices[{position}]"
            key = (movement.tls_id, link)
            message: str | None = None
            if link < 0:
                message = f"el índice de enlace {link} es negativo"
            elif link in own:
                message = f"el índice de enlace {link} está repetido en el movimiento"
            elif key in owner:
                message = f"el enlace {link} de {movement.tls_id!r} ya lo usa {owner[key]!r}"
            elif known and link >= lengths[movement.tls_id]:
                message = (
                    f"el índice {link} no cabe en el estado de {movement.tls_id!r}, "
                    f"que mide {lengths[movement.tls_id]}"
                )
            if message is not None:
                issues.append(CaseIssue("CASE-C08", field, message))
            if link >= 0:
                own.add(link)
                owner.setdefault(key, movement.id)
    return issues


def _group_slots(case: Case) -> list[CaseIssue]:
    """CASE-C09: los slots de cada grupo existen, no se repiten, y su ventana es alcanzable."""
    issues: list[CaseIssue] = []
    by_id = _slots_by_id(case)
    for index, group in enumerate(case.green_groups):
        base = f"green_groups[{index}]"
        seen: set[str] = set()
        clean = True
        for position, slot_id in enumerate(group.slot_ids):
            field = f"{base}.slot_ids[{position}]"
            if slot_id in seen:
                clean = False
                issues.append(CaseIssue("CASE-C09", field, f"el slot {slot_id!r} está repetido"))
            elif slot_id not in by_id:
                clean = False
                issues.append(CaseIssue("CASE-C09", field, f"el slot {slot_id!r} no existe"))
            elif _inverted(by_id[slot_id]):
                clean = False
            seen.add(slot_id)
        if _beyond(group.min_s, group.max_s):
            issues.append(
                CaseIssue(
                    "CASE-C09",
                    f"{base}.min_s",
                    f"el mínimo ({_n(group.min_s)}) supera al máximo ({_n(group.max_s)})",
                )
            )
        elif clean:
            issues.extend(_unreachable_group(case, index))
    return issues


def _unreachable_group(case: Case, index: int) -> list[CaseIssue]:
    """El verde del grupo no se puede lograr con las duraciones de sus slots."""
    group = case.green_groups[index]
    by_id = _slots_by_id(case)
    used = [by_id[slot_id] for slot_id in group.slot_ids]
    low = sum(slot.min_s for slot in used)
    high = sum(slot.max_s for slot in used)
    issues: list[CaseIssue] = []
    if _beyond(low, group.max_s):
        issues.append(
            CaseIssue(
                "CASE-C09",
                f"green_groups[{index}].max_s",
                f"sus slots necesitan al menos {_n(low)} s y el máximo del grupo es "
                f"{_n(group.max_s)} s",
            )
        )
    if _beyond(group.min_s, high):
        issues.append(
            CaseIssue(
                "CASE-C09",
                f"green_groups[{index}].min_s",
                f"sus slots suman como mucho {_n(high)} s y el mínimo del grupo es "
                f"{_n(group.min_s)} s",
            )
        )
    return issues


def _feasible_cycle(case: Case) -> list[CaseIssue]:
    """CASE-C10: el rango del ciclo se cruza con lo que pueden sumar los slots."""
    if (
        _beyond(case.cycle_s.min, case.cycle_s.max)
        or any(_inverted(slot) for slot in case.slots)
        or cycle_window(case) is not None
    ):
        return []
    low = sum(slot.min_s for slot in case.slots)
    high = sum(slot.max_s for slot in case.slots)
    return [
        CaseIssue(
            "CASE-C10",
            "cycle_s",
            f"el ciclo declarado [{_n(case.cycle_s.min)}, {_n(case.cycle_s.max)}] s no se cruza "
            f"con lo que suman los slots [{_n(low)}, {_n(high)}] s",
        )
    ]


def _green_in_group_slots(case: Case) -> list[CaseIssue]:
    """CASE-C11: cada slot de un grupo de verde muestra verde en algún enlace."""
    issues: list[CaseIssue] = []
    by_id = _slots_by_id(case)
    for index, group in enumerate(case.green_groups):
        for position, slot_id in enumerate(group.slot_ids):
            slot = by_id.get(slot_id)
            if slot is None:
                continue
            if not any(GREEN_LETTERS & set(state.state) for state in slot.states):
                issues.append(
                    CaseIssue(
                        "CASE-C11",
                        f"green_groups[{index}].slot_ids[{position}]",
                        f"el slot {slot_id!r} no muestra verde ('g' o 'G') en ningún enlace",
                    )
                )
    return issues


def _pedestrian_evidence(case: Case) -> list[CaseIssue]:
    """CASE-C12: los grupos peatonales exigen evidencia que respalde sus ventanas."""
    pedestrian = [group.id for group in case.green_groups if group.purpose == "pedestrian"]
    if not pedestrian or any(item.strip() for item in case.restrictions_evidence):
        return []
    return [
        CaseIssue(
            "CASE-C12",
            "restrictions_evidence",
            f"los grupos peatonales {pedestrian} necesitan evidencia de sus ventanas verdes",
        )
    ]


def _origin_and_status(case: Case) -> list[CaseIssue]:
    """CASE-C13: el origen del caso es coherente con su red y su estado de representación."""
    issues: list[CaseIssue] = []
    if case.origin == "field":
        if case.network is None:
            issues.append(CaseIssue("CASE-C13", "network", "un caso de campo debe declarar su red"))
        if case.representation_status == "synthetic_fixture":
            issues.append(
                CaseIssue(
                    "CASE-C13",
                    "representation_status",
                    "un caso de campo no puede ser 'synthetic_fixture'",
                )
            )
    elif case.representation_status in ("calibrated", "validated"):
        issues.append(
            CaseIssue(
                "CASE-C13",
                "representation_status",
                f"un caso sintético no puede estar {case.representation_status!r}",
            )
        )
    return issues


RULES: tuple[Rule, ...] = (
    Rule("CASE-C01", "Identificadores únicos", "error", _unique_ids),
    Rule("CASE-C02", "Rangos con mínimo no mayor que máximo", "error", _ordered_ranges),
    Rule("CASE-C03", "Límites de cada slot", "error", _slot_bounds),
    Rule("CASE-C04", "Al menos un slot variable", "error", _variable_slot),
    Rule("CASE-C05", "Límites alineados con el tick", "error", _tick_alignment),
    Rule("CASE-C06", "Un estado por semáforo en cada slot", "error", _states_per_tls),
    Rule("CASE-C07", "Slots seguidos con estados distintos", "warning", _repeated_states),
    Rule("CASE-C08", "Semáforo e índices de enlace de los movimientos", "error", _movement_links),
    Rule("CASE-C09", "Slots y ventana de cada grupo de verde", "error", _group_slots),
    Rule("CASE-C10", "Ciclo factible", "error", _feasible_cycle),
    Rule("CASE-C11", "Verde en los slots de cada grupo", "error", _green_in_group_slots),
    Rule("CASE-C12", "Evidencia de los grupos peatonales", "error", _pedestrian_evidence),
    Rule("CASE-C13", "Origen y estado coherentes", "error", _origin_and_status),
)


def evaluate_rules(case: Case) -> list[RuleResult]:
    """Resultado de cada regla de consistencia sobre ``case``, en el orden de ``RULES``."""
    results: list[RuleResult] = []
    for rule in RULES:
        issues = rule.check(case)
        status: RuleStatus
        if not issues:
            status = "passed"
        else:
            status = "failed" if rule.severity == "error" else "warning"
        results.append(RuleResult(rule.rule_id, rule.title, status, tuple(issues)))
    return results


def accept_case(data: object) -> Case:
    """Valida la estructura de ``data`` y la consistencia del caso, y devuelve el caso.

    Los avisos (CASE-C07) no rechazan el caso; ``evaluate_rules`` los informa.

    Raises:
        CaseInvalidError: si falla la estructura (CASE-S01 a S03) o alguna regla de error
            (CASE-C01 a C13); lleva todos los problemas, hasta ``MAX_ISSUES``.
    """
    case = parse_case(data)
    issues = [
        issue
        for result in evaluate_rules(case)
        if result.status == "failed"
        for issue in result.issues
    ]
    if issues:
        raise CaseInvalidError(cap_issues(issues))
    return case
