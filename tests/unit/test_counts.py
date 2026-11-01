"""Pruebas de importación y normalización de aforos (DEV04, HU02): QA03, QA04 y QA05."""

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from semaforo.datos.importer import CountImportError, read_counts
from semaforo.datos.normalizer import prepare_counts
from semaforo.dominio.case import Case, parse_case

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COUNTS = FIXTURES / "aforos.csv"
DEMO_CASE = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
COLUMNS = [
    "case_id",
    "observation_id",
    "source_id",
    "origin",
    "start",
    "end",
    "movement_id",
    "vehicle_class",
    "count",
    "quality_state",
]
HEADER = ",".join(COLUMNS)
PERIOD = "2026-10-18T08:00:00-05:00,2026-10-18T08:15:00-05:00"
VALID_ROWS = [
    "SYNTHETIC_DEMO,OBS_DEMO,SYNTHETIC_FIXTURE,synthetic," + PERIOD + ",N_S,car,90,observed",
    "SYNTHETIC_DEMO,OBS_DEMO,SYNTHETIC_FIXTURE,synthetic," + PERIOD + ",N_S,bus,10,observed",
    "SYNTHETIC_DEMO,OBS_DEMO,SYNTHETIC_FIXTURE,synthetic," + PERIOD + ",E_W,car,50,observed",
    "SYNTHETIC_DEMO,OBS_DEMO,SYNTHETIC_FIXTURE,synthetic," + PERIOD + ",E_W,bus,0,observed",
]


def make_case() -> Case:
    return parse_case(copy.deepcopy(DEMO_CASE))


def write(tmp_path: Path, rows: list[str], header: str = HEADER) -> Path:
    path = tmp_path / "aforos.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def issues_of(path: Path) -> list[tuple[int | None, str | None]]:
    with pytest.raises(CountImportError) as raised:
        read_counts(path, make_case())
    return [(issue.line, issue.field) for issue in raised.value.issues]


def row(**changes: str) -> str:
    """Una fila válida (la de N_S, clase car) con los campos cambiados."""
    fields = dict(zip(COLUMNS, VALID_ROWS[0].split(","), strict=True))
    fields.update(changes)
    return ",".join(fields[name] for name in COLUMNS)


# QA03: normalización del caso de 90 autos y 10 buses en 900 s.


def test_the_fixture_normalizes_to_the_expected_flows_and_proportions() -> None:
    prepared = prepare_counts(COUNTS, make_case())
    [period] = prepared.periods
    assert period.status == "complete"
    assert period.duration_s == 900
    flows = {m.movement_id: m for m in period.movements}
    assert flows["N_S"].flow_vph == 400
    assert dict(flows["N_S"].composition) == {"car": 0.9, "bus": 0.1}
    assert flows["E_W"].flow_vph == 200
    assert dict(flows["E_W"].composition) == {"car": 1.0, "bus": 0.0}


def test_the_original_file_is_read_without_changing_a_byte(tmp_path: Path) -> None:
    source = tmp_path / "original.csv"
    source.write_bytes(COUNTS.read_bytes())
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    prepared = prepare_counts(source, make_case())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert prepared.source_sha256 == before


def test_a_utf8_file_with_bom_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "con_bom.csv"
    path.write_bytes("﻿".encode() + COUNTS.read_bytes())
    assert len(read_counts(path, make_case()).rows) == 4


def test_a_blank_line_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "con_vacia.csv"
    path.write_text("\n".join([HEADER, *VALID_ROWS, "", ""]) + "\n", encoding="utf-8")
    assert len(read_counts(path, make_case()).rows) == 4


# QA04: archivos con defectos. Ninguno se acepta, y cada error queda identificado.


def test_a_missing_column_in_the_header_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, VALID_ROWS, header=HEADER.replace(",quality_state", ""))
    assert issues_of(path) == [(1, None)]


def test_an_empty_mandatory_field_is_reported_with_its_line(tmp_path: Path) -> None:
    path = write(tmp_path, [row(source_id=""), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, "source_id")]


def test_a_row_with_the_wrong_number_of_fields_is_reported(tmp_path: Path) -> None:
    path = write(tmp_path, [VALID_ROWS[0] + ",extra", *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, None)]


def test_a_duplicated_key_is_rejected_and_not_added(tmp_path: Path) -> None:
    path = write(tmp_path, [*VALID_ROWS, row(count="5")])
    assert issues_of(path) == [(6, "observation_id")]


def test_a_negative_count_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, [row(count="-1"), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, "count")]


@pytest.mark.parametrize("count", ["1.5", "dos", "1e3", "+5"])
def test_a_count_that_is_not_a_whole_number_is_rejected(tmp_path: Path, count: str) -> None:
    path = write(tmp_path, [row(count=count), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, "count")]


def test_an_empty_count_is_a_missing_field_not_a_zero(tmp_path: Path) -> None:
    path = write(tmp_path, [row(count=""), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, "count")]


def test_an_unknown_vehicle_class_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, [row(vehicle_class="truck"), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, "vehicle_class")]


def test_an_unknown_movement_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, [row(movement_id="X_Y"), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, "movement_id")]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"start": "2026-10-18 08:00"}, "start"),
        ({"start": "2026-13-18T08:00:00-05:00"}, "start"),
        ({"end": "2026-10-18T08:15:00"}, "end"),
        ({"end": "2026-10-18T07:45:00-05:00"}, "end"),
        ({"end": "2026-10-18T08:00:00-05:00"}, "end"),
    ],
)
def test_an_invalid_or_inverted_date_is_rejected(
    tmp_path: Path, changes: dict[str, str], field: str
) -> None:
    path = write(tmp_path, [row(**changes), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, field)]


def test_rows_of_one_period_must_share_its_start_and_end(tmp_path: Path) -> None:
    other_hour = row(start="2026-10-18T09:00:00-05:00", end="2026-10-18T09:15:00-05:00")
    path = write(tmp_path, [VALID_ROWS[0], other_hour, *VALID_ROWS[2:]])
    assert issues_of(path) == [(3, "start")]


def test_a_quality_state_outside_the_allowed_values_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, [row(quality_state="estimated"), *VALID_ROWS[1:]])
    assert issues_of(path) == [(2, "quality_state")]


def test_a_count_from_another_case_or_origin_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        [row(case_id="OTRO", origin="field"), *VALID_ROWS[1:]],
    )
    assert issues_of(path) == [(2, "case_id"), (2, "origin")]


def test_every_problem_is_reported_not_only_the_first(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        [row(count="-1"), row(vehicle_class="truck"), row(start="sin-fecha"), *VALID_ROWS[1:]],
    )
    assert issues_of(path) == [(2, "count"), (3, "vehicle_class"), (4, "start")]


def test_a_file_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "latin.csv"
    path.write_bytes(HEADER.encode() + b"\n" + "ñ".encode("latin-1") + b"\n")
    assert issues_of(path) == [(None, None)]


def test_a_file_above_the_size_limit_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CountImportError) as raised:
        read_counts(COUNTS, make_case(), max_bytes=10)
    assert raised.value.issues[0].line is None


def test_a_missing_file_is_rejected_with_a_reason(tmp_path: Path) -> None:
    with pytest.raises(CountImportError) as raised:
        read_counts(tmp_path / "no_existe.csv", make_case())
    assert "no se puede leer" in raised.value.issues[0].message


# QA05: ceros y faltantes. Un cero conserva volumen 0; un faltante no se convierte en cero.


def test_an_observed_zero_keeps_zero_volume_and_no_composition(tmp_path: Path) -> None:
    zeros = [row(count="0"), row(movement_id="N_S", vehicle_class="bus", count="0")]
    path = write(
        tmp_path,
        [*zeros, *VALID_ROWS[2:]],
    )
    [period] = prepare_counts(path, make_case()).periods
    assert period.status == "complete"
    flows = {m.movement_id: m for m in period.movements}
    assert flows["N_S"].flow_vph == 0
    assert dict(flows["N_S"].composition) == {"car": None, "bus": None}


def test_a_missing_row_makes_the_period_incomplete_and_is_not_zero(tmp_path: Path) -> None:
    path = write(tmp_path, VALID_ROWS[:3])
    [period] = prepare_counts(path, make_case()).periods
    assert period.status == "incomplete"
    assert period.movements == ()
    assert period.missing == (("E_W", "bus"),)


def test_complete_and_incomplete_periods_are_kept_apart(tmp_path: Path) -> None:
    second = (
        "SYNTHETIC_DEMO,OBS_2,SYNTHETIC_FIXTURE,synthetic,"
        "2026-10-18T08:15:00-05:00,2026-10-18T08:30:00-05:00"
    )
    rows = [
        *VALID_ROWS,
        *[f"{second},{tail}" for tail in ("N_S,car,30,observed", "N_S,bus,10,observed")],
    ]
    prepared = prepare_counts(write(tmp_path, rows), make_case())
    statuses = {period.observation_id: period.status for period in prepared.periods}
    assert statuses == {"OBS_DEMO": "complete", "OBS_2": "incomplete"}
    assert prepared.periods[0].observation_id == "OBS_DEMO"


def test_the_fixture_round_trips_to_the_recorded_expectations() -> None:
    expected = json.loads((FIXTURES / "expected_normalization.json").read_text(encoding="utf-8"))
    [period] = prepare_counts(COUNTS, make_case()).periods
    assert period.duration_s == expected["period_s"]
    for movement in period.movements:
        assert movement.flow_vph == expected[movement.movement_id]["flow_vph"]
        for vclass, share in expected[movement.movement_id].items():
            if vclass in ("flow_vph",):
                continue
            assert movement.composition[vclass] == share


# QA04 (texto literal del catálogo): campo ausente, duplicado, -1, clase desconocida y fecha
# inválida. Cada archivo se rechaza al importar y tampoco pasa por la normalización: ninguna
# aceptación silenciosa. El reporte señala la fila y el campo.


def qa04_missing_field(tmp_path: Path) -> Path:
    return write(tmp_path, [row(source_id=""), *VALID_ROWS[1:]])


def qa04_duplicate(tmp_path: Path) -> Path:
    return write(tmp_path, [*VALID_ROWS, row(count="5")])


def qa04_minus_one(tmp_path: Path) -> Path:
    return write(tmp_path, [row(count="-1"), *VALID_ROWS[1:]])


def qa04_unknown_class(tmp_path: Path) -> Path:
    return write(tmp_path, [row(vehicle_class="truck"), *VALID_ROWS[1:]])


def qa04_invalid_date(tmp_path: Path) -> Path:
    return write(tmp_path, [row(start="2026-13-18T08:00:00-05:00"), *VALID_ROWS[1:]])


@pytest.mark.parametrize(
    ("build", "line", "field"),
    [
        (qa04_missing_field, 2, "source_id"),
        (qa04_duplicate, 6, "observation_id"),
        (qa04_minus_one, 2, "count"),
        (qa04_unknown_class, 2, "vehicle_class"),
        (qa04_invalid_date, 2, "start"),
    ],
    ids=["missing-field", "duplicate", "minus-one", "unknown-class", "invalid-date"],
)
def test_qa04_each_defect_of_the_catalog_is_identified_and_never_accepted(
    tmp_path: Path, build: Callable[[Path], Path], line: int, field: str
) -> None:
    path = build(tmp_path)
    assert issues_of(path) == [(line, field)]
    with pytest.raises(CountImportError) as raised:
        prepare_counts(path, make_case())
    assert [(i.line, i.field) for i in raised.value.issues] == [(line, field)]
    assert all(i.message for i in raised.value.issues)
