"""Pruebas de cobertura temporal y faltantes de los aforos (DEV05 F2, HU03)."""

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from semaforo.datos.coverage import Coverage, assess_coverage, list_missing
from semaforo.datos.normalizer import PreparedCounts, prepare_counts
from semaforo.datos.quality import QualityError
from semaforo.dominio.case import Case, parse_case

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_CASE = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
HEADER = (
    "case_id,observation_id,source_id,origin,start,end,"
    "movement_id,vehicle_class,count,quality_state"
)
LIMA = timezone(timedelta(hours=-5))
ORIGIN = datetime(2026, 10, 18, 8, 0, tzinfo=LIMA)
KEYS = [("N_S", "car"), ("N_S", "bus"), ("E_W", "car"), ("E_W", "bus")]


def at(minute: int) -> datetime:
    """Un instante, en minutos desde las 08:00 de Lima."""
    return ORIGIN + timedelta(minutes=minute)


def make_case() -> Case:
    return parse_case(copy.deepcopy(DEMO_CASE))


def rows(
    observation_id: str,
    start: int,
    end: int,
    without: tuple[str, str] | None = None,
) -> list[str]:
    """Filas de un periodo entre dos minutos; ``without`` omite una combinación (un faltante)."""
    return [
        f"SYNTHETIC_DEMO,{observation_id},CAMARA,synthetic,{at(start).isoformat()},"
        f"{at(end).isoformat()},{movement},{vclass},10,observed"
        for movement, vclass in KEYS
        if (movement, vclass) != without
    ]


def prepared(tmp_path: Path, *periods: list[str]) -> PreparedCounts:
    path = tmp_path / "aforos.csv"
    path.write_text("\n".join([HEADER, *[row for p in periods for row in p]]) + "\n")
    return prepare_counts(path, make_case())


def hour(tmp_path: Path, *periods: list[str], min_coverage: float | None = None) -> Coverage:
    """Cobertura sobre la hora 08:00 a 09:00, declarada."""
    return assess_coverage(
        prepared(tmp_path, *periods), make_case(), (at(0), at(60)), min_coverage=min_coverage
    )


def full_hour() -> list[list[str]]:
    return [rows(f"P{i}", 15 * i, 15 * i + 15) for i in range(4)]


def test_a_fully_covered_window_has_coverage_one_and_no_gaps(tmp_path: Path) -> None:
    result = hour(tmp_path, *full_hour())
    assert (result.window_s, result.covered_s, result.coverage) == (3600, 3600, 1.0)
    assert result.gaps == ()
    assert result.window_declared is True


def test_missing_time_is_reported_as_gaps(tmp_path: Path) -> None:
    result = hour(tmp_path, rows("P0", 0, 15), rows("P2", 30, 45))
    assert result.coverage == 0.5
    assert [(g.start, g.end) for g in result.gaps] == [(at(15), at(30)), (at(45), at(60))]


def test_an_incomplete_period_is_not_covered_and_its_missing_row_is_listed(tmp_path: Path) -> None:
    periods = [rows("P0", 0, 15), rows("P1", 15, 30, without=("E_W", "bus")), *full_hour()[2:]]
    counts = prepared(tmp_path, *periods)
    result = assess_coverage(counts, make_case(), (at(0), at(60)))
    assert result.coverage == 0.75
    assert [(g.start, g.end) for g in result.gaps] == [(at(15), at(30))]
    [entry] = list_missing(counts)
    assert (entry.observation_id, entry.start, entry.end) == ("P1", at(15), at(30))
    assert (entry.movement_id, entry.vehicle_class) == ("E_W", "bus")


def test_coverage_by_movement_uses_the_classes_of_that_movement(tmp_path: Path) -> None:
    periods = [rows("P0", 0, 15), rows("P1", 15, 30, without=("E_W", "bus")), *full_hour()[2:]]
    result = hour(tmp_path, *periods)
    by_movement = {m.movement_id: m.coverage for m in result.per_movement}
    assert by_movement == {"N_S": 1.0, "E_W": 0.75}
    assert [m.movement_id for m in result.per_movement] == ["N_S", "E_W"]


def test_overlapping_periods_are_counted_once_and_reported(tmp_path: Path) -> None:
    result = assess_coverage(
        prepared(tmp_path, rows("A", 0, 15), rows("B", 10, 25)), make_case(), (at(0), at(30))
    )
    assert result.covered_s == 25 * 60
    assert result.coverage == 25 / 30
    assert result.overlaps == (("A", "B"),)
    assert result.gaps[0].start == at(25)


def test_adjacent_periods_do_not_overlap_and_leave_no_gap(tmp_path: Path) -> None:
    result = hour(tmp_path, *full_hour())
    assert result.overlaps == ()


def test_without_a_declared_window_it_is_deduced_and_says_so(tmp_path: Path) -> None:
    counts = prepared(tmp_path, rows("A", 0, 15), rows("B", 30, 45))
    result = assess_coverage(counts, make_case())
    assert (result.window_start, result.window_end) == (at(0), at(45))
    assert result.window_declared is False
    assert result.coverage == 1800 / 2700


def test_a_declared_window_clips_the_periods(tmp_path: Path) -> None:
    counts = prepared(tmp_path, rows("A", 0, 15))
    result = assess_coverage(counts, make_case(), (at(5), at(20)))
    assert result.covered_s == 600
    assert result.coverage == 600 / 900
    assert [(g.start, g.end) for g in result.gaps] == [(at(15), at(20))]


def test_a_period_outside_the_window_does_not_count_and_is_listed(tmp_path: Path) -> None:
    counts = prepared(tmp_path, rows("DENTRO", 0, 15), rows("FUERA", 90, 105))
    result = assess_coverage(counts, make_case(), (at(0), at(60)))
    assert result.coverage == 0.25
    assert result.outside_window == ("FUERA",)


def test_periods_in_another_time_zone_are_placed_by_instant(tmp_path: Path) -> None:
    utc_rows = [
        f"SYNTHETIC_DEMO,UTC,CAMARA,synthetic,2026-10-18T13:00:00+00:00,"
        f"2026-10-18T13:15:00+00:00,{movement},{vclass},10,observed"
        for movement, vclass in KEYS
    ]
    result = hour(tmp_path, utc_rows)
    assert result.coverage == 0.25


def test_the_minimum_coverage_is_a_verdict_on_the_window_and_each_movement(
    tmp_path: Path,
) -> None:
    periods = [rows("P0", 0, 15), rows("P1", 15, 30, without=("E_W", "bus")), *full_hour()[2:]]
    below = hour(tmp_path, *periods, min_coverage=0.8)
    assert below.meets_minimum is False
    assert {m.movement_id: m.meets_minimum for m in below.per_movement} == {
        "N_S": True,
        "E_W": False,
    }
    exact = hour(tmp_path, *periods, min_coverage=0.75)
    assert exact.meets_minimum is True
    assert hour(tmp_path, *periods).meets_minimum is None
    assert all(m.meets_minimum is None for m in hour(tmp_path, *periods).per_movement)


def test_no_periods_and_no_window_cannot_be_assessed(tmp_path: Path) -> None:
    empty = prepared(tmp_path)
    with pytest.raises(QualityError) as raised:
        assess_coverage(empty, make_case())
    assert raised.value.field == "window"


def test_no_periods_with_a_declared_window_is_zero_coverage(tmp_path: Path) -> None:
    result = assess_coverage(prepared(tmp_path), make_case(), (at(0), at(60)))
    assert result.coverage == 0
    assert [(g.start, g.end) for g in result.gaps] == [(at(0), at(60))]
    assert [m.coverage for m in result.per_movement] == [0, 0]


@pytest.mark.parametrize("window", [(0, 0), (60, 0)])
def test_an_empty_or_inverted_window_is_rejected(tmp_path: Path, window: tuple[int, int]) -> None:
    counts = prepared(tmp_path, rows("A", 0, 15))
    with pytest.raises(QualityError) as raised:
        assess_coverage(counts, make_case(), (at(window[0]), at(window[1])))
    assert raised.value.field == "window"


@pytest.mark.parametrize("minimum", [-0.1, 1.5, math.nan, math.inf])
def test_a_minimum_coverage_outside_zero_to_one_is_rejected(tmp_path: Path, minimum: float) -> None:
    counts = prepared(tmp_path, rows("A", 0, 15))
    with pytest.raises(QualityError) as raised:
        assess_coverage(counts, make_case(), (at(0), at(60)), min_coverage=minimum)
    assert raised.value.field == "min_coverage"


def test_a_complete_file_has_no_missing_entries(tmp_path: Path) -> None:
    assert list_missing(prepared(tmp_path, *full_hour())) == ()


def test_every_missing_combination_is_listed_in_period_order(tmp_path: Path) -> None:
    short = rows("P1", 15, 30, without=("E_W", "bus"))
    shorter = [row for row in rows("P0", 0, 15) if ",N_S," not in row]
    entries = list_missing(prepared(tmp_path, short, shorter))
    assert [(e.observation_id, e.movement_id, e.vehicle_class) for e in entries] == [
        ("P0", "N_S", "car"),
        ("P0", "N_S", "bus"),
        ("P1", "E_W", "bus"),
    ]


def test_a_period_inside_another_does_not_shorten_the_covered_time(tmp_path: Path) -> None:
    result = assess_coverage(
        prepared(tmp_path, rows("GRANDE", 0, 30), rows("CHICO", 10, 20)),
        make_case(),
        (at(0), at(30)),
    )
    assert result.coverage == 1.0
    assert result.gaps == ()
    assert result.overlaps == (("GRANDE", "CHICO"),)


def test_a_period_that_only_touches_the_edge_of_the_window_is_outside(tmp_path: Path) -> None:
    counts = prepared(
        tmp_path, rows("ANTES", 0, 15), rows("DESPUES", 60, 75), rows("DENTRO", 20, 30)
    )
    result = assess_coverage(counts, make_case(), (at(15), at(60)))
    assert result.outside_window == ("ANTES", "DESPUES")
    assert result.covered_s == 600


def test_a_period_that_ends_after_the_window_is_clipped_at_its_end(tmp_path: Path) -> None:
    counts = prepared(tmp_path, rows("A", 50, 70))
    result = assess_coverage(counts, make_case(), (at(0), at(60)))
    assert result.covered_s == 600
    assert result.coverage == 600 / 3600
    assert [(g.start, g.end) for g in result.gaps] == [(at(0), at(50))]


def test_the_minimum_coverage_is_inclusive_for_each_movement(tmp_path: Path) -> None:
    periods = [rows("P0", 0, 15), rows("P1", 15, 30, without=("E_W", "bus")), *full_hour()[2:]]
    exact = hour(tmp_path, *periods, min_coverage=0.75)
    assert {m.movement_id: m.meets_minimum for m in exact.per_movement} == {
        "N_S": True,
        "E_W": True,
    }
