"""Pruebas del validador de factibilidad de un plan (DEV13, F2; QA02 con casos de frontera).

Datos sintéticos. ``replica`` reproduce la estructura de caso-001 (9 slots, 4 variables, 5 grupos de
verde que se solapan, ciclo de 120 a 240 s, tick de 1 s) con los límites de la tabla de DEV03 F0:
son propuestas del equipo pendientes de revisión con el especialista de tránsito.
"""

import copy
import dataclasses
import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from semaforo.dominio.case import Case, CaseInvalidError, parse_case
from semaforo.dominio.case_plan import plan_issues
from semaforo.dominio.feasibility import (
    CLAIM_RULE,
    RULE_TITLES,
    PlanCheck,
    PreparedCase,
    check_plan,
    prepare,
)
from semaforo.dominio.timing import INPUT_RULE

DEMO_CASE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "case.json").read_text(encoding="utf-8")
)
# (id, tipo, mínimo, máximo, estado de los dos enlaces del semáforo de ejemplo)
SLOT_TABLE = [
    ("t1", "variable", 30, 110, "GG"),
    ("t2", "fixed", 5, 5, "yG"),
    ("t3", "variable", 15, 60, "Gr"),
    ("t4", "fixed", 5, 5, "yr"),
    ("t5", "variable", 25, 70, "rG"),
    ("t6", "fixed", 5, 5, "yG"),
    ("t7", "variable", 5, 30, "rG"),
    ("t8", "fixed", 5, 5, "ry"),
    ("t9", "fixed", 4, 4, "rr"),
]
GROUP_TABLE = [
    ("jp_este_oeste", ["t1"], 30, 110),
    ("jp_oeste_este_recto", ["t1", "t2", "t3"], 50, 175),
    ("jp_oeste_este_flecha", ["t3"], 15, 60),
    ("frutales_sur", ["t5"], 25, 70),
    ("frutales_norte", ["t5", "t6", "t7"], 35, 105),
]
BASELINE = {
    "t1": 82.0,
    "t2": 5.0,
    "t3": 45.0,
    "t4": 5.0,
    "t5": 45.0,
    "t6": 5.0,
    "t7": 10.0,
    "t8": 5.0,
    "t9": 4.0,
}
SLOT_IDS = list(BASELINE)
VARIABLE_IDS = ["t1", "t3", "t5", "t7"]


def replica_data() -> dict[str, Any]:
    data = copy.deepcopy(DEMO_CASE)
    data["case_id"] = "REPLICA"
    data["tick_s"] = 1
    data["cycle_s"] = {"min": 120, "max": 240}
    data["slots"] = [
        {
            "id": slot_id,
            "kind": kind,
            "min_s": low,
            "max_s": high,
            "states": [{"tls_id": "DEMO_TLS", "state": state}],
        }
        for slot_id, kind, low, high, state in SLOT_TABLE
    ]
    data["green_groups"] = [
        {"id": name, "slot_ids": members, "min_s": low, "max_s": high, "purpose": "vehicle"}
        for name, members, low, high in GROUP_TABLE
    ]
    return data


def make_case(change: Callable[[dict[str, Any]], None] | None = None) -> Case:
    data = replica_data()
    if change is not None:
        change(data)
    return parse_case(data)


def prepared(change: Callable[[dict[str, Any]], None] | None = None) -> PreparedCase:
    return prepare(make_case(change))


def check(change: Callable[[dict[str, Any]], None] | None = None, /, **plan: float) -> PlanCheck:
    return check_plan(prepared(change), {**BASELINE, **plan})


def statuses(result: PlanCheck) -> dict[str, str]:
    return {outcome.rule_id: outcome.status for outcome in result.outcomes}


ALL_PLAN_RULES = ["PLAN-01", "PLAN-02", "PLAN-03", "PLAN-04", "PLAN-05"]


# ---------------------------------------------------------------------------
# Preparar el caso
# ---------------------------------------------------------------------------


def test_a_consistent_case_is_prepared_with_its_slots_in_sequence() -> None:
    ready = prepared()
    assert ready.slot_ids == tuple(SLOT_IDS)
    assert ready.variable_ids == tuple(VARIABLE_IDS)
    assert ready.case.case_id == "REPLICA"
    assert ready.warnings == ()


def test_a_prepared_case_cannot_be_modified() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        prepared().slot_ids = ()  # type: ignore[misc]


def test_a_case_that_breaks_an_error_rule_is_not_prepared() -> None:
    def invert(data: dict[str, Any]) -> None:
        data["slots"][0]["min_s"] = 200

    with pytest.raises(CaseInvalidError) as raised:
        prepared(invert)
    assert "CASE-C03" in {issue.rule_id for issue in raised.value.issues}


def test_every_problem_of_the_case_is_reported_together() -> None:
    def break_two_things(data: dict[str, Any]) -> None:
        data["slots"][0]["min_s"] = 200
        data["slots"][1]["id"] = "t1"

    with pytest.raises(CaseInvalidError) as raised:
        prepared(break_two_things)
    assert {"CASE-C01", "CASE-C03"} <= {issue.rule_id for issue in raised.value.issues}


def test_qa02_a_cycle_the_slots_cannot_reach_is_not_prepared() -> None:
    def unreachable(data: dict[str, Any]) -> None:
        data["cycle_s"] = {"min": 400, "max": 500}

    with pytest.raises(CaseInvalidError) as raised:
        prepared(unreachable)
    assert [issue.rule_id for issue in raised.value.issues] == ["CASE-C10"]


def test_a_group_window_that_cannot_be_reached_is_not_prepared() -> None:
    def unreachable(data: dict[str, Any]) -> None:
        data["green_groups"][0]["min_s"] = 500
        data["green_groups"][0]["max_s"] = 600

    with pytest.raises(CaseInvalidError) as raised:
        prepared(unreachable)
    assert "CASE-C09" in {issue.rule_id for issue in raised.value.issues}


def test_a_warning_does_not_stop_the_case_and_is_kept() -> None:
    def repeat_states(data: dict[str, Any]) -> None:
        data["slots"][8]["states"][0]["state"] = "ry"  # t9 igual a t8

    ready = prepared(repeat_states)
    assert [issue.rule_id for issue in ready.warnings] == ["CASE-C07"]


def test_the_variable_slots_are_found_even_if_the_kind_is_the_last_one_declared() -> None:
    ready = prepared()
    assert ready.variable_ids == tuple(
        slot.id for slot in ready.case.slots if slot.kind == "variable"
    )


# ---------------------------------------------------------------------------
# Un plan factible
# ---------------------------------------------------------------------------


def test_the_baseline_program_is_feasible() -> None:
    result = check()
    assert result.feasible
    assert result.violated == ()
    assert result.issues == ()
    assert [(o.rule_id, o.status) for o in result.outcomes] == [
        ("TIME-01", "satisfied"),
        *[(rule, "satisfied") for rule in ALL_PLAN_RULES],
    ]


def test_the_timing_of_a_feasible_plan_is_available() -> None:
    result = check()
    assert result.timing is not None
    assert result.timing.cycle_s == 206.0
    assert result.timing.greens_s["frutales_norte"] == 60.0


def test_every_rule_has_a_title_and_the_outcomes_carry_it() -> None:
    assert set(RULE_TITLES) == {"TIME-01", "TIME-02", *ALL_PLAN_RULES}
    assert all(RULE_TITLES.values())
    for outcome in check().outcomes:
        assert outcome.title == RULE_TITLES[outcome.rule_id]


def test_overlapping_groups_do_not_count_twice_in_the_cycle() -> None:
    result = check()
    greens = result.timing.greens_s if result.timing else {}
    assert sum(greens.values()) == 364.0
    assert sum(greens.values()) > 240.0
    assert result.feasible


def test_the_results_cannot_be_modified() -> None:
    result = check()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.timing = None  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.outcomes[0].status = "violated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Límites de los slots y slots fijos (PLAN-02)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slot", "value"), [("t1", 30.0), ("t1", 110.0), ("t3", 15.0), ("t3", 60.0)]
)
def test_qa02_the_limits_of_a_slot_are_inclusive(slot: str, value: float) -> None:
    assert check(**{slot: value}).feasible


@pytest.mark.parametrize(
    ("slot", "value"), [("t1", 29.0), ("t1", 111.0), ("t3", 14.0), ("t3", 61.0), ("t7", 4.0)]
)
def test_qa02_one_tick_outside_the_limits_violates_plan_02_and_skips_the_cycle_and_groups(
    slot: str, value: float
) -> None:
    result = check(**{slot: value})
    assert not result.feasible
    assert statuses(result) == {
        "TIME-01": "satisfied",
        "PLAN-01": "satisfied",
        "PLAN-02": "violated",
        "PLAN-03": "satisfied",
        "PLAN-04": "skipped",
        "PLAN-05": "skipped",
    }
    assert [(i.rule_id, i.field) for i in result.issues] == [("PLAN-02", f"durations[{slot}]")]
    assert "fuera de los límites del slot" in result.issues[0].message


def test_qa02_an_altered_fixed_slot_violates_its_interval() -> None:
    for value in (4.0, 6.0, 4.9999, 5.5):
        result = check(t2=value)
        assert "PLAN-02" in result.violated
        assert any(i.field == "durations[t2]" for i in result.issues)


def test_qa02_noise_within_the_tolerance_is_accepted_and_beyond_it_is_not() -> None:
    assert check(t1=30.0 - 1e-10).feasible
    assert check(t1=110.0 + 1e-10).feasible
    below = check(t1=30.0 - 1e-6)
    assert below.violated == ("PLAN-02", "PLAN-03")


def test_both_slot_rules_are_reported_together_on_different_slots() -> None:
    result = check(t1=29.0, t3=30.5)
    assert result.violated == ("PLAN-02", "PLAN-03")
    assert [(i.rule_id, i.field) for i in result.issues] == [
        ("PLAN-02", "durations[t1]"),
        ("PLAN-03", "durations[t3]"),
    ]


# ---------------------------------------------------------------------------
# Tick (PLAN-03)
# ---------------------------------------------------------------------------


def test_qa02_half_a_tick_violates_plan_03_only() -> None:
    result = check(t1=82.5)
    assert result.violated == ("PLAN-03",)
    assert statuses(result)["PLAN-04"] == "skipped"
    assert "no es múltiplo del tick" in result.issues[0].message


def test_a_finer_tick_accepts_half_seconds() -> None:
    def half_second(data: dict[str, Any]) -> None:
        data["tick_s"] = 0.5

    assert check(half_second, t1=82.5).feasible
    assert check(half_second, t1=82.25).violated == ("PLAN-03",)


def test_the_tick_tolerance_is_relative_and_tiny() -> None:
    assert check(t1=82.0 + 1e-10).feasible
    assert check(t1=82.0 + 1e-6).violated == ("PLAN-03",)


# ---------------------------------------------------------------------------
# Ciclo (PLAN-04)
# ---------------------------------------------------------------------------

AT_MAX_CYCLE = {"t1": 96.0, "t3": 46.0, "t5": 57.0, "t7": 17.0}
AT_MIN_CYCLE = {"t1": 36.0, "t3": 20.0, "t5": 30.0, "t7": 10.0}


def test_qa02_the_cycle_limits_are_inclusive() -> None:
    maximum = check(**AT_MAX_CYCLE)
    minimum = check(**AT_MIN_CYCLE)
    assert maximum.feasible
    assert maximum.timing is not None
    assert maximum.timing.cycle_s == 240.0
    assert minimum.feasible
    assert minimum.timing is not None
    assert minimum.timing.cycle_s == 120.0


def test_qa02_one_second_over_or_under_the_cycle_violates_plan_04_only() -> None:
    over = check(**{**AT_MAX_CYCLE, "t1": 97.0})
    under = check(**{**AT_MIN_CYCLE, "t1": 35.0})
    for result, cycle in ((over, "241"), (under, "119")):
        assert result.violated == ("PLAN-04",)
        assert statuses(result)["PLAN-05"] == "satisfied"
        assert result.issues[0].field == "durations"
        assert f"el ciclo de {cycle} s" in result.issues[0].message


def test_the_cycle_tolerance_is_a_nanosecond() -> None:
    assert check(**{**AT_MAX_CYCLE, "t1": 96.0 + 1e-10}).feasible


def test_the_cycle_is_reported_with_its_value_even_if_it_is_out_of_range() -> None:
    result = check(**{**AT_MAX_CYCLE, "t1": 110.0, "t3": 60.0})
    assert result.violated == ("PLAN-04",)
    assert result.timing is not None
    assert result.timing.cycle_s == 240.0 + 14 + 14


# ---------------------------------------------------------------------------
# Verde de cada grupo (PLAN-05)
# ---------------------------------------------------------------------------


def tighter_group(data: dict[str, Any]) -> None:
    """El grupo «recto» (t1 + t2 + t3) con límites más estrictos que la suma de sus slots."""
    data["green_groups"][1]["min_s"] = 100
    data["green_groups"][1]["max_s"] = 150


def test_qa02_a_group_green_is_checked_against_its_own_limits() -> None:
    assert check(tighter_group).feasible  # recto = 132
    assert check(tighter_group, t1=50.0, t3=45.0).feasible  # recto = 100, el mínimo
    assert check(tighter_group, t1=100.0, t3=45.0).feasible  # recto = 150, el máximo
    for plan in ({"t1": 49.0}, {"t1": 101.0}):
        result = check(tighter_group, **plan)
        assert result.violated == ("PLAN-05",)
        assert result.issues[0].field == "green_groups[1]"
        assert "jp_oeste_este_recto" in result.issues[0].message


def test_a_slot_shared_by_two_groups_violates_each_group_it_belongs_to() -> None:
    def both_tight(data: dict[str, Any]) -> None:
        tighter_group(data)
        data["green_groups"][0]["min_s"] = 82
        data["green_groups"][0]["max_s"] = 82

    result = check(both_tight, t1=60.0)
    assert result.violated == ("PLAN-05",)
    assert [i.field for i in result.issues] == ["green_groups[0]"]
    result = check(both_tight, t1=40.0, t3=15.0)
    assert [i.field for i in result.issues] == ["green_groups[0]", "green_groups[1]"]


def test_a_group_violation_and_a_cycle_violation_are_reported_together() -> None:
    def cross(data: dict[str, Any]) -> None:
        data["green_groups"][3]["min_s"] = 60
        data["green_groups"][3]["max_s"] = 70

    result = check(cross, t1=110.0, t3=60.0, t5=25.0, t7=30.0)
    assert result.violated == ("PLAN-04", "PLAN-05")
    assert {i.field for i in result.issues} == {"durations", "green_groups[3]"}


def test_a_group_that_repeats_a_slot_is_not_a_prepared_case() -> None:
    def repeated(data: dict[str, Any]) -> None:
        data["green_groups"][0]["slot_ids"] = ["t1", "t1"]

    with pytest.raises(CaseInvalidError) as raised:
        prepared(repeated)
    assert [issue.rule_id for issue in raised.value.issues] == ["CASE-C09"]


# ---------------------------------------------------------------------------
# TIME-01: la entrada no es un plan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), float("-inf"), -1.0, True, "82", None, [82], 10**400]
)
def test_a_value_that_is_not_a_duration_violates_time_01_and_skips_the_rest(bad: object) -> None:
    result = check(t1=bad)  # type: ignore[arg-type]
    assert result.violated == ("TIME-01",)
    assert result.timing is None
    assert statuses(result) == {
        "TIME-01": "violated",
        **dict.fromkeys(ALL_PLAN_RULES, "skipped"),
    }
    assert [(i.rule_id, i.field) for i in result.issues] == [("TIME-01", "durations[t1]")]


def test_a_boolean_is_not_a_duration_even_if_one_second_would_fit_the_limits() -> None:
    def short_slot(data: dict[str, Any]) -> None:
        data["slots"][0]["min_s"] = 1
        data["green_groups"][0]["min_s"] = 1
        data["green_groups"][1]["min_s"] = 21

    case = make_case(short_slot)
    assert check_plan(prepare(case), {**BASELINE, "t1": 1.0}).feasible
    result = check_plan(prepare(case), {**BASELINE, "t1": True})
    assert result.violated == ("TIME-01",)
    assert result.issues[0].message == "debe ser un número"
    # Las reglas PLAN de DEV03, que usa el compilador, también lo rechazan (PLAN-01).
    assert [i.rule_id for i in plan_issues(case, {**BASELINE, "t1": True})] == ["PLAN-01"]


def test_a_missing_and_an_unknown_slot_violate_time_01() -> None:
    plan = {key: value for key, value in BASELINE.items() if key != "t4"}
    plan["extra"] = 5.0
    result = check_plan(prepared(), plan)
    assert result.violated == ("TIME-01",)
    assert [i.field for i in result.issues] == ["durations[extra]", "durations[t4]"]


@pytest.mark.parametrize("value", [None, [], [1, 2], "plan", 5, ((("t1"), 1.0),)])
def test_an_input_that_is_not_a_mapping_violates_time_01(value: object) -> None:
    result = check_plan(prepared(), value)  # type: ignore[arg-type]
    assert result.violated == ("TIME-01",)
    assert [i.field for i in result.issues] == ["durations"]


def test_durations_whose_sum_overflows_violate_time_01_and_have_no_timing() -> None:
    result = check(t1=1.7e308, t2=1.7e308)
    assert result.violated == ("TIME-01",)
    assert result.timing is None
    assert "suman más de lo que cabe" in result.issues[0].message


def test_a_huge_but_finite_plan_is_judged_not_rejected() -> None:
    result = check(t1=1e300)
    assert result.violated == ("PLAN-02",)
    assert result.timing is not None


def test_a_zero_duration_is_numeric_and_violates_the_slot_limit() -> None:
    result = check(t1=0.0)
    assert result.violated == ("PLAN-02",)
    assert result.timing is not None


def test_the_timing_is_available_even_if_limits_are_violated() -> None:
    result = check(t1=500.0)
    assert result.violated == ("PLAN-02",)
    assert result.timing is not None
    assert result.timing.cycle_s == 206.0 - 82.0 + 500.0


# ---------------------------------------------------------------------------
# TIME-02: caso y versión
# ---------------------------------------------------------------------------


def test_without_a_claim_time_02_is_not_evaluated() -> None:
    assert CLAIM_RULE not in statuses(check())


def test_a_plan_of_the_same_case_and_version_satisfies_time_02() -> None:
    ready = prepared()
    for claim in (
        {"case_id": "REPLICA", "case_version": "1.0.0"},
        {"case_id": "REPLICA"},
        {"case_version": "1.0.0"},
    ):
        result = check_plan(ready, BASELINE, **claim)
        assert result.feasible
        assert result.outcomes[0].rule_id == CLAIM_RULE
        assert result.outcomes[0].status == "satisfied"
        assert len(result.outcomes) == 7


@pytest.mark.parametrize(
    ("claim", "fields"),
    [
        ({"case_id": "OTRO"}, ["case_id"]),
        ({"case_version": "2.0.0"}, ["case_version"]),
        ({"case_id": "OTRO", "case_version": "2.0.0"}, ["case_id", "case_version"]),
        ({"case_id": "", "case_version": "1.0.0"}, ["case_id"]),
    ],
)
def test_a_plan_of_another_case_or_version_violates_time_02_and_nothing_else_is_judged(
    claim: dict[str, str], fields: list[str]
) -> None:
    result = check_plan(prepared(), BASELINE, **claim)
    assert result.violated == ("TIME-02",)
    assert [i.field for i in result.issues] == fields
    assert result.timing is None
    assert [o.status for o in result.outcomes] == ["violated"] + ["skipped"] * 6


def test_time_02_is_judged_before_the_durations() -> None:
    result = check_plan(prepared(), {"t1": float("nan")}, case_id="OTRO")
    assert result.violated == ("TIME-02",)


# ---------------------------------------------------------------------------
# Propiedades de la comprobación
# ---------------------------------------------------------------------------


def test_the_check_does_not_modify_the_input_and_ignores_the_key_order() -> None:
    ready = prepared()
    plan = dict(BASELINE)
    first = check_plan(ready, plan)
    assert plan == BASELINE
    assert check_plan(ready, plan) == first
    keys = list(BASELINE)
    random.Random(4).shuffle(keys)  # noqa: S311 - orden de prueba, no seguridad
    assert check_plan(ready, {key: BASELINE[key] for key in keys}) == first


def test_the_same_invalid_plan_gives_the_same_report_every_time() -> None:
    ready = prepared()
    plan = {**BASELINE, "t1": 29.0, "t3": 30.5, "t7": float("nan")}
    assert check_plan(ready, plan) == check_plan(ready, plan)


def test_a_plan_with_integers_gives_the_same_result_as_floats() -> None:
    ready = prepared()
    as_integers = {key: int(value) for key, value in BASELINE.items()}
    assert check_plan(ready, as_integers) == check_plan(ready, BASELINE)


def random_plan(rng: random.Random) -> dict[str, float]:
    plan: dict[str, float] = {}
    for slot_id in SLOT_IDS:
        low, high = {row[0]: (row[2], row[3]) for row in SLOT_TABLE}[slot_id]
        kind = rng.randrange(5)
        if kind == 0:
            plan[slot_id] = float(low - 1 + rng.randint(0, high - low + 2))
        elif kind == 1:
            plan[slot_id] = rng.randint(0, 800) / 4
        elif kind == 2:
            plan[slot_id] = float(rng.choice([low, high]))
        else:
            plan[slot_id] = float(rng.randint(low, high))
    return plan


@pytest.mark.parametrize("seed", range(300))
def test_the_check_agrees_with_the_plan_rules_of_dev03(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - datos de prueba, no seguridad
    ready = prepared()
    plan = random_plan(rng)
    result = check_plan(ready, plan)
    expected = plan_issues(ready.case, plan)
    plan_found = [i for i in result.issues if i.rule_id.startswith("PLAN")]
    assert sorted(map(repr, plan_found)) == sorted(map(repr, expected))
    assert result.feasible == (expected == [])
    assert result.timing is not None
    # Una regla omitida nunca cuenta como cumplida.
    for outcome in result.outcomes:
        assert (outcome.status == "violated") == bool(outcome.issues)
    if "PLAN-02" in result.violated or "PLAN-03" in result.violated:
        assert statuses(result)["PLAN-04"] == statuses(result)["PLAN-05"] == "skipped"
    else:
        assert statuses(result)["PLAN-04"] != "skipped"


def test_the_random_plans_include_feasible_and_infeasible_ones_of_every_kind() -> None:
    ready = prepared()
    seen: set[tuple[str, ...]] = set()
    feasible = 0
    for seed in range(300):
        result = check_plan(ready, random_plan(random.Random(seed)))  # noqa: S311 - datos de prueba
        seen.add(result.violated)
        feasible += result.feasible
    assert feasible > 10
    assert ("PLAN-02",) in seen
    assert ("PLAN-03",) in seen
    assert ("PLAN-02", "PLAN-03") in seen
    assert ("PLAN-04",) in seen


def test_a_plan_is_not_feasible_if_any_evaluated_rule_is_not_satisfied() -> None:
    ready = prepared()
    result = check_plan(ready, BASELINE)
    weakened = PlanCheck(
        (*result.outcomes[:-1], dataclasses.replace(result.outcomes[-1], status="skipped")),
        result.timing,
    )
    assert result.feasible
    assert not weakened.feasible
    assert weakened.violated == ()


def test_time_01_covers_the_input_and_plan_01_stays_satisfied_after_it() -> None:
    result = check(t1=82.0)
    assert statuses(result)[INPUT_RULE] == statuses(result)["PLAN-01"] == "satisfied"
