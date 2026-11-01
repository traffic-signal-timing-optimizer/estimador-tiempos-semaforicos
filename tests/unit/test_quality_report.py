"""Pruebas del reporte de calidad de aforos (DEV05 F3, HU03; D6 y D7)."""

import copy
import csv
import hashlib
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from semaforo.datos.coverage import assess_coverage, list_missing
from semaforo.datos.normalizer import prepare_counts
from semaforo.datos.quality import QualityError, compare_files, find_exclusions
from semaforo.datos.quality_report import (
    DETAIL_FILE,
    MANIFEST_FILE,
    SUMMARY_FILE,
    QualityReport,
    ReportInputs,
    build_report,
    publish_quality,
)
from semaforo.dominio.case import Case, canonical_sha256, parse_case

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_CASE = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
HEADER = (
    "case_id,observation_id,source_id,origin,start,end,"
    "movement_id,vehicle_class,count,quality_state"
)
W1 = ("2026-10-18T08:00:00-05:00", "2026-10-18T08:15:00-05:00")
W2 = ("2026-10-18T08:15:00-05:00", "2026-10-18T08:30:00-05:00")
KEYS = [("N_S", "car"), ("N_S", "bus"), ("E_W", "car"), ("E_W", "bus")]
NOW = datetime(2026, 10, 31, 9, 0, 0, tzinfo=UTC)
LIMA = timezone(timedelta(hours=-5))


def _at(minute: int) -> datetime:
    """Un instante, en minutos desde las 08:00 de Lima (-05:00)."""
    return datetime(2026, 10, 18, 8, 0, tzinfo=LIMA) + timedelta(minutes=minute)


def make_case(case_id: str = "SYNTHETIC_DEMO") -> Case:
    data = copy.deepcopy(DEMO_CASE)
    data["case_id"] = case_id
    return parse_case(data)


def period(
    observation: str,
    source: str,
    window: tuple[str, str],
    counts: list[int],
    keys: list[tuple[str, str]] | None = None,
) -> list[str]:
    pairs = list(zip(keys or KEYS, counts, strict=True))
    return [
        f"SYNTHETIC_DEMO,{observation},{source},synthetic,{window[0]},{window[1]},"
        f"{movement},{vclass},{count},observed"
        for (movement, vclass), count in pairs
    ]


def pipeline(
    tmp_path: Path,
    observed: list[str],
    control: list[str],
    limit: float | None = None,
) -> ReportInputs:
    case = make_case()
    obs = tmp_path / "principal.csv"
    ctl = tmp_path / "control.csv"
    obs.write_text("\n".join([HEADER, *observed]) + "\n", encoding="utf-8")
    ctl.write_text("\n".join([HEADER, *control]) + "\n", encoding="utf-8")
    comparison = compare_files(obs, ctl, case)
    prepared = prepare_counts(obs, case)
    coverage = assess_coverage(prepared, case, (_at(0), _at(30)))
    return ReportInputs(
        comparison=comparison,
        coverage=coverage,
        exclusions=find_exclusions(comparison, limit),
        missing=list_missing(prepared),
        case=case,
        max_relative_error=limit,
    )


def qa06(tmp_path: Path, limit: float | None = None) -> ReportInputs:
    return pipeline(
        tmp_path,
        period("OBS", "CAMARA", W1, [90, 5, 50, 0]),
        period("CTL", "MANUAL", W1, [100, 0, 50, 0]),
        limit,
    )


def build(tmp_path: Path, limit: float | None = None) -> QualityReport:
    return build_report(qa06(tmp_path, limit), NOW)


def build_for(tmp_path: Path, observed: list[str], control: list[str]) -> QualityReport:
    return build_report(pipeline(tmp_path, observed, control), NOW)


def rows_of(report: QualityReport, name: str = DETAIL_FILE) -> list[list[str]]:
    text = report.files[name].decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


def test_the_detail_is_a_semicolon_csv_with_bom_and_windows_line_endings(tmp_path: Path) -> None:
    raw = build(tmp_path).files[DETAIL_FILE]
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw
    assert raw.decode("utf-8-sig").split("\r\n")[0] == ";".join(
        [
            "observation_id",
            "control_source_id",
            "start",
            "end",
            "movement_id",
            "vehicle_class",
            "observado",
            "control",
            "error_absoluto",
            "error_relativo",
            "motivo_error_relativo",
            "estado",
            "motivo_estado",
        ]
    )


def test_qa06_rows_show_the_errors_and_the_zero_control_reason(tmp_path: Path) -> None:
    rows = rows_of(build(tmp_path))
    by_key = {(r[4], r[5]): r for r in rows[1:]}
    car = by_key['="N_S"', '="car"']
    bus = by_key['="N_S"', '="bus"']
    assert car[6:10] == ["90", "100", "-10", "0.100"]
    assert car[10:] == ["", "comparable", ""]
    assert bus[6:10] == ["5", "0", "5", ""]
    assert bus[10] == "control cero"


def test_identifiers_are_wrapped_so_excel_keeps_them_as_text(tmp_path: Path) -> None:
    rows = rows_of(build(tmp_path))
    assert rows[1][0] == '="OBS"'
    assert rows[1][1] == '="MANUAL"'


def test_the_number_of_rows_is_one_per_window_movement_and_class(tmp_path: Path) -> None:
    assert len(rows_of(build(tmp_path))) == 1 + 4


def test_a_window_without_a_pair_takes_one_row_with_its_state_and_reason(tmp_path: Path) -> None:
    rows = rows_of(
        build_for(
            tmp_path,
            period("OBS", "CAMARA", W1, [1, 1, 1, 1]),
            period("CTL", "MANUAL", W2, [1, 1, 1, 1]),
        )
    )
    states = {row[11] for row in rows[1:]}
    assert states == {"sin pareja"}
    reasons = [row[12] for row in rows[1:]]
    assert "solo existe en el conteo principal" in reasons[0]
    assert "solo existe en el conteo de control" in reasons[1]
    assert all(row[4] == "" for row in rows[1:])


def test_a_window_with_missing_rows_is_not_comparable_and_says_why(tmp_path: Path) -> None:
    short = [row for row in period("OBS", "CAMARA", W1, [1, 1, 1], KEYS[:3])]
    rows = rows_of(build_for(tmp_path, short, period("CTL", "MANUAL", W1, [1, 1, 1, 1])))
    assert len(rows) == 2
    assert rows[1][11] == "no comparable"
    assert "E_W/bus" in rows[1][12]


def test_an_excluded_comparison_is_marked_with_its_reason(tmp_path: Path) -> None:
    rows = rows_of(build(tmp_path, limit=0.05))
    by_key = {(r[4], r[5]): r for r in rows[1:]}
    car = by_key['="N_S"', '="car"']
    assert car[11] == "excluido"
    assert "supera el límite 0.05" in car[12]
    assert by_key['="N_S"', '="bus"'][11] == "comparable"


def test_the_summary_keeps_exact_values_and_the_limit_used(tmp_path: Path) -> None:
    summary = json.loads(build(tmp_path, limit=0.05).files[SUMMARY_FILE])
    assert summary["max_relative_error"] == 0.05
    assert summary["window"]["declared"] is True
    assert summary["window"]["window_s"] == 1800
    assert summary["window"]["coverage"] == 900 / 1800
    assert summary["windows_by_status"]["comparable"] == 1
    assert summary["exclusions"][0]["relative_error"] == 0.1
    assert summary["exclusions"][0]["movement_id"] == "N_S"


def test_the_summary_lists_missing_entries_and_overlaps(tmp_path: Path) -> None:
    observed = [
        *period("A", "CAMARA", W1, [1, 1, 1, 1]),
        *period(
            "B",
            "CAMARA",
            ("2026-10-18T08:10:00-05:00", "2026-10-18T08:25:00-05:00"),
            [1, 1, 1],
            KEYS[:3],
        ),
    ]
    summary = json.loads(
        build_for(tmp_path, observed, period("C", "MANUAL", W1, [1, 1, 1, 1])).files[SUMMARY_FILE]
    )
    assert summary["overlaps"] == [["A", "B"]]
    assert summary["missing"][0]["movement_id"] == "E_W"
    assert summary["missing"][0]["vehicle_class"] == "bus"


def test_the_manifest_records_the_fingerprints_of_every_file(tmp_path: Path) -> None:
    report = build(tmp_path)
    manifest = json.loads(report.files[MANIFEST_FILE])
    assert manifest["files"][DETAIL_FILE] == hashlib.sha256(report.files[DETAIL_FILE]).hexdigest()
    assert manifest["files"][SUMMARY_FILE] == hashlib.sha256(report.files[SUMMARY_FILE]).hexdigest()
    assert manifest["case_sha256"] == canonical_sha256(make_case())
    assert len(manifest["observed_sha256"]) == len(manifest["control_sha256"]) == 64


def test_the_same_inputs_give_the_same_files(tmp_path: Path) -> None:
    first, second = build(tmp_path), build(tmp_path)
    assert first.files == second.files
    assert first.folder_key == second.folder_key


def test_publication_creates_a_new_folder_with_the_three_files(tmp_path: Path) -> None:
    root = tmp_path / "calidad"
    folder = publish_quality(root, qa06(tmp_path), NOW)
    assert folder.parent == root / "SYNTHETIC_DEMO"
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [DETAIL_FILE, SUMMARY_FILE, MANIFEST_FILE]
    )
    assert folder.name.startswith("20261031T090000Z_")


def test_a_published_folder_is_never_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "calidad"
    publish_quality(root, qa06(tmp_path), NOW)
    with pytest.raises(FileExistsError):
        publish_quality(root, qa06(tmp_path), NOW)


@pytest.mark.parametrize("case_id", ["../fuera", "a/b", "con espacio", ".oculto"])
def test_a_case_id_that_is_not_a_safe_folder_name_is_rejected(tmp_path: Path, case_id: str) -> None:
    inputs = qa06(tmp_path)
    bad = replace(inputs, case=make_case(case_id))
    with pytest.raises(QualityError) as raised:
        build_report(bad, NOW)
    assert raised.value.field == "case_id"


def test_the_summary_records_each_fingerprint_on_its_own_side(tmp_path: Path) -> None:
    inputs = qa06(tmp_path)
    summary = json.loads(build_report(inputs, NOW).files[SUMMARY_FILE])
    assert summary["observed_sha256"] == inputs.comparison.observed_sha256
    assert summary["control_sha256"] == inputs.comparison.control_sha256
    assert summary["observed_sha256"] != summary["control_sha256"]


def test_the_folder_name_ends_with_the_fingerprint_of_the_detail(tmp_path: Path) -> None:
    report = build(tmp_path)
    detail_sha = hashlib.sha256(report.files[DETAIL_FILE]).hexdigest()
    assert report.folder_key.endswith("_" + detail_sha[:8])


def test_the_folder_time_is_in_utc_whatever_the_zone_of_the_clock(tmp_path: Path) -> None:
    local_clock = datetime(2026, 10, 31, 4, 0, 0, tzinfo=LIMA)
    report = build_report(qa06(tmp_path), local_clock)
    assert report.folder_key.startswith("20261031T090000Z_")
    manifest = json.loads(report.files[MANIFEST_FILE])
    assert manifest["created_at"] == "2026-10-31T09:00:00+00:00"


def test_qa06_the_catalog_case_with_known_gaps_gives_exact_errors_and_coverage(
    tmp_path: Path,
) -> None:
    """Control 100/0 y observado 90/5, con una fila faltante conocida en el segundo periodo.

    Error absoluto 10 y 5; relativo 0.1 y nulo; cobertura exacta: 900 s de una ventana de 1800 s.
    """
    observed = [
        *period("OBS_1", "CAMARA", W1, [90, 5, 50, 0]),
        *period("OBS_2", "CAMARA", W2, [80, 3, 40], KEYS[:3]),  # falta E_W / bus
    ]
    control = period("CTL_1", "MANUAL", W1, [100, 0, 50, 0])
    inputs = pipeline(tmp_path, observed, control)

    comparable = [window for window in inputs.comparison.windows if window.status == "comparable"]
    [window] = comparable
    found = {(c.movement_id, c.vehicle_class): c for c in window.counts}
    car, bus = found["N_S", "car"], found["N_S", "bus"]
    assert (car.absolute_value, car.relative_error) == (10, 0.1)
    assert (bus.absolute_value, bus.relative_error) == (5, None)
    assert bus.relative_reason == "control cero"

    coverage = inputs.coverage
    assert (coverage.window_s, coverage.covered_s, coverage.coverage) == (1800, 900, 0.5)
    assert [(g.start, g.end) for g in coverage.gaps] == [(_at(15), _at(30))]
    assert [(m.observation_id, m.movement_id, m.vehicle_class) for m in inputs.missing] == [
        ("OBS_2", "E_W", "bus")
    ]
