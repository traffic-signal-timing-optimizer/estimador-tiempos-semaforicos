"""Demora de la cohorte y su censura (DEV19 F2; QA25), con cifras calculadas a mano."""

import json
import math
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.protocol import parse_protocol
from semaforo.evaluacion.cohort import (
    CohortDelay,
    VehicleDelay,
    cohort_delay,
    require_supported,
    summarize_delays,
)
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.simulacion.reconcile import Reconciliation, Status, VehicleOutcome
from semaforo.simulacion.tripinfo import Trip

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
END_S = 1000.0


def case() -> Case:
    return parse_case(json.loads((FIXTURES / "case.json").read_text(encoding="utf-8")))


def outcome(  # noqa: PLR0913 - cada argumento es un dato del vehículo
    vehicle_id: str,
    status: Status,
    *,
    movement: str = "N_S",
    vehicle_class: str = "car",
    in_cohort: bool = True,
    scheduled: float = 100.0,
) -> VehicleOutcome:
    inserted = None if status == "not_inserted" else scheduled
    return VehicleOutcome(
        vehicle_id=vehicle_id,
        movement_id=movement,
        vehicle_class=vehicle_class,
        in_cohort=in_cohort,
        scheduled_s=scheduled,
        status=status,
        inserted_s=inserted,
        arrival_s=scheduled + 60 if status == "finished" else None,
    )


def reconciliation(*outcomes: VehicleOutcome) -> Reconciliation:
    cohort = [item for item in outcomes if item.in_cohort]
    return Reconciliation(
        outcomes=list(outcomes),
        counts=[],
        requested=len(cohort),
        finished=sum(1 for item in cohort if item.status == "finished"),
        unfinished=sum(1 for item in cohort if item.status == "unfinished"),
        not_inserted=sum(1 for item in cohort if item.status == "not_inserted"),
    )


def finished(loss: float, wait: float = 0.0) -> Trip:
    return Trip(100.0, 160.0, time_loss=loss, depart_delay=wait)


def running(loss: float, wait: float = 0.0) -> Trip:
    return Trip(100.0, -1.0, time_loss=loss, depart_delay=wait)


def waiting(wait: float) -> Trip:
    return Trip(-1.0, -1.0, time_loss=0.0, depart_delay=wait)


def measure(trips: dict[str, Trip], *outcomes: VehicleOutcome) -> CohortDelay:
    return cohort_delay(reconciliation(*outcomes), trips, case(), END_S)


# --- cohorte completa ------------------------------------------------------------------------


def test_a_complete_cohort_has_its_mean_and_both_parts() -> None:
    result = measure(
        {"a": finished(10.0, 2.0), "b": finished(20.0, 0.0), "c": finished(30.0, 4.0)},
        outcome("a", "finished"),
        outcome("b", "finished"),
        outcome("c", "finished", movement="E_W"),
    )
    total = result.total
    assert (total.status, total.requested, total.finished) == ("complete", 3, 3)
    assert total.mean_delay_s == pytest.approx(66.0 / 3)
    assert total.mean_time_loss_s == pytest.approx(20.0)
    assert total.mean_depart_delay_s == pytest.approx(2.0)
    assert total.sum_delay_s == pytest.approx(66.0)
    assert total.lower_bound_mean_delay_s is None
    assert total.lower_bound_mean_time_loss_s is None
    assert total.lower_bound_mean_depart_delay_s is None


def test_zeros_count_in_the_mean() -> None:
    result = measure(
        {"a": finished(0.0), "b": finished(0.0), "c": finished(9.0)},
        outcome("a", "finished"),
        outcome("b", "finished"),
        outcome("c", "finished"),
    )
    assert result.total.mean_delay_s == pytest.approx(3.0)


def test_the_cohort_is_split_by_access_and_movement() -> None:
    result = measure(
        {"a": finished(10.0), "b": finished(20.0), "c": finished(30.0)},
        outcome("a", "finished"),
        outcome("b", "finished"),
        outcome("c", "finished", movement="E_W"),
    )
    assert sorted(result.by_access) == ["E", "N"]
    assert result.by_access["N"].mean_delay_s == pytest.approx(15.0)
    assert result.by_access["E"].mean_delay_s == pytest.approx(30.0)
    assert sorted(result.by_movement) == ["E_W", "N_S"]
    assert result.by_movement["N_S"].requested == 2
    assert [vehicle.access_id for vehicle in result.vehicles] == ["N", "N", "E"]


# --- cohorte censurada -----------------------------------------------------------------------


def test_one_unfinished_vehicle_censors_the_cohort_and_gives_only_a_lower_bound() -> None:
    result = measure(
        {"a": finished(10.0), "b": finished(20.0), "c": running(300.0, 5.0)},
        outcome("a", "finished"),
        outcome("b", "finished"),
        outcome("c", "unfinished"),
    )
    total = result.total
    assert (total.status, total.finished, total.unfinished) == ("censored", 2, 1)
    assert total.mean_delay_s is None
    assert total.mean_time_loss_s is None
    assert total.mean_depart_delay_s is None
    assert total.lower_bound_mean_delay_s == pytest.approx(335.0 / 3)
    assert total.lower_bound_mean_time_loss_s == pytest.approx(110.0)
    assert total.lower_bound_mean_depart_delay_s == pytest.approx(5.0 / 3)


def test_the_lower_bound_divides_by_all_requested_not_by_those_that_finished() -> None:
    result = measure(
        {"a": finished(10.0), "b": waiting(50.0)},
        outcome("a", "finished"),
        outcome("b", "not_inserted"),
    )
    assert result.total.lower_bound_mean_delay_s == pytest.approx(30.0)
    assert result.total.lower_bound_mean_delay_s != pytest.approx(10.0)


def test_a_vehicle_that_never_entered_keeps_the_wait_sumo_recorded() -> None:
    result = measure({"a": waiting(386.0)}, outcome("a", "not_inserted"))
    vehicle = result.vehicles[0]
    assert (vehicle.status, vehicle.time_loss_s, vehicle.depart_delay_s) == (
        "not_inserted",
        0.0,
        386.0,
    )
    assert vehicle.depart_delay_source == "sumo"


def test_without_a_record_the_wait_is_the_end_minus_the_scheduled_departure() -> None:
    result = measure({}, outcome("a", "not_inserted", scheduled=250.0))
    vehicle = result.vehicles[0]
    assert vehicle.depart_delay_s == END_S - 250.0
    assert vehicle.depart_delay_source == "schedule"


def test_a_departure_scheduled_after_the_end_waited_nothing() -> None:
    result = measure({}, outcome("a", "not_inserted", scheduled=END_S + 30))
    assert result.vehicles[0].depart_delay_s == 0.0


def test_a_censored_access_does_not_censor_a_complete_one() -> None:
    result = measure(
        {"a": finished(10.0), "b": running(40.0)},
        outcome("a", "finished", movement="E_W"),
        outcome("b", "unfinished"),
    )
    assert result.by_access["E"].status == "complete"
    assert result.by_access["E"].mean_delay_s == pytest.approx(10.0)
    assert result.by_access["N"].status == "censored"
    assert result.by_access["N"].mean_delay_s is None
    assert result.total.status == "censored"


# --- población y denominadores (QA25) --------------------------------------------------------


def test_warmup_vehicles_are_counted_apart_and_never_in_a_denominator() -> None:
    result = measure(
        {"w": running(999.0), "a": finished(10.0)},
        outcome("w", "unfinished", in_cohort=False),
        outcome("a", "finished"),
    )
    assert result.warmup_vehicles == 1
    assert (result.total.requested, result.total.status) == (1, "complete")
    assert [vehicle.vehicle_id for vehicle in result.vehicles] == ["a"]


def test_an_empty_cohort_has_no_figures() -> None:
    result = measure({"w": finished(1.0)}, outcome("w", "finished", in_cohort=False))
    total = result.total
    assert (total.status, total.requested, total.sum_delay_s) == ("empty", 0, 0.0)
    assert total.mean_delay_s is None
    assert total.lower_bound_mean_delay_s is None
    assert result.by_access == {}


def test_every_requested_vehicle_is_kept_and_the_groups_add_up() -> None:
    outcomes = [
        outcome("a", "finished"),
        outcome("b", "unfinished"),
        outcome("c", "not_inserted"),
        outcome("d", "finished", movement="E_W"),
        outcome("e", "not_inserted", movement="E_W", vehicle_class="bus"),
    ]
    trips = {"a": finished(5.0), "b": running(7.0), "d": finished(1.0), "e": waiting(3.0)}
    result = measure(trips, *outcomes)
    assert [vehicle.vehicle_id for vehicle in result.vehicles] == ["a", "b", "c", "d", "e"]
    for groups in (result.by_access, result.by_movement):
        assert sum(group.requested for group in groups.values()) == 5
        assert sum(group.finished for group in groups.values()) == 2
        assert sum(group.unfinished for group in groups.values()) == 1
        assert sum(group.not_inserted for group in groups.values()) == 2
        assert math.fsum(group.sum_delay_s for group in groups.values()) == pytest.approx(
            result.total.sum_delay_s
        )


# --- incoherencias: nunca cifras a medias ----------------------------------------------------


def refused(trips: dict[str, Trip], *outcomes: VehicleOutcome, match: str) -> None:
    with pytest.raises(EvaluacionError, match=match) as raised:
        measure(trips, *outcomes)
    assert raised.value.code is ErrorCode.OUTPUT_INVALID


def test_a_finished_vehicle_without_trip_is_refused() -> None:
    refused({}, outcome("a", "finished"), match="no coinciden")


def test_a_finished_vehicle_whose_trip_never_departed_is_refused() -> None:
    refused({"a": waiting(3.0)}, outcome("a", "finished"), match="no coinciden")


def test_a_not_inserted_vehicle_whose_trip_departed_is_refused() -> None:
    refused({"a": finished(3.0)}, outcome("a", "not_inserted"), match="no coinciden")


@pytest.mark.parametrize(
    "trip",
    [
        Trip(100.0, 160.0, time_loss=None, depart_delay=0.0),
        Trip(100.0, 160.0, time_loss=1.0, depart_delay=None),
    ],
)
def test_a_trip_without_its_times_is_refused(trip: Trip) -> None:
    refused({"a": trip}, outcome("a", "finished"), match="le falta")


def test_a_waiting_record_without_its_wait_is_refused() -> None:
    refused({"a": Trip(-1.0, -1.0)}, outcome("a", "not_inserted"), match="le falta departDelay")


@pytest.mark.parametrize(
    "trip",
    [
        Trip(100.0, 160.0, time_loss=-0.01, depart_delay=0.0),
        Trip(100.0, 160.0, time_loss=1.0, depart_delay=-1.0),
    ],
)
def test_a_negative_time_is_refused(trip: Trip) -> None:
    refused({"a": trip}, outcome("a", "finished"), match="negativo")


def test_a_movement_of_another_case_is_refused() -> None:
    refused({"a": finished(1.0)}, outcome("a", "finished", movement="X_Y"), match="no es del caso")


def test_counts_that_do_not_match_their_vehicles_are_refused() -> None:
    wrong = reconciliation(outcome("a", "finished")).model_copy(update={"requested": 2})
    with pytest.raises(EvaluacionError, match="conteos"):
        cohort_delay(wrong, {"a": finished(1.0)}, case(), END_S)


# --- protocolo admitido ----------------------------------------------------------------------


def fixture_protocol(**changes: object) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "protocol.json").read_text(encoding="utf-8"))
    data.update(changes)
    return data


def test_the_fixture_protocol_is_supported() -> None:
    require_supported(parse_protocol(fixture_protocol()))


def test_another_population_is_not_supported() -> None:
    with pytest.raises(EvaluacionError, match="población") as raised:
        require_supported(parse_protocol(fixture_protocol(cohort_policy="todos_los_vehiculos")))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "cohort_policy"


def test_an_alternative_censoring_rule_is_not_supported_yet() -> None:
    protocol = parse_protocol(
        fixture_protocol(
            censoring_policy="approved_alternative", alternate_censoring_rule="penalizar"
        )
    )
    with pytest.raises(EvaluacionError, match="censura") as raised:
        require_supported(protocol)
    assert raised.value.field == "censoring_policy"


# --- propiedades -----------------------------------------------------------------------------

STATUSES: list[Status] = ["finished", "unfinished", "not_inserted"]


@st.composite
def vehicles(draw: st.DrawFn) -> list[VehicleDelay]:
    count = draw(st.integers(min_value=0, max_value=30))
    times = st.floats(min_value=0, max_value=1e4, allow_nan=False)
    result: list[VehicleDelay] = []
    for index in range(count):
        status = draw(st.sampled_from(STATUSES))
        result.append(
            VehicleDelay(
                vehicle_id=f"v{index}",
                movement_id="N_S",
                vehicle_class="car",
                access_id="N",
                status=status,
                time_loss_s=0.0 if status == "not_inserted" else draw(times),
                depart_delay_s=draw(times),
                depart_delay_source="sumo",
            )
        )
    return result


@settings(max_examples=300, deadline=None)
@given(vehicles())
def test_a_summary_has_a_mean_only_when_complete_and_a_bound_only_when_censored(
    group: list[VehicleDelay],
) -> None:
    summary = summarize_delays(group)
    assert summary.requested == len(group)
    assert summary.finished + summary.unfinished + summary.not_inserted == len(group)
    complete = bool(group) and all(vehicle.status == "finished" for vehicle in group)
    assert (summary.mean_delay_s is not None) is complete
    assert (summary.lower_bound_mean_delay_s is not None) is (bool(group) and not complete)
    figure = summary.mean_delay_s if complete else summary.lower_bound_mean_delay_s
    if group:
        assert figure is not None
        assert figure * len(group) == pytest.approx(summary.sum_delay_s, rel=1e-9, abs=1e-6)
        parts = (
            (summary.mean_time_loss_s, summary.mean_depart_delay_s)
            if complete
            else (summary.lower_bound_mean_time_loss_s, summary.lower_bound_mean_depart_delay_s)
        )
        assert parts[0] is not None
        assert parts[1] is not None
        assert parts[0] + parts[1] == pytest.approx(figure, rel=1e-9, abs=1e-6)
