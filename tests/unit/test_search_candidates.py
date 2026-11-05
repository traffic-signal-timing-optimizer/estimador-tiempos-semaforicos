"""Candidatos de la búsqueda de referencias (DEV14 F1, HU08, QA16 sin SUMO).

Datos sintéticos: la réplica de caso-001 de DEV13 (``timing_tools``) y un espacio pequeño que se
puede contar a mano.
"""

import itertools
import json
from typing import Any

import pytest

from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import PreparedCase, check_plan
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.search import (
    GRID_SCAN_LIMIT,
    SEARCH_VERSION,
    CandidateSet,
    generate_candidates,
)
from timing_tools import BASELINE, FIXED, LIMITS, VARIABLE_IDS, prepared

# Espacio pequeño: t1 80..82, t3 45..46, t5 44..45 y t7 10..12 (36 vectores). Los fijos suman 24 s,
# así que el ciclo va de 203 a 209 s; con un máximo de 206 s, los que suman más son inviables.
SMALL = {"t1": (80, 82), "t3": (45, 46), "t5": (44, 45), "t7": (10, 12)}
SMALL_CYCLE_MAX = 206


def _small(data: dict[str, Any]) -> None:
    for slot in data["slots"]:
        if slot["id"] in SMALL:
            slot["min_s"], slot["max_s"] = SMALL[slot["id"]]
    data["cycle_s"]["max"] = SMALL_CYCLE_MAX


def small_case() -> PreparedCase:
    return prepared(_small)


def small_feasible() -> list[tuple[int, ...]]:
    """Los vectores factibles del espacio pequeño, contados sin el módulo."""
    ranges = [range(SMALL[slot][0], SMALL[slot][1] + 1) for slot in VARIABLE_IDS]
    fixed = sum(FIXED.values())
    return [v for v in itertools.product(*ranges) if fixed + sum(v) <= SMALL_CYCLE_MAX]


def search(case: PreparedCase | None = None, **options: Any) -> CandidateSet:  # noqa: ANN401
    settings: dict[str, Any] = {
        "scenario_id": "ESC-1",
        "budget": 20,
        "attempt_limit": 2000,
        "seed": 1001,
    }
    settings.update(options)
    return generate_candidates(prepared() if case is None else case, **settings)


def vectors(result: CandidateSet) -> list[tuple[int, ...]]:
    return [tuple(c.ticks[slot] for slot in VARIABLE_IDS) for c in result.candidates]


def test_qa16_a_small_space_that_fits_the_budget_is_enumerated_in_full() -> None:
    expected = small_feasible()
    result = search(small_case(), budget=len(expected))
    assert result.method == "grid"
    assert vectors(result) == expected
    assert result.space_size == 36
    assert result.grid_feasible == len(expected)
    assert result.attempts == 36
    assert result.infeasible == 36 - len(expected)
    assert result.infeasible_by_rule == {"PLAN-04": 36 - len(expected)}
    assert result.duplicates == 0
    assert not result.exhausted
    assert all(c.origin == "grid" and c.consumes_budget for c in result.candidates)


def test_qa16_the_same_search_twice_gives_the_same_candidates() -> None:
    first = search(small_case(), budget=len(small_feasible()))
    second = search(small_case(), budget=len(small_feasible()))
    assert first == second
    assert first.trace() == second.trace()


def test_qa16_a_budget_smaller_than_the_grid_samples_and_is_respected() -> None:
    feasible = small_feasible()
    result = search(small_case(), budget=5)
    assert result.method == "sampling"
    assert result.grid_feasible == len(feasible)
    assert result.budget_used == 5
    assert set(vectors(result)) <= set(feasible)
    assert not result.exhausted


def test_qa16_sampling_is_repeatable_with_the_same_seed() -> None:
    assert search(seed=7) == search(seed=7)


def test_another_seed_or_scenario_gives_another_sample() -> None:
    base = vectors(search(seed=7))
    assert vectors(search(seed=8)) != base
    assert vectors(search(seed=7, scenario_id="ESC-2")) != base


def test_the_real_shaped_space_is_too_big_for_the_grid_and_is_sampled() -> None:
    result = search(budget=20)
    expected_size = 1
    for slot in VARIABLE_IDS:
        low, high = LIMITS[slot]
        expected_size *= int(high - low) + 1
    assert result.space_size == expected_size > GRID_SCAN_LIMIT
    assert result.grid_feasible is None
    assert result.method == "sampling"
    assert result.budget_used == 20


def test_every_sampled_candidate_is_feasible_unique_and_within_its_limits() -> None:
    case = prepared()
    result = search(case, budget=60)
    ids = [c.candidate_id for c in result.candidates]
    assert len(set(ids)) == len(ids) == 60
    assert len(set(vectors(result))) == 60
    for candidate in result.candidates:
        assert check_plan(case, candidate.durations_s).feasible
        assert list(candidate.durations_s) == list(BASELINE)
        for slot, (low, high) in LIMITS.items():
            assert low <= candidate.durations_s[slot] <= high
        for slot, value in FIXED.items():
            assert candidate.durations_s[slot] == value


def test_the_attempts_add_up_to_accepted_duplicates_and_infeasible() -> None:
    result = search(small_case(), budget=10, attempt_limit=500)
    assert result.attempts == result.budget_used + result.duplicates + result.infeasible
    assert sum(result.infeasible_by_rule.values()) == result.infeasible


def test_the_search_stops_at_the_attempt_limit_and_says_so() -> None:
    result = search(budget=20, attempt_limit=3)
    assert result.attempts == 3
    assert result.exhausted
    assert result.budget_used <= 3


def test_a_space_without_enough_feasible_plans_exhausts_the_attempts() -> None:
    feasible = small_feasible()
    result = search(small_case(), budget=len(feasible) - 1, attempt_limit=400)
    assert result.method == "sampling"
    # Hay más factibles que B: con 400 intentos sobre 36 vectores se llena B sin agotar.
    assert not result.exhausted
    full = search(small_case(), budget=len(feasible) + 1, attempt_limit=400)
    # Con B mayor que los factibles se enumera la grilla: no hace falta muestrear.
    assert full.method == "grid"
    assert full.budget_used == len(feasible)


def test_sampling_reaches_the_minimum_and_the_maximum_of_every_slot() -> None:
    result = search(small_case(), budget=len(small_feasible()) - 1, attempt_limit=2000)
    for index, slot in enumerate(VARIABLE_IDS):
        values = {vector[index] for vector in vectors(result)}
        assert values == set(range(SMALL[slot][0], SMALL[slot][1] + 1))


def test_the_current_plan_goes_first_and_does_not_consume_the_budget() -> None:
    result = search(budget=20, current_plan=BASELINE)
    first = result.candidates[0]
    assert first.origin == "current_plan"
    assert not first.consumes_budget
    assert dict(first.durations_s) == BASELINE
    assert result.current_plan == "included"
    assert len(result.candidates) == 21
    assert result.budget_used == 20


def test_a_sampled_copy_of_the_current_plan_is_a_duplicate() -> None:
    feasible = small_feasible()
    current = dict(FIXED) | dict(zip(VARIABLE_IDS, map(float, feasible[0]), strict=True))
    result = search(small_case(), budget=len(feasible) - 1, current_plan=current)
    assert result.method == "grid"
    assert result.duplicates == 1
    assert vectors(result) == feasible
    assert result.budget_used == len(feasible) - 1


def test_an_infeasible_current_plan_is_excluded_with_its_rules() -> None:
    result = search(budget=5, current_plan=BASELINE | {"t1": 200.0})
    assert result.current_plan == "excluded"
    assert result.current_plan_violated == ("PLAN-02",)
    assert all(c.origin == "sampled" for c in result.candidates)


def test_a_current_plan_with_missing_slots_is_excluded_not_an_error() -> None:
    plan = {key: value for key, value in BASELINE.items() if key != "t9"}
    result = search(budget=5, current_plan=plan)
    assert result.current_plan == "excluded"
    assert result.current_plan_violated == ("TIME-01",)


def test_without_a_current_plan_it_is_declared_absent() -> None:
    result = search(budget=5)
    assert result.current_plan == "absent"
    assert result.current_plan_violated == ()


WEBSTER = BASELINE | {"t1": 90.0, "t3": 40.0}


def test_a_webster_plan_goes_after_the_current_plan_and_does_not_consume_the_budget() -> None:
    result = search(budget=20, current_plan=BASELINE, webster_plan=WEBSTER)
    assert [c.origin for c in result.candidates[:2]] == ["current_plan", "webster"]
    webster = result.candidates[1]
    assert not webster.consumes_budget
    assert dict(webster.durations_s) == WEBSTER
    assert result.webster == "included"
    assert result.webster_violated == ()
    assert len(result.candidates) == 22
    assert result.budget_used == 20


def test_a_webster_plan_alone_goes_first() -> None:
    result = search(budget=5, webster_plan=WEBSTER)
    assert result.candidates[0].origin == "webster"
    assert result.current_plan == "absent"
    assert result.webster == "included"


def test_a_webster_plan_equal_to_the_current_plan_is_a_duplicate_and_not_evaluated_twice() -> None:
    result = search(budget=5, current_plan=BASELINE, webster_plan=BASELINE)
    assert result.webster == "duplicate"
    assert [c.origin for c in result.candidates].count("current_plan") == 1
    assert "webster" not in [c.origin for c in result.candidates]
    assert result.budget_used == 5


def test_a_sampled_copy_of_the_webster_plan_is_a_duplicate() -> None:
    feasible = small_feasible()
    plan = dict(FIXED) | dict(zip(VARIABLE_IDS, map(float, feasible[0]), strict=True))
    result = search(small_case(), budget=len(feasible) - 1, webster_plan=plan)
    assert result.method == "grid"
    assert result.duplicates == 1
    assert vectors(result) == feasible
    assert result.budget_used == len(feasible) - 1


def test_an_infeasible_webster_plan_is_excluded_with_its_rules() -> None:
    result = search(budget=5, webster_plan=BASELINE | {"t1": 200.0})
    assert result.webster == "excluded"
    assert result.webster_violated == ("PLAN-02",)
    assert all(c.origin == "sampled" for c in result.candidates)


def test_a_webster_plan_with_missing_slots_is_excluded_not_an_error() -> None:
    plan = {key: value for key, value in WEBSTER.items() if key != "t9"}
    result = search(budget=5, webster_plan=plan)
    assert result.webster == "excluded"
    assert result.webster_violated == ("TIME-01",)


def test_without_a_webster_plan_the_trace_is_the_same_as_before() -> None:
    trace = search(budget=4, current_plan=BASELINE).trace()
    assert "webster" not in trace
    assert search(budget=4, webster_plan=None).webster == "absent"


def test_the_trace_records_the_webster_plan_only_when_one_is_given() -> None:
    assert search(budget=4, webster_plan=WEBSTER).trace()["webster"] == {
        "status": "included",
        "violated": [],
    }
    excluded = search(budget=4, webster_plan=BASELINE | {"t1": 200.0}).trace()
    assert excluded["webster"] == {"status": "excluded", "violated": ["PLAN-02"]}
    duplicate = search(budget=4, current_plan=BASELINE, webster_plan=BASELINE).trace()
    assert duplicate["webster"] == {"status": "duplicate", "violated": []}


def test_a_webster_plan_changes_the_trace_and_so_the_identity_of_the_search() -> None:
    plain = search(budget=4, current_plan=BASELINE)
    with_webster = search(budget=4, current_plan=BASELINE, webster_plan=WEBSTER)
    assert plain.trace() != with_webster.trace()
    assert plain.trace()["candidates"] != with_webster.trace()["candidates"]


def test_the_identifier_depends_on_the_plan_not_on_its_origin() -> None:
    grid = search(small_case(), budget=len(small_feasible()))
    current = grid.candidates[3]
    plan = dict(current.durations_s)
    other = search(small_case(), budget=len(small_feasible()), current_plan=plan)
    assert other.candidates[0].candidate_id == current.candidate_id
    assert other.candidates[0].origin == "current_plan"


def test_a_half_second_tick_gives_durations_on_that_tick() -> None:
    def half(data: dict[str, Any]) -> None:
        data["tick_s"] = 0.5

    case = prepared(half)
    result = search(case, budget=30)
    for candidate in result.candidates:
        assert check_plan(case, candidate.durations_s).feasible
        for slot in VARIABLE_IDS:
            assert (candidate.durations_s[slot] * 2).is_integer()
    assert any(not c.durations_s["t1"].is_integer() for c in result.candidates)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("budget", 0),
        ("budget", -1),
        ("budget", True),
        ("budget", 2.0),
        ("budget", "20"),
        ("attempt_limit", 0),
        ("attempt_limit", False),
        ("seed", 1.5),
        ("seed", True),
        ("seed", "1001"),
        ("scenario_id", ""),
        ("scenario_id", None),
    ],
)
def test_invalid_parameters_are_rejected_with_their_field(field: str, value: object) -> None:
    options: dict[str, Any] = {field: value}
    with pytest.raises(ReferenciasError) as caught:
        search(**options)
    assert caught.value.code == ErrorCode.INPUT_SCHEMA
    assert caught.value.field == field


def test_a_huge_invalid_value_is_shown_shortened() -> None:
    with pytest.raises(ReferenciasError) as caught:
        search(budget="x" * 10_000)
    assert len(str(caught.value)) < 300


def test_a_negative_or_zero_seed_is_valid() -> None:
    assert search(seed=0).budget_used == 20
    assert search(seed=-5) != search(seed=5)


def test_the_trace_is_json_with_every_candidate_and_count() -> None:
    result = search(budget=4, current_plan=BASELINE)
    trace = result.trace()
    again = json.loads(json.dumps(trace, ensure_ascii=False))
    assert again == trace
    assert trace["search_version"] == SEARCH_VERSION
    assert trace["budget_counts"] == "unique_feasible_search_candidates"
    assert trace["budget"] == 4
    assert trace["budget_used"] == 4
    assert trace["grid_scan_limit"] == GRID_SCAN_LIMIT
    assert trace["current_plan"] == {"status": "included", "violated": []}
    assert trace["rules_version"] == prepared().rules_version
    assert len(trace["candidates"]) == 5  # type: ignore[arg-type]
    first = trace["candidates"][0]  # type: ignore[index]
    assert first["origin"] == "current_plan"
    assert first["ticks"] == {"t1": 82, "t3": 45, "t5": 45, "t7": 10}


def test_changing_the_case_limits_changes_the_sample() -> None:
    def narrower(data: dict[str, Any]) -> None:
        data["slots"][0]["max_s"] = 100

    assert vectors(search(prepared(narrower))) != vectors(search())


def test_an_infeasible_plan_is_counted_by_the_first_rule_it_breaks() -> None:
    # Con el verde de Frutales norte (t5 + t6 + t7) hasta 60 s, algunos vectores violan el ciclo
    # y el grupo a la vez: cuentan en PLAN-04, que se evalúa primero.
    def both(data: dict[str, Any]) -> None:
        _small(data)
        for group in data["green_groups"]:
            if group["id"] == "frutales_norte":
                group["max_s"] = 60

    ranges = [range(SMALL[slot][0], SMALL[slot][1] + 1) for slot in VARIABLE_IDS]
    fixed = sum(FIXED.values())
    expected: dict[str, int] = {}
    for t1, t3, t5, t7 in itertools.product(*ranges):
        if fixed + t1 + t3 + t5 + t7 > SMALL_CYCLE_MAX:
            expected["PLAN-04"] = expected.get("PLAN-04", 0) + 1
        elif t5 + FIXED["t6"] + t7 > 60:
            expected["PLAN-05"] = expected.get("PLAN-05", 0) + 1
    result = search(prepared(both), budget=36)
    assert result.method == "grid"
    assert set(expected) == {"PLAN-04", "PLAN-05"}
    assert result.infeasible_by_rule == expected


def test_a_current_plan_with_tolerated_noise_keeps_its_nearest_tick() -> None:
    noisy = BASELINE | {"t1": 81.9999999}
    result = search(budget=3, current_plan=noisy)
    assert result.current_plan == "included"
    assert result.candidates[0].ticks["t1"] == 82
    assert result.candidates[0].durations_s["t1"] == 82.0


def test_the_trace_counts_what_was_used_when_the_attempts_run_out() -> None:
    trace = search(budget=20, attempt_limit=3).trace()
    assert trace["budget"] == 20
    assert trace["exhausted"] is True
    assert trace["budget_used"] == len(trace["candidates"]) <= 3  # type: ignore[arg-type]


def test_the_trace_keeps_the_rules_an_excluded_current_plan_breaks() -> None:
    trace = search(budget=2, current_plan=BASELINE | {"t1": 200.0}).trace()
    assert trace["current_plan"] == {"status": "excluded", "violated": ["PLAN-02"]}


def test_a_small_space_sample_repeats_vectors_but_keeps_each_plan_once() -> None:
    result = search(small_case(), budget=len(small_feasible()) - 1, attempt_limit=2000)
    assert result.method == "sampling"
    assert result.duplicates > 0
    found = vectors(result)
    assert len(found) == len(set(found)) == result.budget_used
