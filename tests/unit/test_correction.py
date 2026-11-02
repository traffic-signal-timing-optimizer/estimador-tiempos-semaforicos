"""Pruebas del corrector determinista de duraciones (DEV13, F3; HU11, ADR06, D5 a D11 y D18).

Datos sintéticos (la réplica de caso-001 está en ``timing_tools``). Las cifras de los ejemplos son
las del análisis del acta de F0 (``2026-11-02-dev13-f0-decisiones.md``), calculadas a mano y
confirmadas con el caso real.
"""

import dataclasses
import inspect
import random
import re
from fractions import Fraction
from typing import Any

import pytest

from semaforo.dominio import feasibility
from semaforo.dominio.feasibility import (
    ALGORITHM_VERSION,
    Correction,
    PreparedCase,
    check_plan,
    correct,
    prepare,
)
from timing_tools import (
    BASELINE,
    BASELINE_VARIABLE,
    CASE_ID,
    CASE_VERSION,
    FIXED,
    LIMITS,
    PRIORITY,
    VARIABLE_IDS,
    Change,
    make_case,
    prepared,
    priority_order,
)


def with_priority(change: Change | None = None) -> PreparedCase:
    return prepared(change, priority_order())


def run(
    durations: object,
    ready: PreparedCase | None = None,
    /,
    *,
    case_id: str = CASE_ID,
    case_version: str = CASE_VERSION,
) -> Correction:
    target = with_priority() if ready is None else ready
    return correct(target, durations, case_id=case_id, case_version=case_version)  # type: ignore[arg-type]


def variables(result: Correction) -> dict[str, float]:
    assert result.final_s is not None
    return {slot_id: result.final_s[slot_id] for slot_id in VARIABLE_IDS}


def plan(t1: float, t3: float, t5: float, t7: float) -> dict[str, float]:
    return {"t1": t1, "t3": t3, "t5": t5, "t7": t7}


def cycle_of(result: Correction) -> float:
    assert result.check is not None
    assert result.check.timing is not None
    return result.check.timing.cycle_s


# ---------------------------------------------------------------------------
# Aceptado: el original ya cumplía todo
# ---------------------------------------------------------------------------


def test_the_baseline_program_is_accepted_without_changes() -> None:
    ready = with_priority()
    result = run(BASELINE_VARIABLE, ready)
    assert result.status == "accepted"
    assert result.admissible
    assert dict(result.final_s or {}) == BASELINE
    assert dict(result.plan or {}) == BASELINE
    assert dict(result.original_s or {}) == BASELINE_VARIABLE
    assert dict(result.changes_s) == dict.fromkeys(VARIABLE_IDS, 0.0)
    assert result.check is not None
    assert result.check.feasible
    assert result.issues == ()
    assert (result.case_id, result.case_version) == (CASE_ID, CASE_VERSION)
    assert result.rules_version == ready.rules_version
    assert result.order_source == "declared"
    assert cycle_of(result) == 206.0


def test_noise_within_the_tolerance_is_accepted_and_the_final_is_the_exact_tick() -> None:
    result = run({**BASELINE_VARIABLE, "t1": 82.0 + 1e-10})
    assert result.status == "accepted"
    assert variables(result)["t1"] == 82.0
    assert -1e-9 < result.changes_s["t1"] < 0


def test_integers_are_valid_input_and_give_floats() -> None:
    result = run({key: int(value) for key, value in BASELINE_VARIABLE.items()})
    assert result.status == "accepted"
    assert dict(result.final_s or {}) == BASELINE
    assert all(isinstance(value, float) for value in (result.final_s or {}).values())


def test_the_fixed_slots_come_from_the_case_and_never_change() -> None:
    for proposal in (BASELINE_VARIABLE, plan(500, -5, 0, 1000)):
        result = run(proposal)
        assert {key: (result.final_s or {})[key] for key in FIXED} == FIXED


# ---------------------------------------------------------------------------
# Corregido con el orden del caso (t7, t5, t3, t1 pierden; t1, t3, t5, t7 ganan)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("proposal", "expected", "cycle"),
    [
        pytest.param(plan(110, 60, 70, 30), plan(110, 60, 41, 5), 240.0, id="todo-al-maximo"),
        pytest.param(plan(100, 58, 68, 29), plan(100, 58, 53, 5), 240.0, id="algo-pasado"),
        pytest.param(plan(30, 15, 25, 5), plan(51, 15, 25, 5), 120.0, id="todo-al-minimo"),
        pytest.param(plan(120, 10, 50.4, 40), plan(110, 15, 50, 30), 229.0, id="fuera-de-limites"),
        pytest.param(plan(82.5, 45.5, 44.5, 10.49), plan(83, 46, 45, 10), 208.0, id="medio-tick"),
        pytest.param(plan(1e308, -1e308, 45, 10), plan(110, 15, 45, 10), 204.0, id="enormes"),
        pytest.param(plan(-3, 45, 45, 10), plan(30, 45, 45, 10), 154.0, id="negativo"),
        pytest.param(plan(200, 200, 200, 200), plan(110, 60, 41, 5), 240.0, id="recorte-y-ciclo"),
        pytest.param(plan(0, 0, 0, 0), plan(51, 15, 25, 5), 120.0, id="todo-en-cero"),
    ],
)
def test_the_proposal_is_corrected_with_the_order_of_the_case(
    proposal: dict[str, float], expected: dict[str, float], cycle: float
) -> None:
    result = run(proposal)
    assert result.status == "corrected"
    assert result.admissible
    assert variables(result) == expected
    assert cycle_of(result) == cycle
    assert result.check is not None
    assert result.check.feasible


def test_the_changes_are_final_minus_original() -> None:
    result = run(plan(110, 60, 70, 30))
    assert dict(result.changes_s) == {"t1": 0.0, "t3": 0.0, "t5": -29.0, "t7": -25.0}
    result = run(plan(30, 15, 25, 5))
    assert dict(result.changes_s) == {"t1": 21.0, "t3": 0.0, "t5": 0.0, "t7": 0.0}


def test_the_original_is_recorded_as_received() -> None:
    proposal = plan(120, 10, 50.4, 40)
    result = run(proposal)
    assert dict(result.original_s or {}) == proposal


def test_when_the_first_slot_reaches_its_minimum_the_next_one_loses() -> None:
    # Sobran 54 + 10 s: t7 da 25 (hasta 5), t5 da 39 (de 70 a 31) y t3, t1 no pierden.
    result = run(plan(110, 60, 70, 30), with_priority(raise_fixed_red))
    assert variables(result) == plan(110, 60, 31, 5)


def raise_fixed_red(data: dict[str, Any]) -> None:
    """El todo rojo (t9) pasa de 4 a 14 s: diez segundos más de ciclo fijo."""
    data["slots"][8]["min_s"] = 14
    data["slots"][8]["max_s"] = 14


def test_when_the_excess_runs_through_every_slot_the_last_one_loses_too() -> None:
    def shorter_cycle(data: dict[str, Any]) -> None:
        data["cycle_s"] = {"min": 99, "max": 100}

    # Sobran 194 s y los cuatro van a su mínimo salvo t1, que queda en 31 para llegar a 100.
    result = run(plan(110, 60, 70, 30), with_priority(shorter_cycle))
    assert variables(result) == plan(31, 15, 25, 5)
    assert cycle_of(result) == 100.0


def test_when_the_cycle_is_short_the_first_to_gain_is_the_last_to_lose() -> None:
    def longer_minimum(data: dict[str, Any]) -> None:
        data["cycle_s"] = {"min": 230, "max": 240}

    # Faltan 131 s: t1 gana 80 (hasta 110), t3 gana 45 (hasta 60) y t5 gana 6.
    result = run(plan(30, 15, 25, 5), with_priority(longer_minimum))
    assert variables(result) == plan(110, 60, 31, 5)
    assert cycle_of(result) == 230.0


# ---------------------------------------------------------------------------
# Sin archivo de orden: el orden de la secuencia, como dice el diseño al pie de la letra
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("proposal", "expected"),
    [
        pytest.param(plan(110, 60, 70, 30), plan(56, 60, 70, 30), id="todo-al-maximo"),
        pytest.param(plan(100, 58, 68, 29), plan(61, 58, 68, 29), id="algo-pasado"),
        pytest.param(plan(30, 15, 25, 5), plan(51, 15, 25, 5), id="todo-al-minimo"),
    ],
)
def test_without_an_order_file_the_sequence_order_is_used(
    proposal: dict[str, float], expected: dict[str, float]
) -> None:
    result = run(proposal, prepared())
    assert result.order_source == "sequence"
    assert variables(result) == expected


# ---------------------------------------------------------------------------
# Aritmética exacta en ticks
# ---------------------------------------------------------------------------


def tenth_of_second(data: dict[str, Any]) -> None:
    data["tick_s"] = 0.1


def half_second(data: dict[str, Any]) -> None:
    data["tick_s"] = 0.5


@pytest.mark.parametrize(
    ("change", "value", "expected"),
    [
        (tenth_of_second, 82.35, 82.4),
        (tenth_of_second, 82.25, 82.3),
        (tenth_of_second, 82.34, 82.3),
        (tenth_of_second, 82.36, 82.4),
        (half_second, 82.25, 82.5),
        (half_second, 82.24, 82.0),
        (None, 82.5, 83.0),
        (None, 81.5, 82.0),
        (None, 82.4999, 82.0),
    ],
)
def test_half_a_tick_goes_up_and_the_rounding_is_exact(
    change: Change | None, value: float, expected: float
) -> None:
    result = run({**BASELINE_VARIABLE, "t1": value}, with_priority(change))
    assert result.status == "corrected"
    assert variables(result)["t1"] == expected


def test_binary_floats_would_have_rounded_the_wrong_way() -> None:
    assert 82.35 / 0.1 < 823.5  # el binario da 823.4999…; la aritmética exacta da 823.5
    result = run({**BASELINE_VARIABLE, "t1": 82.35}, with_priority(tenth_of_second))
    assert variables(result)["t1"] == 82.4


# ---------------------------------------------------------------------------
# Rechazado: lo que el algoritmo no repara (D11)
# ---------------------------------------------------------------------------


def tighter_straight_group(data: dict[str, Any]) -> None:
    data["green_groups"][1]["min_s"] = 100
    data["green_groups"][1]["max_s"] = 150


def test_a_group_tighter_than_its_slots_can_leave_the_plan_rejected() -> None:
    result = run(plan(30, 15, 45, 10), with_priority(tighter_straight_group))
    assert result.status == "rejected"
    assert not result.admissible
    assert result.plan is None
    assert result.check is not None
    assert result.check.violated == ("PLAN-05",)
    assert result.check.issues[0].field == "green_groups[1]"
    assert variables(result) == plan(30, 15, 45, 10)


def test_the_cycle_adjustment_can_break_a_group_and_then_it_is_rejected() -> None:
    def tighter_south(data: dict[str, Any]) -> None:
        data["green_groups"][3]["min_s"] = 60

    result = run(plan(110, 60, 70, 30), with_priority(tighter_south))
    assert result.status == "rejected"
    assert variables(result) == plan(110, 60, 41, 5)
    assert result.check is not None
    assert result.check.violated == ("PLAN-05",)
    assert "frutales_sur" in result.check.issues[0].message


def test_a_rejected_plan_keeps_the_original_and_the_changes() -> None:
    result = run(plan(30, 15, 45, 10), with_priority(tighter_straight_group))
    assert dict(result.original_s or {}) == plan(30, 15, 45, 10)
    assert dict(result.changes_s) == dict.fromkeys(VARIABLE_IDS, 0.0)


# ---------------------------------------------------------------------------
# Entrada inválida: no se corrige nada
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), float("-inf"), True, "82", None, [82], 10**400]
)
def test_a_value_that_is_not_a_finite_number_is_invalid_input(bad: object) -> None:
    ready = with_priority()
    result = run({**BASELINE_VARIABLE, "t1": bad}, ready)
    assert result.status == "invalid_input"
    assert not result.admissible
    assert [(i.rule_id, i.field) for i in result.issues] == [("TIME-01", "durations[t1]")]
    assert result.original_s is None
    assert result.final_s is None
    assert result.plan is None
    assert result.check is None
    assert dict(result.changes_s) == {}
    assert result.rules_version == ready.rules_version


def test_a_fixed_slot_in_the_proposal_is_invalid_input() -> None:
    result = run({**BASELINE_VARIABLE, "t2": 5.0})
    assert result.status == "invalid_input"
    assert [(i.field, i.message) for i in result.issues] == [
        ("durations[t2]", "no es un slot esperado")
    ]


def test_a_full_plan_is_not_a_proposal_of_variable_durations() -> None:
    result = run(BASELINE)
    assert result.status == "invalid_input"
    assert len(result.issues) == len(FIXED)


def test_a_missing_variable_slot_is_invalid_input() -> None:
    proposal = {key: value for key, value in BASELINE_VARIABLE.items() if key != "t7"}
    result = run(proposal)
    assert [(i.field, i.message) for i in result.issues] == [
        ("durations[t7]", "falta la duración del slot")
    ]


@pytest.mark.parametrize("value", [None, [], [82, 45, 45, 10], "plan", 5])
def test_a_proposal_that_is_not_a_mapping_is_invalid_input(value: object) -> None:
    result = run(value)
    assert result.status == "invalid_input"
    assert [i.field for i in result.issues] == ["durations"]


@pytest.mark.parametrize(
    ("claim", "fields"),
    [
        ({"case_id": "OTRO"}, ["case_id"]),
        ({"case_version": "2.0.0"}, ["case_version"]),
        ({"case_id": "", "case_version": "9.9.9"}, ["case_id", "case_version"]),
    ],
)
def test_a_proposal_for_another_case_or_version_is_invalid_input(
    claim: dict[str, str], fields: list[str]
) -> None:
    result = run(BASELINE_VARIABLE, **claim)
    assert result.status == "invalid_input"
    assert [(i.rule_id, i.field) for i in result.issues] == [("TIME-02", f) for f in fields]


def test_the_case_and_version_are_checked_before_the_durations() -> None:
    result = run({"t1": float("nan")}, case_id="OTRO")
    assert [i.rule_id for i in result.issues] == ["TIME-02"]


def test_a_huge_hostile_proposal_is_answered_quickly_with_capped_issues() -> None:
    proposal: dict[str, object] = {f"x{index}": 1.0 for index in range(100_000)}
    result = run(proposal)
    assert result.status == "invalid_input"
    assert len(result.issues) == 101


# ---------------------------------------------------------------------------
# Determinista, acotada, idéntica en todos los flujos (HU11, QA22)
# ---------------------------------------------------------------------------


def test_the_corrector_does_not_receive_flows() -> None:
    assert list(inspect.signature(correct).parameters) == [
        "prepared",
        "durations",
        "case_id",
        "case_version",
    ]


def test_the_same_input_gives_the_same_record_and_is_not_modified() -> None:
    ready = with_priority()
    proposal = plan(120, 10, 50.4, 40)
    before = dict(proposal)
    first = run(proposal, ready)
    assert run(proposal, ready) == first
    assert proposal == before


def test_the_record_cannot_be_modified() -> None:
    result = run(plan(110, 60, 70, 30))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status = "accepted"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.final_s["t1"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        result.changes_s["t1"] = 1.0  # type: ignore[index]
    with pytest.raises(TypeError):
        result.original_s["t1"] = 1.0  # type: ignore[index]


def random_proposal(rng: random.Random) -> dict[str, float]:
    """Una propuesta de cinco tipos: enteros dentro, cualquier valor, décimas, bordes y cerca del
    mínimo (para que también haya ciclos cortos)."""
    kind = rng.randrange(5)
    proposal: dict[str, float] = {}
    for slot_id in VARIABLE_IDS:
        low, high = LIMITS[slot_id]
        if kind == 0:
            value = float(rng.randint(int(low), int(high)))
        elif kind == 1:
            value = rng.uniform(-50, 300)
        elif kind == 2:
            value = rng.randint(int(low) * 10, int(high) * 10) / 10
        elif kind == 3:
            value = rng.choice([low, high, low - 1, high + 1])
        else:
            value = rng.uniform(low - 20, low + 4)
        proposal[slot_id] = value
    return proposal


def rounded(value: float, low: float, high: float) -> int:
    """Lo que esperamos tras recortar y redondear a ticks de 1 s (a medio tick, hacia arriba)."""
    exact = min(max(Fraction(repr(value)), Fraction(repr(low))), Fraction(repr(high)))
    return int(exact + Fraction(1, 2) - (exact + Fraction(1, 2)) % 1)


@pytest.mark.parametrize("declared", [True, False], ids=["orden-del-caso", "secuencia"])
@pytest.mark.parametrize("seed", range(200))
def test_every_correction_keeps_the_rules_on_generated_proposals(seed: int, declared: bool) -> None:
    rng = random.Random(seed)  # noqa: S311 - propuestas de prueba, no seguridad
    ready = with_priority() if declared else prepared()
    proposal = random_proposal(rng)
    result = run(proposal, ready)
    # En esta réplica (como en caso-001) los límites de los grupos son la suma de sus slots: nunca
    # se rechaza (hallazgo 1 de F0).
    assert result.status in ("accepted", "corrected")
    final = variables(result)
    # Acotada: cada slot dentro de sus límites, en ticks enteros, y el ciclo en su ventana.
    for slot_id, value in final.items():
        low, high = LIMITS[slot_id]
        assert low <= value <= high
        assert value == int(value)
    assert 120.0 <= cycle_of(result) <= 240.0
    # Lo que dice el registro se confirma validando de nuevo el plan final.
    assert check_plan(ready, dict(result.final_s or {})).feasible
    # Corregir el resultado no cambia nada: es aceptado tal cual.
    again = run(final, ready)
    assert again.status == "accepted"
    assert again.final_s == result.final_s
    # Los cambios son exactamente final menos original.
    for slot_id in VARIABLE_IDS:
        exact = Fraction(repr(final[slot_id])) - Fraction(repr(proposal[slot_id]))
        assert result.changes_s[slot_id] == float(exact)
    # El ajuste del ciclo sigue el orden: quien pierde lo hace solo si los anteriores ya están en
    # su mínimo; quien gana, solo si los anteriores ya están en su máximo.
    start = {i: rounded(proposal[i], *LIMITS[i]) for i in VARIABLE_IDS}
    start_cycle = sum(start.values()) + sum(FIXED.values())
    if start_cycle > 240:
        assert all(final[i] <= start[i] for i in VARIABLE_IDS)
        losers = [i for i in ready.cut_order if final[i] < start[i]]
        for earlier, later in zip(ready.cut_order, ready.cut_order[1:], strict=False):
            if later in losers:
                assert final[earlier] == LIMITS[earlier][0]
    elif start_cycle < 120:
        assert all(final[i] >= start[i] for i in VARIABLE_IDS)
        for earlier, later in zip(ready.give_order, ready.give_order[1:], strict=False):
            if final[later] > start[later]:
                assert final[earlier] == LIMITS[earlier][1]
    else:
        assert final == {i: float(start[i]) for i in VARIABLE_IDS}


def test_the_generated_proposals_cover_long_short_and_fine_cycles() -> None:
    seen = {"long": 0, "short": 0, "fine": 0, "accepted": 0}
    for seed in range(200):
        proposal = random_proposal(random.Random(seed))  # noqa: S311 - datos de prueba
        start = {i: rounded(proposal[i], *LIMITS[i]) for i in VARIABLE_IDS}
        cycle = sum(start.values()) + sum(FIXED.values())
        seen["long" if cycle > 240 else "short" if cycle < 120 else "fine"] += 1
        seen["accepted"] += run(proposal).status == "accepted"
    assert min(seen.values()) >= 5, seen


# ---------------------------------------------------------------------------
# Versión de reglas (D14)
# ---------------------------------------------------------------------------


def test_the_rules_version_is_a_sha256_and_repeats_for_the_same_rules() -> None:
    first = with_priority().rules_version
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert with_priority().rules_version == first


def test_the_rules_version_changes_with_the_order_the_limits_the_tick_or_the_groups() -> None:
    base = with_priority().rules_version

    def wider_slot(data: dict[str, Any]) -> None:
        data["slots"][0]["max_s"] = 111

    def other_group(data: dict[str, Any]) -> None:
        data["green_groups"][0]["min_s"] = 31

    versions = {
        prepared().rules_version,
        prepare(make_case(), priority_order(["t5", "t7", "t3", "t1"])).rules_version,
        with_priority(wider_slot).rules_version,
        with_priority(tenth_of_second).rules_version,
        with_priority(other_group).rules_version,
    }
    assert base not in versions
    assert len(versions) == 5


def test_a_declared_order_equal_to_the_sequence_still_differs_because_it_gives_in_reverse() -> None:
    declared = prepare(make_case(), priority_order(VARIABLE_IDS))
    assert declared.cut_order == prepared().cut_order
    assert declared.give_order != prepared().give_order
    assert declared.rules_version != prepared().rules_version


def test_the_rules_version_ignores_what_is_not_a_timing_rule() -> None:
    base = with_priority().rules_version

    def describe(data: dict[str, Any]) -> None:
        data["description"] = "otra descripción"
        data["movements"][0]["flow_domain_vph"] = {"min": 0, "max": 99}
        data["restrictions_evidence"] = ["otra evidencia"]

    assert with_priority(describe).rules_version == base


def test_the_algorithm_version_is_declared_and_enters_the_rules_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ALGORITHM_VERSION == "1.0.0"
    base = with_priority().rules_version
    monkeypatch.setattr(feasibility, "ALGORITHM_VERSION", "9.9.9")
    assert with_priority().rules_version != base


def test_the_priority_order_used_here_is_the_one_of_caso_001() -> None:
    assert with_priority().cut_order == tuple(PRIORITY)
