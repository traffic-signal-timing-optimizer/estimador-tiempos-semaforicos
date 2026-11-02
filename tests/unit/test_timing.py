"""Pruebas de la reconstrucción del ciclo, los verdes y las ventanas (DEV13, F1; QA02).

Datos sintéticos. Los números de caso-001 salen de la tabla del acta de tiempos y límites de
DEV03 (``2026-10-30-dev03-f0-tiempos-y-limites.md``): ciclo de 206 s y verdes de 82, 132, 45, 45 y
60 s. Son propuestas del equipo pendientes de revisión con el especialista de tránsito.
"""

import copy
import dataclasses
import itertools
import json
import random
import time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from semaforo.dominio.case import MAX_ISSUES, Case, CaseIssue, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.timing import (
    INPUT_RULE,
    GreenWindow,
    GroupTiming,
    Timing,
    TimingInputError,
    duration_issues,
    reconstruct,
)

DEMO_CASE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "case.json").read_text(encoding="utf-8")
)
# Plan de ejemplo de response.json: ciclo de 60 s.
DEMO_PLAN = {"s1": 30.0, "s2": 3.0, "s3": 1.0, "s4": 22.0, "s5": 3.0, "s6": 1.0}
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
GROUPS_OF_BASELINE = {
    "jp_este_oeste": ["t1"],
    "jp_oeste_este_recto": ["t1", "t2", "t3"],
    "jp_oeste_este_flecha": ["t3"],
    "frutales_sur": ["t5"],
    "frutales_norte": ["t5", "t6", "t7"],
}


def build_case(slot_ids: list[str], groups: dict[str, list[str]]) -> Case:
    """Caso sintético con estos slots (todos variables entre 1 y 100 s) y estos grupos."""
    data = copy.deepcopy(DEMO_CASE)
    data["slots"] = [
        {
            "id": slot_id,
            "kind": "variable",
            "min_s": 1,
            "max_s": 100,
            "states": [{"tls_id": "DEMO_TLS", "state": "Gr"}],
        }
        for slot_id in slot_ids
    ]
    data["green_groups"] = [
        {"id": name, "slot_ids": members, "min_s": 0, "max_s": 100, "purpose": "vehicle"}
        for name, members in groups.items()
    ]
    return parse_case(data)


def baseline_case() -> Case:
    return build_case(list(BASELINE), GROUPS_OF_BASELINE)


def demo_case() -> Case:
    return parse_case(copy.deepcopy(DEMO_CASE))


def group_of(timing: Timing, group_id: str) -> GroupTiming:
    return next(group for group in timing.groups if group.group_id == group_id)


# ---------------------------------------------------------------------------
# Ciclo y tiempos de cada slot
# ---------------------------------------------------------------------------


def test_the_cycle_of_the_demo_plan_is_the_sum_of_its_slots() -> None:
    timing = reconstruct(demo_case(), DEMO_PLAN)
    assert timing.cycle_s == 60.0


def test_each_slot_starts_where_the_previous_one_ends() -> None:
    timing = reconstruct(demo_case(), DEMO_PLAN)
    assert [(s.slot_id, s.start_s, s.end_s) for s in timing.slots] == [
        ("s1", 0.0, 30.0),
        ("s2", 30.0, 33.0),
        ("s3", 33.0, 34.0),
        ("s4", 34.0, 56.0),
        ("s5", 56.0, 59.0),
        ("s6", 59.0, 60.0),
    ]


def test_the_baseline_program_of_caso_001_has_a_cycle_of_206_seconds() -> None:
    timing = reconstruct(baseline_case(), BASELINE)
    assert timing.cycle_s == 206.0
    assert timing.slots[-1].end_s == 206.0


def test_the_slots_of_the_baseline_follow_the_sequence() -> None:
    timing = reconstruct(baseline_case(), BASELINE)
    assert [(s.slot_id, s.start_s, s.end_s) for s in timing.slots] == [
        ("t1", 0.0, 82.0),
        ("t2", 82.0, 87.0),
        ("t3", 87.0, 132.0),
        ("t4", 132.0, 137.0),
        ("t5", 137.0, 182.0),
        ("t6", 182.0, 187.0),
        ("t7", 187.0, 197.0),
        ("t8", 197.0, 202.0),
        ("t9", 202.0, 206.0),
    ]


def test_the_order_of_the_keys_does_not_change_the_result() -> None:
    case = baseline_case()
    expected = reconstruct(case, BASELINE)
    for seed in range(5):
        keys = list(BASELINE)
        random.Random(seed).shuffle(keys)  # noqa: S311 - orden de prueba, no seguridad
        assert reconstruct(case, {key: BASELINE[key] for key in keys}) == expected


def test_integers_and_floats_give_the_same_result() -> None:
    case = baseline_case()
    as_integers = {key: int(value) for key, value in BASELINE.items()}
    assert reconstruct(case, as_integers) == reconstruct(case, BASELINE)


def test_the_same_input_twice_gives_the_same_result_and_is_not_modified() -> None:
    case = baseline_case()
    plan = dict(BASELINE)
    first = reconstruct(case, plan)
    assert reconstruct(case, plan) == first
    assert plan == BASELINE


def test_the_result_cannot_be_modified() -> None:
    timing = reconstruct(demo_case(), DEMO_PLAN)
    with pytest.raises(dataclasses.FrozenInstanceError):
        timing.cycle_s = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        timing.slots[0].start_s = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        timing.groups[0].total_s = 1.0  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        timing.groups[0].windows[0].wraps = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Verde de cada grupo: sin doble conteo de solapes (QA02)
# ---------------------------------------------------------------------------


def test_the_greens_of_the_demo_plan_are_the_slots_of_each_group() -> None:
    timing = reconstruct(demo_case(), DEMO_PLAN)
    assert timing.greens_s == {"NS": 30.0, "EW": 22.0}


def test_the_greens_of_the_baseline_match_the_table_of_dev03() -> None:
    timing = reconstruct(baseline_case(), BASELINE)
    assert timing.greens_s == {
        "jp_este_oeste": 82.0,
        "jp_oeste_este_recto": 132.0,
        "jp_oeste_este_flecha": 45.0,
        "frutales_sur": 45.0,
        "frutales_norte": 60.0,
    }


def test_overlapping_groups_are_not_added_to_get_the_cycle() -> None:
    timing = reconstruct(baseline_case(), BASELINE)
    assert sum(group.total_s for group in timing.groups) == 82 + 132 + 45 + 45 + 60
    assert timing.cycle_s == 206.0
    assert timing.cycle_s != sum(group.total_s for group in timing.groups)


def test_a_slot_shared_by_two_groups_counts_in_each_group_but_once_in_the_cycle() -> None:
    case = build_case(["a", "b", "c"], {"x": ["a", "b"], "y": ["b", "c"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0, "c": 30.0})
    assert timing.greens_s == {"x": 30.0, "y": 50.0}
    assert timing.cycle_s == 60.0


def test_a_group_that_repeats_a_slot_counts_it_once() -> None:
    case = build_case(["a", "b"], {"x": ["a", "a", "b", "a"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0})
    assert timing.greens_s == {"x": 30.0}
    assert group_of(timing, "x").windows == (GreenWindow(("a", "b"), 0.0, 30.0, wraps=False),)


def test_a_group_with_an_unknown_slot_ignores_it() -> None:
    case = build_case(["a", "b"], {"x": ["a", "zzz"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0})
    assert timing.greens_s == {"x": 10.0}


def test_a_group_with_no_known_slot_has_no_green_and_no_windows() -> None:
    case = build_case(["a", "b"], {"x": ["zzz"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0})
    group = group_of(timing, "x")
    assert (group.total_s, group.windows) == (0.0, ())


def test_the_purpose_of_the_group_is_kept() -> None:
    data = copy.deepcopy(DEMO_CASE)
    data["green_groups"][0]["purpose"] = "pedestrian"
    timing = reconstruct(parse_case(data), DEMO_PLAN)
    assert [(group.group_id, group.purpose) for group in timing.groups] == [
        ("NS", "pedestrian"),
        ("EW", "vehicle"),
    ]


def test_the_order_of_the_groups_is_the_order_of_the_case() -> None:
    timing = reconstruct(baseline_case(), BASELINE)
    assert [group.group_id for group in timing.groups] == list(GROUPS_OF_BASELINE)


# ---------------------------------------------------------------------------
# Ventanas: seguidas, separadas y que cruzan el fin del ciclo
# ---------------------------------------------------------------------------


def test_consecutive_slots_form_one_window_with_its_start_and_duration() -> None:
    timing = reconstruct(baseline_case(), BASELINE)
    assert group_of(timing, "jp_oeste_este_recto").windows == (
        GreenWindow(("t1", "t2", "t3"), 0.0, 132.0, wraps=False),
    )
    assert group_of(timing, "frutales_norte").windows == (
        GreenWindow(("t5", "t6", "t7"), 137.0, 60.0, wraps=False),
    )


def test_a_single_slot_group_has_one_window_at_the_start_of_its_slot() -> None:
    timing = reconstruct(baseline_case(), BASELINE)
    assert group_of(timing, "jp_oeste_este_flecha").windows == (
        GreenWindow(("t3",), 87.0, 45.0, wraps=False),
    )


def test_separated_slots_make_separated_windows_and_the_total_does_not_include_the_gap() -> None:
    case = build_case(["a", "b", "c", "d"], {"x": ["a", "c"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0})
    group = group_of(timing, "x")
    assert group.total_s == 40.0
    assert group.windows == (
        GreenWindow(("a",), 0.0, 10.0, wraps=False),
        GreenWindow(("c",), 30.0, 30.0, wraps=False),
    )


def test_the_order_of_the_slots_in_the_group_does_not_change_its_windows() -> None:
    case = build_case(["a", "b", "c", "d"], {"x": ["c", "a"], "y": ["a", "c"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0})
    assert group_of(timing, "x").windows == group_of(timing, "y").windows


def test_the_last_and_the_first_slot_are_one_window_that_crosses_the_end_of_the_cycle() -> None:
    case = build_case(["a", "b", "c", "d"], {"x": ["d", "a"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0, "c": 30.0, "d": 40.0})
    group = group_of(timing, "x")
    assert group.total_s == 50.0
    assert group.windows == (GreenWindow(("d", "a"), 60.0, 50.0, wraps=True),)


def test_a_wrapping_group_with_a_slot_in_the_middle_lists_the_windows_by_start() -> None:
    case = build_case(["a", "b", "c", "d", "e"], {"x": ["a", "c", "e"]})
    timing = reconstruct(case, {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0})
    assert group_of(timing, "x").windows == (
        GreenWindow(("c",), 3.0, 3.0, wraps=False),
        GreenWindow(("e", "a"), 10.0, 6.0, wraps=True),
    )
    assert group_of(timing, "x").total_s == 9.0


def test_a_wrapping_window_can_have_several_slots_on_each_side() -> None:
    case = build_case(["a", "b", "c", "d", "e"], {"x": ["a", "b", "d", "e"]})
    timing = reconstruct(case, {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0})
    assert group_of(timing, "x").windows == (
        GreenWindow(("d", "e", "a", "b"), 6.0, 12.0, wraps=True),
    )


def test_only_the_first_or_only_the_last_slot_does_not_wrap() -> None:
    case = build_case(["a", "b", "c"], {"first": ["a"], "last": ["c"], "both_ends": ["a", "c"]})
    timing = reconstruct(case, {"a": 1.0, "b": 2.0, "c": 3.0})
    assert group_of(timing, "first").windows == (GreenWindow(("a",), 0.0, 1.0, wraps=False),)
    assert group_of(timing, "last").windows == (GreenWindow(("c",), 3.0, 3.0, wraps=False),)
    assert group_of(timing, "both_ends").windows == (GreenWindow(("c", "a"), 3.0, 4.0, wraps=True),)


def test_a_group_with_every_slot_is_one_window_that_does_not_wrap() -> None:
    case = build_case(["a", "b", "c"], {"all": ["c", "b", "a"]})
    timing = reconstruct(case, {"a": 1.0, "b": 2.0, "c": 3.0})
    group = group_of(timing, "all")
    assert group.total_s == timing.cycle_s == 6.0
    assert group.windows == (GreenWindow(("a", "b", "c"), 0.0, 6.0, wraps=False),)


def test_a_case_with_a_single_slot_works() -> None:
    case = build_case(["only"], {"x": ["only"]})
    timing = reconstruct(case, {"only": 7.0})
    assert timing.cycle_s == 7.0
    assert group_of(timing, "x").windows == (GreenWindow(("only",), 0.0, 7.0, wraps=False),)


def test_a_zero_duration_is_reconstructed_not_judged() -> None:
    case = build_case(["a", "b"], {"x": ["a", "b"]})
    timing = reconstruct(case, {"a": 0.0, "b": 5.0})
    assert timing.cycle_s == 5.0
    assert [(s.start_s, s.end_s) for s in timing.slots] == [(0.0, 0.0), (0.0, 5.0)]


def test_a_repeated_slot_id_in_the_case_uses_the_first_one() -> None:
    case = build_case(["a", "b", "a"], {"x": ["a"]})
    timing = reconstruct(case, {"a": 10.0, "b": 20.0})
    assert [slot.slot_id for slot in timing.slots] == ["a", "b"]
    assert timing.cycle_s == 30.0


# ---------------------------------------------------------------------------
# Aritmética exacta
# ---------------------------------------------------------------------------


def test_decimal_durations_add_up_exactly() -> None:
    case = build_case(["a", "b", "c"], {"x": ["a", "b", "c"]})
    timing = reconstruct(case, {"a": 0.1, "b": 0.2, "c": 0.4})
    assert timing.cycle_s == 0.7
    assert 0.1 + 0.2 + 0.4 != 0.7  # con decimales binarios daría 0.7000000000000001
    assert timing.slots[1].end_s == 0.3
    assert 0.1 + 0.2 != 0.3
    assert timing.greens_s == {"x": 0.7}


def test_the_start_of_a_window_is_exact() -> None:
    case = build_case(["a", "b", "c"], {"x": ["c"]})
    timing = reconstruct(case, {"a": 0.1, "b": 0.2, "c": 0.4})
    assert group_of(timing, "x").windows[0].start_s == 0.3


def test_very_large_durations_that_still_fit_are_reconstructed() -> None:
    case = build_case(["a", "b"], {"x": ["a"]})
    timing = reconstruct(case, {"a": 1e300, "b": 1e300})
    assert timing.cycle_s == 2e300


def test_durations_whose_sum_does_not_fit_in_a_number_are_rejected() -> None:
    case = build_case(["a", "b"], {"x": ["a"]})
    with pytest.raises(TimingInputError) as caught:
        reconstruct(case, {"a": 1.7e308, "b": 1.7e308})
    assert caught.value.issues[0].rule_id == INPUT_RULE
    assert caught.value.issues[0].field == "durations"
    assert "suman más de lo que cabe" in caught.value.issues[0].message


# ---------------------------------------------------------------------------
# Entrada hostil: falta, sobra, no es número, no es finito o es negativa
# ---------------------------------------------------------------------------

SLOTS = ["a", "b"]


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (float("nan"), "finito"),
        (float("inf"), "finito"),
        (float("-inf"), "finito"),
        (-1.0, "negativa"),
        (-1, "negativa"),
        (-1e-300, "negativa"),
        (True, "debe ser un número"),
        (False, "debe ser un número"),
        ("5", "debe ser un número"),
        (None, "debe ser un número"),
        ([5], "debe ser un número"),
        ({"a": 1}, "debe ser un número"),
        (1 + 2j, "debe ser un número"),
        (Fraction(5), "debe ser un número"),
        (Decimal(5), "debe ser un número"),
        (b"5", "debe ser un número"),
        (10**400, "demasiado grande"),
        (-(10**400), "demasiado grande"),
    ],
)
def test_a_value_that_is_not_a_valid_duration_is_reported(value: object, reason: str) -> None:
    issues = duration_issues(SLOTS, {"a": value, "b": 5.0})
    assert [(i.rule_id, i.field) for i in issues] == [(INPUT_RULE, "durations[a]")]
    assert reason in issues[0].message


def test_zero_and_negative_zero_are_valid_durations_for_the_input_check() -> None:
    assert duration_issues(SLOTS, {"a": 0, "b": -0.0}) == []


def test_a_valid_input_has_no_issues() -> None:
    assert duration_issues(SLOTS, {"a": 5, "b": 1e300}) == []


def test_a_missing_slot_is_reported() -> None:
    issues = duration_issues(SLOTS, {"a": 5.0})
    assert [(i.field, i.message) for i in issues] == [
        ("durations[b]", "falta la duración del slot")
    ]


def test_an_unknown_slot_is_reported_before_the_slots_of_the_case() -> None:
    issues = duration_issues(SLOTS, {"zzz": 1.0, "a": -1.0, "b": 5.0})
    assert [(i.field, i.message) for i in issues] == [
        ("durations[zzz]", "no es un slot esperado"),
        ("durations[a]", "no puede ser negativa"),
    ]


def test_every_problem_is_reported_together() -> None:
    issues = duration_issues(SLOTS, {"x": 1.0, "a": float("nan")})
    assert [i.field for i in issues] == ["durations[x]", "durations[a]", "durations[b]"]


def test_a_key_that_is_not_text_is_reported_as_unknown() -> None:
    issues = duration_issues(SLOTS, {1: 5.0, ("a",): 2.0, "a": 5.0, "b": 5.0})
    assert [(i.field, i.message) for i in issues] == [
        ("durations[1]", "no es un slot esperado"),
        ("durations[('a',)]", "no es un slot esperado"),
    ]


def test_an_empty_input_reports_every_slot() -> None:
    issues = duration_issues(SLOTS, {})
    assert [i.field for i in issues] == ["durations[a]", "durations[b]"]


@pytest.mark.parametrize("value", [None, [], [1.0, 2.0], "a", 5, 5.0, (("a", 1.0),)])
def test_an_input_that_is_not_a_mapping_is_reported_once(value: object) -> None:
    issues = duration_issues(SLOTS, value)
    assert [(i.rule_id, i.field) for i in issues] == [(INPUT_RULE, "durations")]
    assert "objeto" in issues[0].message


def test_a_very_long_key_is_shortened_in_the_message() -> None:
    issues = duration_issues(SLOTS, {"x" * 100_000: 1.0, "a": 1.0, "b": 1.0})
    assert len(issues[0].field or "") < 100
    assert (issues[0].field or "").endswith("…]")


def test_a_key_of_exactly_forty_characters_is_shown_whole_and_one_more_is_cut() -> None:
    whole = "k" * 40
    cut = "k" * 41
    assert (
        duration_issues(SLOTS, {whole: 1.0, "a": 1.0, "b": 1.0})[0].field == f"durations[{whole}]"
    )
    assert duration_issues(SLOTS, {cut: 1.0, "a": 1.0, "b": 1.0})[0].field == f"durations[{whole}…]"


def test_a_very_long_slot_id_of_the_case_is_shortened_too() -> None:
    issues = duration_issues(["y" * 100_000], {})
    assert len(issues[0].field or "") < 100


def test_the_issues_are_capped_and_the_last_one_counts_the_rest() -> None:
    slots = [f"s{index}" for index in range(1000)]
    issues = duration_issues(slots, {})
    assert len(issues) == MAX_ISSUES + 1
    assert issues[-1].field is None
    assert issues[-1].message == "y 900 problemas más sin mostrar"
    assert issues[-1].rule_id == INPUT_RULE


def test_one_issue_over_the_cap_is_counted_in_the_singular() -> None:
    slots = [f"s{index}" for index in range(MAX_ISSUES + 1)]
    issues = duration_issues(slots, {})
    assert len(issues) == MAX_ISSUES + 1
    assert issues[-1].message == "y 1 problema más sin mostrar"


def test_exactly_the_cap_has_no_omitted_line() -> None:
    slots = [f"s{index}" for index in range(MAX_ISSUES)]
    issues = duration_issues(slots, {})
    assert len(issues) == MAX_ISSUES
    assert all(issue.field is not None for issue in issues)


def test_reconstruct_rejects_the_input_with_the_error_of_the_domain() -> None:
    case = baseline_case()
    with pytest.raises(TimingInputError) as caught:
        reconstruct(case, {**BASELINE, "t3": float("nan"), "t9": -1.0})
    error = caught.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert error.field == "durations[t3]"
    assert [i.field for i in error.issues] == ["durations[t3]", "durations[t9]"]
    assert str(error) == (
        "INPUT_SCHEMA: las duraciones no son válidas: TIME-01 en durations[t3]: "
        "debe ser un número finito (sin NaN ni infinito) (y 1 más)"
    )


def test_the_message_of_a_single_issue_has_no_extra_count() -> None:
    with pytest.raises(TimingInputError) as caught:
        reconstruct(baseline_case(), {**BASELINE, "t3": True})
    assert "más)" not in str(caught.value)
    assert str(caught.value).endswith("TIME-01 en durations[t3]: debe ser un número")


def test_the_error_without_field_names_no_place() -> None:
    with pytest.raises(TimingInputError) as caught:
        reconstruct(baseline_case(), [1, 2, 3])  # type: ignore[arg-type]
    assert caught.value.field == "durations"


def test_an_error_needs_at_least_one_issue() -> None:
    with pytest.raises(ValueError, match="al menos un problema"):
        TimingInputError([])


def test_the_error_of_an_issue_without_field_does_not_say_where() -> None:
    error = TimingInputError([CaseIssue(INPUT_RULE, None, "algo")])
    assert str(error) == "INPUT_SCHEMA: las duraciones no son válidas: TIME-01: algo"
    assert error.field is None


def test_reconstruct_does_not_touch_the_input_when_it_rejects_it() -> None:
    plan = {**BASELINE, "t1": -3.0}
    before = dict(plan)
    with pytest.raises(TimingInputError):
        reconstruct(baseline_case(), plan)
    assert plan == before


# ---------------------------------------------------------------------------
# Propiedades con casos generados con semilla
# ---------------------------------------------------------------------------


def random_case(rng: random.Random) -> tuple[Case, dict[str, float]]:
    count = rng.randint(1, 9)
    slot_ids = [f"s{index}" for index in range(count)]
    groups = {
        f"g{index}": rng.sample(slot_ids, rng.randint(1, count))
        for index in range(rng.randint(1, 6))
    }
    durations = {slot_id: rng.randint(0, 300) / 10 for slot_id in slot_ids}
    return build_case(slot_ids, groups), durations


def exact(value: float) -> Fraction:
    return Fraction(repr(value))


@pytest.mark.parametrize("seed", range(300))
def test_the_reconstruction_keeps_its_invariants_on_generated_cases(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311 - casos de prueba, no seguridad
    case, durations = random_case(rng)
    timing = reconstruct(case, durations)
    order = [slot.id for slot in case.slots]
    cycle = sum((exact(durations[slot_id]) for slot_id in order), Fraction(0))
    assert exact(timing.cycle_s) == cycle
    # Los slots se siguen sin huecos ni solapes y llegan al final del ciclo.
    assert [s.slot_id for s in timing.slots] == order
    assert timing.slots[0].start_s == 0.0
    for before, after in zip(timing.slots, timing.slots[1:], strict=False):
        assert before.end_s == after.start_s
    assert timing.slots[-1].end_s == timing.cycle_s
    for slot in timing.slots:
        assert exact(slot.end_s) - exact(slot.start_s) == exact(durations[slot.slot_id])
    for group, source in zip(timing.groups, case.green_groups, strict=True):
        members = set(source.slot_ids)
        assert exact(group.total_s) == sum((exact(durations[m]) for m in members), Fraction(0))
        in_windows = [slot_id for window in group.windows for slot_id in window.slot_ids]
        # Las ventanas reparten los slots del grupo: ninguno falta ni se repite.
        assert sorted(in_windows) == sorted(members)
        assert sum((exact(w.duration_s) for w in group.windows), Fraction(0)) == exact(
            group.total_s
        )
        for window in group.windows:
            positions = [order.index(slot_id) for slot_id in window.slot_ids]
            steps = [(b - a) % len(order) for a, b in itertools.pairwise(positions)]
            assert all(step == 1 for step in steps)
            start = order.index(window.slot_ids[0])
            assert window.start_s == timing.slots[start].start_s
            assert window.wraps == (positions[-1] < positions[0])
        starts = [window.start_s for window in group.windows]
        assert starts == sorted(starts)


def test_the_generated_cases_cover_wrapping_and_separated_windows() -> None:
    wrapping = separated = 0
    for seed in range(300):
        case, durations = random_case(random.Random(seed))  # noqa: S311 - datos de prueba
        for group in reconstruct(case, durations).groups:
            wrapping += any(window.wraps for window in group.windows)
            separated += len(group.windows) > 1
    assert wrapping > 20
    assert separated > 20


def test_a_big_case_is_reconstructed_in_linear_time() -> None:
    count = 20_000
    slot_ids = [f"s{index}" for index in range(count)]
    case = build_case(slot_ids, {"even": slot_ids[::2], "all": slot_ids})
    durations = {slot_id: 1.5 for slot_id in slot_ids}
    started = time.perf_counter()
    timing = reconstruct(case, durations)
    assert time.perf_counter() - started < 10
    assert timing.cycle_s == 30_000.0
    assert group_of(timing, "even").total_s == 15_000.0
    assert len(group_of(timing, "even").windows) == count // 2
