"""Cola y detenciones en la zona (DEV19 F3; QA27), con trayectorias calculadas a mano."""

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from semaforo.caso.errors import CasoError
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.protocol import Protocol, parse_protocol
from semaforo.evaluacion.cohort import CohortDelay, VehicleDelay, summarize_delays
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.fcd import FcdRecord, read_fcd
from semaforo.evaluacion.metrics import ZoneMetrics, lane_access, zone_metrics
from semaforo.simulacion.reconcile import Status

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
N, E = "demo_N_0", "demo_E_0"
LIMIT = 1024 * 1024
Step = dict[str, tuple[str, float]]  # vehículo -> (carril, velocidad)


def case() -> Case:
    return parse_case(json.loads((FIXTURES / "case.json").read_text(encoding="utf-8")))


def protocol(**changes: object) -> Protocol:
    data: dict[str, Any] = json.loads((FIXTURES / "protocol.json").read_text(encoding="utf-8"))
    data.update(changes)
    return parse_protocol(data)


def cohort(*vehicles: tuple[str, str, Status]) -> CohortDelay:
    """Cohorte con (vehículo, acceso, estado); la demora no importa aquí."""
    items = [
        VehicleDelay(
            vehicle_id=vehicle_id,
            movement_id="N_S" if access == "N" else "E_W",
            vehicle_class="car",
            access_id=access,
            status=status,
            time_loss_s=0.0,
            depart_delay_s=0.0,
            depart_delay_source="sumo",
        )
        for vehicle_id, access, status in vehicles
    ]
    groups: dict[str, list[VehicleDelay]] = {}
    for item in items:
        groups.setdefault(item.access_id, []).append(item)
    return CohortDelay(
        total=summarize_delays(items),
        by_access={name: summarize_delays(groups[name]) for name in sorted(groups)},
        by_movement={},
        warmup_vehicles=0,
        simulation_end_s=100.0,
        vehicles=items,
    )


def fcd_xml(steps: dict[float, Step]) -> str:
    body: list[str] = []
    for time, vehicles in steps.items():
        rows = "".join(
            f'<vehicle id="{vid}" speed="{speed:.2f}" lane="{lane}"/>'
            for vid, (lane, speed) in vehicles.items()
        )
        body.append(f'<timestep time="{time:.2f}">{rows}</timestep>')
    return "<fcd-export>" + "".join(body) + "</fcd-export>"


def write(tmp_path: Path, steps: dict[float, Step]) -> Path:
    path = tmp_path / "fcd.xml"
    path.write_text(fcd_xml(steps), encoding="utf-8")
    return path


def measure(
    tmp_path: Path,
    steps: dict[float, Step],
    group: CohortDelay,
    *,
    start: float = 0.0,
    end: float = 4.0,
    **changes: object,
) -> ZoneMetrics:
    return zone_metrics(
        write(tmp_path, steps),
        protocol(**changes),
        case(),
        group,
        step_s=1.0,
        start_s=start,
        end_s=end,
    )


# --- QA27: dos accesos, velocidades conocidas y cola cero -----------------------------------

# Cuatro ticks. En N, «a» frena y se detiene en t=1 y t=2 y arranca; «b» llega detenido en t=2.
# En E, «c» pasa sin detenerse: su cola es cero.
QA27: dict[float, Step] = {
    0.0: {"a": (N, 8.0), "c": (E, 10.0)},
    1.0: {"a": (N, 0.0), "c": (E, 9.0)},
    2.0: {"a": (N, 0.05), "b": (N, 0.0), "c": (E, 11.0)},
    3.0: {"a": (N, 3.0), "b": (N, 0.0)},
}


def qa27_cohort() -> CohortDelay:
    return cohort(("a", "N", "finished"), ("b", "N", "finished"), ("c", "E", "finished"))


def test_qa27_queue_counts_match_the_hand_calculation(tmp_path: Path) -> None:
    result = measure(tmp_path, QA27, qa27_cohort())
    # Detenidos por tick en N: 0, 1, 2, 1 -> suma 4, media 1, máximo 2. En E: 0 siempre.
    north, east = result.queue_by_access["N"], result.queue_by_access["E"]
    assert (north.vehicle_ticks, north.mean_vehicles, north.max_vehicles) == (4, 1.0, 2)
    assert (east.vehicle_ticks, east.mean_vehicles, east.max_vehicles) == (0, 0.0, 0)
    assert (result.queue.vehicle_ticks, result.queue.mean_vehicles) == (4, 1.0)
    assert result.queue.max_vehicles == 2


def test_qa27_coverage_is_complete_and_zeros_are_included(tmp_path: Path) -> None:
    result = measure(tmp_path, QA27, qa27_cohort())
    assert (result.queue.ticks_expected, result.queue.ticks_observed) == (4, 4)
    assert result.queue.coverage == 1.0
    assert result.queue.status == "complete"
    assert result.queue_by_access["E"].status == "complete"


def test_qa27_stops_match_the_hand_calculation(tmp_path: Path) -> None:
    result = measure(tmp_path, QA27, qa27_cohort())
    # «a»: una detención (8 -> 0); sigue detenido a 0.05. «b» aparece detenido: una. «c»: cero.
    assert result.vehicle_stops == {"a": 1, "b": 1, "c": 0}
    assert (result.stops.total_stops, result.stops.requested) == (2, 3)
    assert result.stops.mean_stops == pytest.approx(2 / 3)
    assert result.stops_by_access["N"].mean_stops == 1.0
    assert result.stops_by_access["E"].mean_stops == 0.0
    assert result.stops.lower_bound_mean_stops is None


def test_the_units_and_parameters_are_recorded(tmp_path: Path) -> None:
    settings = measure(tmp_path, QA27, qa27_cohort()).settings
    assert settings.zone_lane_ids == [N, E]
    assert (settings.queue_speed_threshold_mps, settings.stop_speed_threshold_mps) == (0.1, 0.1)
    assert (settings.queue_sampling_s, settings.step_length_s) == (1, 1.0)
    assert (settings.measure_start_s, settings.measure_end_s) == (0.0, 4.0)


# --- definiciones en el borde ----------------------------------------------------------------


def test_a_speed_equal_to_the_threshold_is_stopped(tmp_path: Path) -> None:
    steps = {0.0: {"a": (N, 5.0)}, 1.0: {"a": (N, 0.1)}}
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), end=2.0)
    assert result.queue.vehicle_ticks == 1
    assert result.vehicle_stops["a"] == 1


def test_a_speed_just_above_the_threshold_is_moving(tmp_path: Path) -> None:
    steps = {0.0: {"a": (N, 5.0)}, 1.0: {"a": (N, 0.11)}}
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), end=2.0)
    assert result.queue.vehicle_ticks == 0
    assert result.vehicle_stops["a"] == 0


def test_the_queue_and_stop_thresholds_are_independent(tmp_path: Path) -> None:
    steps = {0.0: {"a": (N, 5.0)}, 1.0: {"a": (N, 1.0)}}
    result = measure(
        tmp_path,
        steps,
        cohort(("a", "N", "finished")),
        end=2.0,
        queue_speed_threshold_mps=1.5,
        stop_speed_threshold_mps=0.1,
    )
    assert result.queue.vehicle_ticks == 1
    assert result.vehicle_stops["a"] == 0


def test_stop_and_go_twice_is_two_stops(tmp_path: Path) -> None:
    speeds = [6.0, 0.0, 4.0, 0.0, 0.0, 5.0]
    steps = {float(t): {"a": (N, speed)} for t, speed in enumerate(speeds)}
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), end=6.0)
    assert result.vehicle_stops["a"] == 2


def test_a_vehicle_that_leaves_the_zone_and_comes_back_stopped_counts_again(
    tmp_path: Path,
) -> None:
    steps: dict[float, Step] = {
        0.0: {"a": (N, 0.0)},
        1.0: {"a": ("demo_S_0", 0.0)},
        2.0: {"a": (N, 0.0)},
    }
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), end=3.0)
    assert result.vehicle_stops["a"] == 2


def test_lanes_outside_the_zone_and_internal_lanes_do_not_count(tmp_path: Path) -> None:
    steps: dict[float, Step] = {
        0.0: {"a": ("demo_S_0", 0.0), "b": (":C_0_0", 0.0), "c": (N, 0.0)},
    }
    group = cohort(("a", "N", "finished"), ("b", "N", "finished"), ("c", "N", "finished"))
    result = measure(tmp_path, steps, group, end=1.0)
    assert result.queue.vehicle_ticks == 1
    assert result.vehicle_stops == {"a": 0, "b": 0, "c": 1}


def test_vehicles_outside_the_cohort_queue_but_their_stops_are_not_counted(
    tmp_path: Path,
) -> None:
    steps: dict[float, Step] = {0.0: {"w": (N, 0.0), "a": (N, 0.0)}}
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), end=1.0)
    assert result.queue.vehicle_ticks == 2
    assert result.vehicle_stops == {"a": 1}
    assert result.stops.total_stops == 1


def test_the_queue_only_samples_the_measurement_interval(tmp_path: Path) -> None:
    steps = {float(t): {"a": (N, 0.0)} for t in range(6)}
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), start=2.0, end=4.0)
    assert (result.queue.ticks_expected, result.queue.vehicle_ticks) == (2, 2)


def test_stops_are_counted_over_the_whole_run(tmp_path: Path) -> None:
    steps = {0.0: {"a": (N, 5.0)}, 1.0: {"a": (N, 0.0)}, 2.0: {}, 3.0: {}}
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), start=2.0, end=4.0)
    assert result.vehicle_stops["a"] == 1
    assert result.queue.vehicle_ticks == 0


def test_a_sampling_every_two_steps_takes_every_other_tick(tmp_path: Path) -> None:
    steps = {float(t): {"a": (N, 0.0)} if t % 2 else {} for t in range(6)}
    result = measure(tmp_path, steps, cohort(("a", "N", "finished")), end=6.0, queue_sampling_s=2)
    assert result.queue.ticks_expected == 3
    assert result.queue.vehicle_ticks == 0


def test_a_sampling_that_is_not_a_multiple_of_the_step_is_refused(tmp_path: Path) -> None:
    with pytest.raises(EvaluacionError, match="múltiplo") as raised:
        measure(tmp_path, QA27, qa27_cohort(), queue_sampling_s=1.5)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    for sampling in (0.5, 1e-9):
        with pytest.raises(EvaluacionError, match="múltiplo"):
            measure(tmp_path, QA27, qa27_cohort(), queue_sampling_s=sampling)


# --- cobertura y censura ---------------------------------------------------------------------


def test_a_missing_tick_makes_the_queue_incomplete_without_values(tmp_path: Path) -> None:
    steps = {t: s for t, s in QA27.items() if t != 2.0}
    result = measure(tmp_path, steps, qa27_cohort())
    queue = result.queue
    assert (queue.status, queue.ticks_expected, queue.ticks_observed) == ("incomplete", 4, 3)
    assert queue.coverage == 0.75
    assert (queue.vehicle_ticks, queue.mean_vehicles, queue.max_vehicles) == (None, None, None)
    assert result.queue_by_access["E"].status == "incomplete"


def test_decimal_steps_give_the_exact_number_of_ticks(tmp_path: Path) -> None:
    """(0.4 - 0.1) / 0.1 da 3.0000000000000004 en binario: siguen siendo 3 ticks."""
    steps = {0.1: {"a": (N, 0.0)}, 0.2: {"a": (N, 0.0)}, 0.3: {"a": (N, 0.0)}}
    result = zone_metrics(
        write(tmp_path, steps),
        protocol(queue_sampling_s=0.1),
        case(),
        cohort(("a", "N", "finished")),
        step_s=0.1,
        start_s=0.1,
        end_s=0.4,
    )
    assert (result.queue.ticks_expected, result.queue.ticks_observed) == (3, 3)
    assert result.queue.status == "complete"
    assert result.vehicle_stops["a"] == 1


@pytest.mark.parametrize("start", [4.0, 9.0])
def test_an_empty_or_reversed_interval_has_no_queue(tmp_path: Path, start: float) -> None:
    result = measure(tmp_path, QA27, qa27_cohort(), start=start, end=4.0)
    assert (result.queue.status, result.queue.coverage) == ("empty", None)
    assert result.queue.ticks_expected == 0
    assert result.queue.mean_vehicles is None


def test_the_total_peak_is_of_the_whole_zone_at_one_tick(tmp_path: Path) -> None:
    steps: dict[float, Step] = {0.0: {"a": (N, 0.0), "c": (E, 0.0)}, 1.0: {"a": (N, 0.0)}}
    group = cohort(("a", "N", "finished"), ("c", "E", "finished"))
    result = measure(tmp_path, steps, group, end=2.0)
    assert result.queue.max_vehicles == 2
    assert result.queue_by_access["N"].max_vehicles == 1
    assert result.queue_by_access["E"].max_vehicles == 1


def test_a_censored_cohort_gives_a_lower_bound_of_stops(tmp_path: Path) -> None:
    group = cohort(("a", "N", "finished"), ("b", "N", "unfinished"), ("c", "E", "not_inserted"))
    result = measure(tmp_path, QA27, group)
    assert result.stops.status == "censored"
    assert result.stops.mean_stops is None
    assert result.stops.lower_bound_mean_stops == pytest.approx(2 / 3)
    assert result.stops_by_access["E"].status == "censored"
    assert result.stops_by_access["E"].lower_bound_mean_stops == 0.0


def test_an_access_without_cohort_has_no_stop_figures(tmp_path: Path) -> None:
    result = measure(tmp_path, QA27, cohort(("a", "N", "finished")))
    assert "E" not in result.stops_by_access
    assert result.queue_by_access["E"].mean_vehicles == 0.0


# --- acceso de cada carril -------------------------------------------------------------------


def test_an_upstream_lane_takes_the_access_of_its_street() -> None:
    access = lane_access(case(), [N, "arriba_0", "otra_1"], {"arriba": "N", "demo_N": "N"})
    assert access == {N: "N", "arriba_0": "N", "otra_1": "otra"}


def test_upstream_queues_count_in_the_access_of_their_street(tmp_path: Path) -> None:
    steps: dict[float, Step] = {0.0: {"a": ("arriba_0", 0.0), "b": (N, 0.0)}}
    result = zone_metrics(
        write(tmp_path, steps),
        protocol(zone_lane_ids=[N, E, "arriba_0"]),
        case(),
        cohort(("a", "N", "finished"), ("b", "N", "finished")),
        step_s=1.0,
        start_s=0.0,
        end_s=1.0,
        edge_access={"arriba": "N"},
    )
    assert sorted(result.queue_by_access) == ["E", "N"]
    assert result.queue_by_access["N"].vehicle_ticks == 2
    assert result.vehicle_stops == {"a": 1, "b": 1}


def test_the_access_of_a_lane_is_the_approach_of_its_movement() -> None:
    assert lane_access(case(), [N, E, "otra_calle_2"]) == {
        N: "N",
        E: "E",
        "otra_calle_2": "otra_calle",
    }


# --- lectura de la FCD -----------------------------------------------------------------------


def collect(path: Path, limit: int = LIMIT) -> list[tuple[float, list[FcdRecord]]]:
    steps: list[tuple[float, list[FcdRecord]]] = []
    read_fcd(path, limit, lambda time, records: steps.append((time, records)))
    return steps


def test_the_reader_gives_each_step_with_its_vehicles(tmp_path: Path) -> None:
    steps = collect(write(tmp_path, {0.0: {"a": (N, 1.5)}, 1.0: {}}))
    assert steps == [(0.0, [FcdRecord("a", N, 1.5)]), (1.0, [])]


def test_the_reader_accepts_gzip(tmp_path: Path) -> None:
    path = tmp_path / "fcd.xml.gz"
    path.write_bytes(gzip.compress(fcd_xml({0.0: {"a": (N, 1.0)}}).encode(), mtime=0))
    assert len(collect(path)) == 1


def test_persons_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "fcd.xml"
    path.write_text(
        '<fcd-export><timestep time="0.00"><person id="p" speed="0" lane="x"/>'
        '<vehicle id="a" speed="0" lane="demo_N_0"/></timestep></fcd-export>',
        encoding="utf-8",
    )
    assert collect(path) == [(0.0, [FcdRecord("a", N, 0.0)])]


HOSTILE = {
    "other-root": "<tripinfos/>",
    "steps-out-of-order": '<fcd-export><timestep time="2"/><timestep time="1"/></fcd-export>',
    "repeated-step": '<fcd-export><timestep time="1"/><timestep time="1"/></fcd-export>',
    "step-without-time": "<fcd-export><timestep/></fcd-export>",
    "nan-time": '<fcd-export><timestep time="nan"/></fcd-export>',
    "vehicle-twice": (
        '<fcd-export><timestep time="0"><vehicle id="a" speed="0" lane="x"/>'
        '<vehicle id="a" speed="1" lane="x"/></timestep></fcd-export>'
    ),
    "negative-speed": (
        '<fcd-export><timestep time="0"><vehicle id="a" speed="-1" lane="x"/></timestep>'
        "</fcd-export>"
    ),
    "nan-speed": (
        '<fcd-export><timestep time="0"><vehicle id="a" speed="nan" lane="x"/></timestep>'
        "</fcd-export>"
    ),
    "no-speed": '<fcd-export><timestep time="0"><vehicle id="a" lane="x"/></timestep></fcd-export>',
    "no-lane": '<fcd-export><timestep time="0"><vehicle id="a" speed="1"/></timestep></fcd-export>',
    "no-id": '<fcd-export><timestep time="0"><vehicle speed="1" lane="x"/></timestep></fcd-export>',
    "vehicle-outside-a-step": '<fcd-export><vehicle id="a" speed="1" lane="x"/></fcd-export>',
    "other-element-with-time": '<fcd-export><timestep time="0"/><otro time="1"/></fcd-export>',
    "truncated": '<fcd-export><timestep time="0">',
    "not-xml": "esto no es XML",
    "dtd": '<!DOCTYPE x [<!ENTITY e "a">]><fcd-export/>',
}


@pytest.mark.parametrize("text", HOSTILE.values(), ids=HOSTILE.keys())
def test_a_broken_or_hostile_fcd_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "fcd.xml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        collect(path)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert str(tmp_path) not in raised.value.message


def test_a_fcd_bigger_than_the_cap_is_refused_also_compressed(tmp_path: Path) -> None:
    text = fcd_xml({float(t): {"a": (N, 1.0)} for t in range(2000)})
    path = tmp_path / "fcd.xml.gz"
    path.write_bytes(gzip.compress(text.encode(), mtime=0))
    with pytest.raises(CasoError, match="límite"):
        collect(path, limit=10_000)


def test_a_broken_fcd_makes_the_metrics_fail_without_figures(tmp_path: Path) -> None:
    path = tmp_path / "fcd.xml"
    path.write_text("<fcd-export><timestep time='0'>", encoding="utf-8")
    with pytest.raises(EvaluacionError) as raised:
        zone_metrics(path, protocol(), case(), qa27_cohort(), step_s=1.0, start_s=0.0, end_s=1.0)
    assert raised.value.code is ErrorCode.OUTPUT_INVALID
    assert raised.value.field == "fcd.xml"


def test_a_missing_fcd_makes_the_metrics_fail(tmp_path: Path) -> None:
    with pytest.raises(EvaluacionError) as raised:
        zone_metrics(
            tmp_path / "fcd.xml",
            protocol(),
            case(),
            qa27_cohort(),
            step_s=1.0,
            start_s=0.0,
            end_s=1.0,
        )
    assert raised.value.code is ErrorCode.OUTPUT_INVALID
