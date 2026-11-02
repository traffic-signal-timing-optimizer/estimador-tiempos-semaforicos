"""Comparar la demora de dos corridas sin la media sesgada de los completados (DEV19 F4; QA26)."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from semaforo.dominio.case import Case, parse_case
from semaforo.evaluacion.cohort import CohortDelay, cohort_delay, compare_cohorts
from semaforo.simulacion.reconcile import Reconciliation, Status, VehicleOutcome
from semaforo.simulacion.tripinfo import Trip

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TOLERANCE = 1e-8
VEHICLES = [("v1", "N_S"), ("v2", "N_S"), ("v3", "E_W"), ("v4", "E_W")]


def case() -> Case:
    return parse_case(json.loads((FIXTURES / "case.json").read_text(encoding="utf-8")))


def run(
    results: Mapping[str, tuple[Status, float]], vehicles: list[tuple[str, str]] = VEHICLES
) -> CohortDelay:
    """Una corrida: para cada vehículo, su estado y su demora (pérdida o espera)."""
    outcomes: list[VehicleOutcome] = []
    trips: dict[str, Trip] = {}
    for vehicle_id, movement in vehicles:
        status, delay = results[vehicle_id]
        outcomes.append(
            VehicleOutcome(
                vehicle_id=vehicle_id,
                movement_id=movement,
                vehicle_class="car",
                in_cohort=True,
                scheduled_s=10.0,
                status=status,
                inserted_s=None if status == "not_inserted" else 10.0,
                arrival_s=70.0 if status == "finished" else None,
            )
        )
        if status == "not_inserted":
            trips[vehicle_id] = Trip(-1.0, -1.0, time_loss=0.0, depart_delay=delay)
        else:
            arrival = 70.0 if status == "finished" else -1.0
            trips[vehicle_id] = Trip(10.0, arrival, time_loss=delay, depart_delay=0.0)
    counts = {
        s: sum(1 for o in outcomes if o.status == s)
        for s in ("finished", "unfinished", "not_inserted")
    }
    reconciliation = Reconciliation(
        outcomes=outcomes,
        counts=[],
        requested=len(outcomes),
        finished=counts["finished"],
        unfinished=counts["unfinished"],
        not_inserted=counts["not_inserted"],
    )
    return cohort_delay(reconciliation, trips, case(), 1000.0)


def all_finished(delay: float) -> dict[str, tuple[Status, float]]:
    return {vehicle_id: ("finished", delay) for vehicle_id, _ in VEHICLES}


# --- QA26: un plan que solo deja pasar a los rápidos ------------------------------------------


def test_qa26_the_plan_that_serves_only_fast_vehicles_is_not_declared_better() -> None:
    """A deja terminar a 2 rápidos (5 s) y deja a 2 sin entrar 400 s; B atiende a todos (20 s).

    La media de los que terminaron diría que A es mejor (5 < 20). La cota inferior de A es
    (5 + 5 + 400 + 400) / 4 = 202.5 s, mayor que los 20 s de B: B es menor con certeza.
    """
    only_fast = run(
        {
            "v1": ("finished", 5.0),
            "v2": ("not_inserted", 400.0),
            "v3": ("finished", 5.0),
            "v4": ("not_inserted", 400.0),
        }
    )
    serves_all = run(all_finished(20.0))
    result = compare_cohorts(only_fast, serves_all, TOLERANCE)
    assert result.total.verdict == "b_lower"
    assert result.total.verdict != "a_lower"
    assert result.total.difference_s is None
    assert only_fast.total.lower_bound_mean_delay_s == pytest.approx(202.5)


def test_qa26_when_the_bound_is_not_enough_the_answer_is_undetermined() -> None:
    """Si los que no entraron esperaron poco, la cota de A (10 s) no supera los 20 s de B."""
    only_fast = run(
        {
            "v1": ("finished", 5.0),
            "v2": ("not_inserted", 15.0),
            "v3": ("finished", 5.0),
            "v4": ("not_inserted", 15.0),
        }
    )
    result = compare_cohorts(only_fast, run(all_finished(20.0)), TOLERANCE)
    assert result.total.verdict == "undetermined"
    assert "censurada" in result.total.reason


def test_qa26_the_censoring_is_visible_in_the_comparison() -> None:
    only_fast = run(
        {
            "v1": ("finished", 5.0),
            "v2": ("unfinished", 300.0),
            "v3": ("finished", 5.0),
            "v4": ("not_inserted", 400.0),
        }
    )
    result = compare_cohorts(only_fast, run(all_finished(20.0)), TOLERANCE)
    side = result.total.a
    assert (side.status, side.unfinished, side.not_inserted, side.mean_delay_s) == (
        "censored",
        1,
        1,
        None,
    )
    assert result.total.b.status == "complete"


# --- las demás reglas ------------------------------------------------------------------------


def test_two_complete_cohorts_give_the_difference_of_means() -> None:
    result = compare_cohorts(run(all_finished(12.0)), run(all_finished(20.0)), TOLERANCE)
    assert (result.total.verdict, result.total.difference_s) == ("a_lower", -8.0)
    assert result.same_cohort is True
    reverse = compare_cohorts(run(all_finished(20.0)), run(all_finished(12.0)), TOLERANCE)
    assert (reverse.total.verdict, reverse.total.difference_s) == ("b_lower", 8.0)


def test_means_within_the_tolerance_are_equal() -> None:
    result = compare_cohorts(run(all_finished(20.0)), run(all_finished(20.05)), 0.1)
    assert result.total.verdict == "equal"
    assert result.total.difference_s == pytest.approx(-0.05)
    assert (
        compare_cohorts(run(all_finished(20.0)), run(all_finished(20.05)), 0.01).total.verdict
        == "a_lower"
    )


def test_a_difference_equal_to_the_tolerance_is_still_equal() -> None:
    result = compare_cohorts(run(all_finished(20.0)), run(all_finished(20.5)), 0.5)
    assert (result.total.verdict, result.total.difference_s) == ("equal", -0.5)


def test_two_censored_cohorts_are_undetermined() -> None:
    censored: dict[str, tuple[Status, float]] = {
        "v1": ("finished", 5.0),
        "v2": ("unfinished", 50.0),
        "v3": ("finished", 5.0),
        "v4": ("finished", 5.0),
    }
    result = compare_cohorts(run(censored), run(censored), TOLERANCE)
    assert result.total.verdict == "undetermined"
    assert result.total.difference_s is None


def test_the_complete_side_wins_whichever_position_it_has() -> None:
    censored = run(
        {
            "v1": ("not_inserted", 500.0),
            "v2": ("finished", 1.0),
            "v3": ("finished", 1.0),
            "v4": ("finished", 1.0),
        }
    )
    complete = run(all_finished(20.0))
    assert compare_cohorts(complete, censored, TOLERANCE).total.verdict == "a_lower"
    assert compare_cohorts(censored, complete, TOLERANCE).total.verdict == "b_lower"


def test_a_bound_equal_to_the_complete_mean_does_not_decide() -> None:
    censored = run(
        {
            "v1": ("not_inserted", 77.0),
            "v2": ("finished", 1.0),
            "v3": ("finished", 1.0),
            "v4": ("finished", 1.0),
        }
    )
    assert censored.total.lower_bound_mean_delay_s == pytest.approx(20.0)
    assert (
        compare_cohorts(run(all_finished(20.0)), censored, TOLERANCE).total.verdict
        == "undetermined"
    )


def test_each_access_is_compared_on_its_own() -> None:
    a = run(
        {
            "v1": ("finished", 10.0),
            "v2": ("finished", 10.0),
            "v3": ("unfinished", 5.0),
            "v4": ("finished", 1.0),
        }
    )
    result = compare_cohorts(a, run(all_finished(20.0)), TOLERANCE)
    assert result.by_access["N"].verdict == "a_lower"
    assert result.by_access["N"].difference_s == -10.0
    assert result.by_access["E"].verdict == "undetermined"
    assert result.total.verdict == "undetermined"


def test_different_cohorts_are_not_comparable() -> None:
    other_results: dict[str, tuple[Status, float]] = {
        "v1": ("finished", 1.0),
        "v2": ("finished", 1.0),
        "v3": ("finished", 1.0),
        "x": ("finished", 1.0),
    }
    other = run(other_results, vehicles=[("v1", "N_S"), ("v2", "N_S"), ("v3", "E_W"), ("x", "E_W")])
    result = compare_cohorts(run(all_finished(20.0)), other, TOLERANCE)
    assert (result.same_cohort, result.total.verdict) == (False, "not_comparable")
    assert result.by_access == {}


def test_a_vehicle_moved_to_another_movement_makes_the_cohorts_different() -> None:
    moved = run(
        all_finished(1.0), vehicles=[("v1", "E_W"), ("v2", "N_S"), ("v3", "E_W"), ("v4", "E_W")]
    )
    assert compare_cohorts(run(all_finished(20.0)), moved, TOLERANCE).same_cohort is False


def test_an_empty_side_is_not_comparable() -> None:
    empty = run({}, vehicles=[])
    result = compare_cohorts(empty, empty, TOLERANCE)
    assert result.same_cohort is True
    assert result.total.verdict == "not_comparable"
