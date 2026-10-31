"""Pruebas de la comparación con el conteo de control (DEV05 F1, HU03, QA06)."""

import copy
import json
import math
from pathlib import Path

import pytest

from semaforo.datos.importer import CountImportError
from semaforo.datos.quality import (
    ZERO_CONTROL_REASON,
    QualityComparison,
    QualityError,
    WindowComparison,
    compare_files,
    find_exclusions,
)
from semaforo.dominio.case import Case, parse_case

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_CASE = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
HEADER = (
    "case_id,observation_id,source_id,origin,start,end,"
    "movement_id,vehicle_class,count,quality_state"
)
W1 = ("2026-10-18T08:00:00-05:00", "2026-10-18T08:15:00-05:00")
W2 = ("2026-10-18T08:15:00-05:00", "2026-10-18T08:30:00-05:00")
# Matriz completa del caso de demostración: dos movimientos y dos clases.
KEYS = [("N_S", "car"), ("N_S", "bus"), ("E_W", "car"), ("E_W", "bus")]


def make_case() -> Case:
    return parse_case(copy.deepcopy(DEMO_CASE))


def period(
    observation_id: str,
    source_id: str,
    window: tuple[str, str],
    counts: list[int],
    keys: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Filas de un periodo; ``counts`` sigue el orden de ``keys`` (por defecto, todas)."""
    pairs = list(zip(keys or KEYS, counts, strict=True))
    return [
        f"SYNTHETIC_DEMO,{observation_id},{source_id},synthetic,{window[0]},{window[1]},"
        f"{movement},{vclass},{count},observed"
        for (movement, vclass), count in pairs
    ]


def write(tmp_path: Path, name: str, rows: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    return path


def compare(tmp_path: Path, observed: list[str], control: list[str]) -> QualityComparison:
    return compare_files(
        write(tmp_path, "principal.csv", observed),
        write(tmp_path, "control.csv", control),
        make_case(),
    )


def by_key(window: WindowComparison) -> dict[tuple[str, str], tuple[int, int | None, float | None]]:
    return {
        (c.movement_id, c.vehicle_class): (c.absolute_error, c.absolute_value, c.relative_error)
        for c in window.counts
    }


def test_qa06_errors_against_a_control_of_100_and_0(tmp_path: Path) -> None:
    observed = period("OBS", "CAMARA", W1, [90, 5, 50, 0])
    control = period("CTL", "MANUAL", W1, [100, 0, 50, 0])
    [window] = compare(tmp_path, observed, control).windows
    assert window.status == "comparable"
    found = {(c.movement_id, c.vehicle_class): c for c in window.counts}
    car, bus = found["N_S", "car"], found["N_S", "bus"]
    assert (car.absolute_error, car.absolute_value, car.relative_error) == (-10, 10, 0.1)
    assert car.relative_reason is None
    assert (bus.absolute_error, bus.absolute_value, bus.relative_error) == (5, 5, None)
    assert bus.relative_reason == "control cero"


def test_a_zero_in_both_counts_has_zero_error_and_no_relative_error(tmp_path: Path) -> None:
    observed = period("OBS", "CAMARA", W1, [90, 0, 50, 0])
    control = period("CTL", "MANUAL", W1, [90, 0, 50, 0])
    [window] = compare(tmp_path, observed, control).windows
    found = {(c.movement_id, c.vehicle_class): c for c in window.counts}
    assert found["N_S", "bus"].absolute_error == 0
    assert found["N_S", "bus"].relative_error is None
    assert found["N_S", "bus"].relative_reason == ZERO_CONTROL_REASON
    assert found["N_S", "car"].relative_error == 0.0
    assert found["N_S", "car"].relative_reason is None


def test_the_sign_shows_whether_the_main_count_is_above_or_below(tmp_path: Path) -> None:
    observed = period("OBS", "CAMARA", W1, [110, 4, 50, 0])
    control = period("CTL", "MANUAL", W1, [100, 5, 50, 0])
    [window] = compare(tmp_path, observed, control).windows
    errors = by_key(window)
    assert errors["N_S", "car"] == (10, 10, 0.1)
    assert errors["N_S", "bus"] == (-1, 1, 0.2)


def test_every_movement_and_class_of_the_case_is_compared_in_case_order(tmp_path: Path) -> None:
    observed = period("OBS", "CAMARA", W1, [90, 10, 50, 0])
    control = period("CTL", "MANUAL", W1, [90, 10, 50, 0])
    [window] = compare(tmp_path, observed, control).windows
    assert [(c.movement_id, c.vehicle_class) for c in window.counts] == KEYS


def test_the_ids_and_the_control_source_are_recorded(tmp_path: Path) -> None:
    observed = period("OBS_A", "CAMARA", W1, [1, 1, 1, 1])
    control = period("CTL_A", "MANUAL_1", W1, [1, 1, 1, 1])
    [window] = compare(tmp_path, observed, control).windows
    assert (window.observed_id, window.control_id, window.control_source_id) == (
        "OBS_A",
        "CTL_A",
        "MANUAL_1",
    )


def test_a_window_only_in_one_file_is_reported_not_dropped(tmp_path: Path) -> None:
    observed = [
        *period("OBS_1", "CAMARA", W1, [1, 1, 1, 1]),
        *period("OBS_2", "CAMARA", W2, [2, 2, 2, 2]),
    ]
    control = period("CTL_1", "MANUAL", W1, [1, 1, 1, 1])
    first, second = compare(tmp_path, observed, control).windows
    assert (first.status, second.status) == ("comparable", "only_observed")
    assert second.control_id is None
    assert second.counts == ()
    only_control = compare(tmp_path, control, observed).windows[1]
    assert only_control.status == "only_control"


def test_windows_with_a_different_start_or_end_are_not_paired(tmp_path: Path) -> None:
    longer = ("2026-10-18T08:00:00-05:00", "2026-10-18T08:30:00-05:00")
    observed = period("OBS", "CAMARA", W1, [1, 1, 1, 1])
    control = period("CTL", "MANUAL", longer, [1, 1, 1, 1])
    statuses = [window.status for window in compare(tmp_path, observed, control).windows]
    assert sorted(statuses) == ["only_control", "only_observed"]


def test_the_same_instant_in_another_time_zone_is_the_same_window(tmp_path: Path) -> None:
    utc = ("2026-10-18T13:00:00+00:00", "2026-10-18T13:15:00+00:00")
    observed = period("OBS", "CAMARA", W1, [1, 1, 1, 1])
    control = period("CTL", "MANUAL", utc, [1, 1, 1, 1])
    [window] = compare(tmp_path, observed, control).windows
    assert window.status == "comparable"


@pytest.mark.parametrize("missing_in", ["principal", "control", "both"])
def test_an_incomplete_period_makes_the_window_not_comparable(
    tmp_path: Path, missing_in: str
) -> None:
    short_keys = KEYS[:3]
    full = period("OBS", "CAMARA", W1, [1, 1, 1, 1])
    short = period("OBS", "CAMARA", W1, [1, 1, 1], short_keys)
    control_full = period("CTL", "MANUAL", W1, [1, 1, 1, 1])
    control_short = period("CTL", "MANUAL", W1, [1, 1, 1], short_keys)
    observed = short if missing_in in ("principal", "both") else full
    control = control_short if missing_in in ("control", "both") else control_full
    [window] = compare(tmp_path, observed, control).windows
    assert window.status == "not_comparable"
    assert window.counts == ()
    assert window.reason is not None
    assert "E_W/bus" in window.reason
    assert ("principal" in window.reason) == (missing_in in ("principal", "both"))
    assert ("de control" in window.reason) == (missing_in in ("control", "both"))


def test_a_missing_row_is_never_compared_as_a_zero(tmp_path: Path) -> None:
    observed = period("OBS", "CAMARA", W1, [90, 10, 50], KEYS[:3])
    control = period("CTL", "MANUAL", W1, [90, 10, 50, 0])
    [window] = compare(tmp_path, observed, control).windows
    assert window.status == "not_comparable"
    assert window.counts == ()


def test_windows_come_out_in_time_order(tmp_path: Path) -> None:
    observed = [
        *period("OBS_2", "CAMARA", W2, [1, 1, 1, 1]),
        *period("OBS_1", "CAMARA", W1, [1, 1, 1, 1]),
    ]
    control = [
        *period("CTL_2", "MANUAL", W2, [1, 1, 1, 1]),
        *period("CTL_1", "MANUAL", W1, [1, 1, 1, 1]),
    ]
    windows = compare(tmp_path, observed, control).windows
    assert [w.observed_id for w in windows] == ["OBS_1", "OBS_2"]


def test_a_control_with_the_same_source_as_the_main_count_is_rejected(tmp_path: Path) -> None:
    observed = period("OBS", "MISMA", W1, [1, 1, 1, 1])
    control = period("CTL", "MISMA", W1, [1, 1, 1, 1])
    with pytest.raises(QualityError) as raised:
        compare(tmp_path, observed, control)
    assert raised.value.field == "source_id"


def test_two_periods_with_the_same_window_in_one_file_are_ambiguous(tmp_path: Path) -> None:
    observed = [
        *period("OBS_A", "CAMARA", W1, [1, 1, 1, 1]),
        *period("OBS_B", "CAMARA", W1, [2, 2, 2, 2]),
    ]
    control = period("CTL", "MANUAL", W1, [1, 1, 1, 1])
    with pytest.raises(QualityError) as raised:
        compare(tmp_path, observed, control)
    assert "principal" in raised.value.message
    with pytest.raises(QualityError) as raised_control:
        compare(
            tmp_path,
            control,
            [*period("C_A", "M1", W1, [1, 1, 1, 1]), *period("C_B", "M2", W1, [1, 1, 1, 1])],
        )
    assert "de control" in raised_control.value.message


def test_an_invalid_control_file_is_rejected_by_the_importer(tmp_path: Path) -> None:
    observed = write(tmp_path, "principal.csv", period("OBS", "CAMARA", W1, [1, 1, 1, 1]))
    control = write(tmp_path, "control.csv", period("CTL", "MANUAL", W1, [1, 1, 1, -1]))
    with pytest.raises(CountImportError):
        compare_files(observed, control, make_case())


def test_the_fingerprint_of_each_file_is_recorded(tmp_path: Path) -> None:
    observed = write(tmp_path, "principal.csv", period("OBS", "CAMARA", W1, [1, 1, 1, 1]))
    control = write(tmp_path, "control.csv", period("CTL", "MANUAL", W1, [1, 1, 1, 1]))
    result = compare_files(observed, control, make_case())
    assert result.case_id == "SYNTHETIC_DEMO"
    assert len(result.observed_sha256) == len(result.control_sha256) == 64
    assert result.observed_sha256 != result.control_sha256


# F2: exclusiones por límite de error relativo. Sin límite no se excluye nada.


def qa06(tmp_path: Path) -> QualityComparison:
    observed = period("OBS", "CAMARA", W1, [90, 5, 50, 0])
    control = period("CTL", "MANUAL", W1, [100, 0, 50, 0])
    return compare(tmp_path, observed, control)


def test_without_a_limit_nothing_is_excluded(tmp_path: Path) -> None:
    assert find_exclusions(qa06(tmp_path)) == ()
    assert find_exclusions(qa06(tmp_path), None) == ()


def test_a_comparison_above_the_limit_is_excluded_with_its_value(tmp_path: Path) -> None:
    [exclusion] = find_exclusions(qa06(tmp_path), 0.05)
    assert (exclusion.movement_id, exclusion.vehicle_class) == ("N_S", "car")
    assert (exclusion.relative_error, exclusion.threshold) == (0.1, 0.05)
    assert exclusion.observed_id == "OBS"
    assert exclusion.start.isoformat() == W1[0]
    assert "N_S/car" in exclusion.reason
    assert "0.100" in exclusion.reason
    assert "0.05" in exclusion.reason


def test_an_error_equal_to_the_limit_is_not_excluded(tmp_path: Path) -> None:
    assert find_exclusions(qa06(tmp_path), 0.1) == ()


def test_a_zero_control_has_no_relative_error_so_it_is_not_excluded(tmp_path: Path) -> None:
    # El bus tiene control 0 y observado 5: su error relativo es nulo y no se evalúa.
    assert all(e.vehicle_class != "bus" for e in find_exclusions(qa06(tmp_path), 0.0))


def test_a_limit_of_zero_excludes_any_difference_but_not_a_perfect_match(tmp_path: Path) -> None:
    same = period("OBS", "CAMARA", W1, [90, 10, 50, 0])
    assert (
        find_exclusions(compare(tmp_path, same, period("CTL", "MANUAL", W1, [90, 10, 50, 0])), 0)
        == ()
    )
    assert len(find_exclusions(qa06(tmp_path), 0)) == 1


def test_only_comparable_windows_are_evaluated(tmp_path: Path) -> None:
    observed = period("OBS", "CAMARA", W1, [1, 1, 1], KEYS[:3])
    control = period("CTL", "MANUAL", W1, [100, 100, 100, 100])
    result = compare(tmp_path, observed, control)
    assert result.windows[0].status == "not_comparable"
    assert find_exclusions(result, 0.0) == ()


@pytest.mark.parametrize("limit", [-0.1, math.nan, math.inf])
def test_an_invalid_error_limit_is_rejected(tmp_path: Path, limit: float) -> None:
    with pytest.raises(QualityError) as raised:
        find_exclusions(qa06(tmp_path), limit)
    assert raised.value.field == "max_relative_error"
