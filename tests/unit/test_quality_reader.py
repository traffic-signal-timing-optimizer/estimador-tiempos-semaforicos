"""Lectura tipada y verificada del reporte de calidad publicado (DEV09 F1, decisión D6)."""

import hashlib
import json
from pathlib import Path

import pytest

from quality_tools import KEYS, W1, period, publish_demo_quality
from semaforo.datos import quality_report
from semaforo.datos.quality_report import (
    DETAIL_FILE,
    MANIFEST_FILE,
    SUMMARY_FILE,
    QualityRow,
    read_quality_data,
)
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.store import TrazabilidadError
from workspace_tools import writable

W2 = ("2026-10-18T08:15:00-05:00", "2026-10-18T08:30:00-05:00")
CRLF_HEADER = ";".join(quality_report.DETAIL_HEADER)


def published(
    tmp_path: Path,
    *,
    observed: list[str] | None = None,
    control: list[str] | None = None,
    limit: float | None = None,
) -> Path:
    return publish_demo_quality(
        tmp_path / "calidad", tmp_path / "trabajo", observed=observed, control=control, limit=limit
    )


def rewrite(folder: Path, name: str, data: bytes) -> None:
    """Cambia un archivo publicado y actualiza su huella en el manifiesto (una alteración hábil)."""
    writable(folder / name).write_bytes(data)
    manifest_path = writable(folder / MANIFEST_FILE)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = hashlib.sha256(data).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")


def detail_with(*lines: str, header: str = CRLF_HEADER) -> bytes:
    return ("\r\n".join([header, *lines]) + "\r\n").encode("utf-8-sig")


GOOD_ROW = (
    '="OBS";="MANUAL";2026-10-18T08:00:00-05:00;2026-10-18T08:15:00-05:00;'
    '="N_S";="car";90;100;-10;0.100;;comparable;'
)


def rejects(folder: Path, message: str) -> None:
    with pytest.raises(TrazabilidadError, match=message) as raised:
        read_quality_data(folder)
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def row_of(data_rows: list[QualityRow], movement: str | None, vclass: str | None) -> QualityRow:
    return next(r for r in data_rows if (r.movement_id, r.vehicle_class) == (movement, vclass))


# --- lo que se lee ----------------------------------------------------------------------------


def test_the_qa06_rows_are_read_with_their_numbers_and_reasons(tmp_path: Path) -> None:
    data = read_quality_data(published(tmp_path))
    assert len(data.rows) == 4
    car = row_of(data.rows, "N_S", "car")
    assert (car.observed, car.control, car.absolute_error, car.relative_error) == (
        90,
        100,
        -10,
        0.1,
    )
    assert (car.status, car.status_reason, car.relative_reason) == ("comparable", None, None)
    assert (car.observation_id, car.control_source_id) == ("OBS", "MANUAL")
    bus = row_of(data.rows, "N_S", "bus")
    assert (bus.observed, bus.control, bus.absolute_error) == (5, 0, 5)
    assert (bus.relative_error, bus.relative_reason) == (None, "control cero")


def test_a_true_zero_is_a_zero_and_not_a_missing_value(tmp_path: Path) -> None:
    rows = read_quality_data(published(tmp_path)).rows
    zero = row_of(rows, "E_W", "bus")
    assert (zero.observed, zero.control, zero.absolute_error) == (0, 0, 0)
    assert zero.status == "comparable"


def test_a_missing_row_makes_the_window_not_comparable_with_no_numbers(tmp_path: Path) -> None:
    short = period("OBS", "CAMARA", W1, [1, 1, 1], KEYS[:3])
    folder = published(tmp_path, observed=short, control=period("CTL", "MANUAL", W1, [1, 1, 1, 1]))
    [row] = read_quality_data(folder).rows
    assert row.status == "no comparable"
    assert "E_W/bus" in str(row.status_reason)
    assert (row.movement_id, row.vehicle_class) == (None, None)
    assert (row.observed, row.control, row.absolute_error, row.relative_error) == (
        None,
        None,
        None,
        None,
    )


def test_a_window_without_a_pair_is_one_row_that_says_so(tmp_path: Path) -> None:
    folder = published(
        tmp_path,
        observed=period("OBS", "CAMARA", W1, [1, 1, 1, 1]),
        control=period("CTL", "MANUAL", W2, [1, 1, 1, 1]),
    )
    rows = read_quality_data(folder).rows
    assert [r.status for r in rows] == ["sin pareja", "sin pareja"]
    assert "solo existe en el conteo principal" in str(rows[0].status_reason)


def test_an_excluded_comparison_keeps_its_cause(tmp_path: Path) -> None:
    data = read_quality_data(published(tmp_path, limit=0.05))
    car = row_of(data.rows, "N_S", "car")
    assert car.status == "excluido"
    assert "supera el límite 0.05" in str(car.status_reason)
    assert data.summary.max_relative_error == 0.05
    [exclusion] = data.summary.exclusions
    assert (exclusion.movement_id, exclusion.vehicle_class) == ("N_S", "car")
    assert exclusion.relative_error == 0.1


def test_the_summary_is_read_with_exact_coverage(tmp_path: Path) -> None:
    summary = read_quality_data(published(tmp_path)).summary
    assert summary.window.declared is True
    assert (summary.window.window_s, summary.window.covered_s) == (1800, 900)
    assert summary.window.coverage == 0.5
    assert summary.windows_by_status["comparable"] == 1
    assert [(m.movement_id, m.coverage) for m in summary.per_movement] == [
        ("N_S", 0.5),
        ("E_W", 0.5),
    ]
    assert len(summary.gaps) == 1
    assert summary.missing == []


def test_the_manifest_comes_with_the_data(tmp_path: Path) -> None:
    data = read_quality_data(published(tmp_path))
    assert data.manifest.case_id == "SYNTHETIC_DEMO"
    assert set(data.manifest.files) == {DETAIL_FILE, SUMMARY_FILE}


# --- identificadores y formato ----------------------------------------------------------------


def test_identifiers_with_quotes_and_semicolons_are_read_back_as_written(tmp_path: Path) -> None:
    folder = published(tmp_path)
    odd = GOOD_ROW.replace('="OBS"', '"=""A""""B;C"""')
    rewrite(folder, DETAIL_FILE, detail_with(odd))
    [row] = read_quality_data(folder).rows
    assert row.observation_id == 'A"B;C'
    assert row.control_source_id == "MANUAL"


def test_an_empty_identifier_is_empty(tmp_path: Path) -> None:
    folder = published(tmp_path)
    rewrite(folder, DETAIL_FILE, detail_with(GOOD_ROW.replace('="MANUAL"', '=""')))
    assert read_quality_data(folder).rows[0].control_source_id == ""


def test_a_hand_written_good_row_is_read(tmp_path: Path) -> None:
    folder = published(tmp_path)
    rewrite(folder, DETAIL_FILE, detail_with(GOOD_ROW))
    [row] = read_quality_data(folder).rows
    assert (row.movement_id, row.vehicle_class, row.observed, row.relative_error) == (
        "N_S",
        "car",
        90,
        0.1,
    )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (GOOD_ROW + ";extra", "no tiene 13 columnas"),
        (GOOD_ROW.replace(";comparable;", ";bueno;"), "estado desconocido"),
        (GOOD_ROW.replace("2026-10-18T08:00:00-05:00", "ayer"), "fecha inválida"),
        (GOOD_ROW.replace(";90;", ";noventa;"), "conteo que no es entero"),
        (GOOD_ROW.replace(";90;", ";9.0;"), "conteo que no es entero"),
        (GOOD_ROW.replace(";0.100;", ";diez;"), "error relativo mal escrito"),
        (GOOD_ROW.replace('="OBS"', "OBS"), "identificador mal formado"),
        (GOOD_ROW.replace('="N_S"', "N_S"), "identificador mal formado"),
        (GOOD_ROW.replace('="OBS"', '="O"B"'), "identificador mal formado"),
    ],
)
def test_a_malformed_row_is_refused_with_its_line(tmp_path: Path, row: str, message: str) -> None:
    folder = published(tmp_path)
    rewrite(folder, DETAIL_FILE, detail_with(GOOD_ROW, row))
    rejects(folder, rf"la línea 3 .*{message}")


def test_a_row_with_too_few_columns_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    short = GOOD_ROW.rsplit(";", 2)[0]
    rewrite(folder, DETAIL_FILE, detail_with(GOOD_ROW, short))
    rejects(folder, "la línea 3 no tiene 13 columnas")


def test_a_row_with_an_invalid_end_date_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    broken = GOOD_ROW.replace("2026-10-18T08:15:00-05:00", "mañana")
    rewrite(folder, DETAIL_FILE, detail_with(broken))
    rejects(folder, "la línea 2 tiene una fecha inválida")


def test_a_wrong_header_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    rewrite(folder, DETAIL_FILE, detail_with(GOOD_ROW, header="a;b;c"))
    rejects(folder, "el encabezado no es el de la planilla de calidad")


def test_an_empty_sheet_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    rewrite(folder, DETAIL_FILE, b"")
    rejects(folder, "el encabezado no es el de la planilla de calidad")


def test_a_sheet_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    rewrite(folder, DETAIL_FILE, b"\xff\xfe\x00\x00 no es texto")
    rejects(folder, "no es una planilla de texto válida")


def test_a_header_only_sheet_has_no_rows(tmp_path: Path) -> None:
    folder = published(tmp_path)
    rewrite(folder, DETAIL_FILE, detail_with())
    assert read_quality_data(folder).rows == []


# --- el resumen y el manifiesto ---------------------------------------------------------------


def summary_of(folder: Path) -> dict[str, object]:
    return json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8"))


def put_summary(folder: Path, data: dict[str, object]) -> None:
    rewrite(folder, SUMMARY_FILE, (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))


def test_a_summary_with_another_format_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    data = summary_of(folder)
    del data["window"]
    put_summary(folder, data)
    rejects(folder, "no tiene el formato de un resumen de calidad")


def test_a_summary_that_is_not_json_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    rewrite(folder, SUMMARY_FILE, b"{no es json")
    rejects(folder, "no tiene el formato de un resumen de calidad")


def test_a_summary_with_an_unknown_field_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    data = summary_of(folder)
    data["extra"] = 1
    put_summary(folder, data)
    rejects(folder, "no tiene el formato de un resumen de calidad")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_id", "OTRO"),
        ("observed_sha256", "0" * 64),
        ("control_sha256", "1" * 64),
        ("max_relative_error", 0.5),
    ],
)
def test_a_summary_that_disagrees_with_the_manifest_is_refused(
    tmp_path: Path, field: str, value: object
) -> None:
    folder = published(tmp_path)
    data = summary_of(folder)
    data[field] = value
    put_summary(folder, data)
    rejects(folder, f"{field} no coincide con el manifiesto")


# --- integridad -------------------------------------------------------------------------------


def test_a_changed_file_is_refused_by_its_hash(tmp_path: Path) -> None:
    folder = published(tmp_path)
    writable(folder / DETAIL_FILE).write_bytes(b"cambiado")
    with pytest.raises(TrazabilidadError) as raised:
        read_quality_data(folder)
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_an_extra_file_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    (folder / "sobra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(TrazabilidadError) as raised:
        read_quality_data(folder)
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_a_file_changed_after_the_folder_was_verified_is_not_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = published(tmp_path)
    original = quality_report.read_quality_report

    def verify_then_change(path: Path) -> quality_report.QualityManifest:
        manifest = original(path)
        writable(path / DETAIL_FILE).write_bytes(detail_with(GOOD_ROW))
        return manifest

    monkeypatch.setattr(quality_report, "read_quality_report", verify_then_change)
    with pytest.raises(TrazabilidadError, match="modificado") as raised:
        read_quality_data(folder)
    assert raised.value.code == ErrorCode.HASH_MISMATCH
    assert raised.value.field == DETAIL_FILE


def test_a_manifest_that_does_not_list_the_sheet_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    manifest_path = writable(folder / MANIFEST_FILE)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in (DETAIL_FILE, SUMMARY_FILE):
        writable(folder / name).unlink()
        del manifest["files"][name]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    rejects(folder, "calidad.csv: el manifiesto no lo incluye")


def test_a_file_over_the_limit_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = published(tmp_path)
    monkeypatch.setattr(quality_report, "MAX_FILE_BYTES", 10)
    rejects(folder, "es demasiado grande")


def test_a_file_exactly_at_the_limit_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = published(tmp_path)
    size = max((folder / name).stat().st_size for name in (DETAIL_FILE, SUMMARY_FILE))
    monkeypatch.setattr(quality_report, "MAX_FILE_BYTES", size)
    assert len(read_quality_data(folder).rows) == 4


def test_a_missing_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TrazabilidadError) as raised:
        read_quality_data(tmp_path / "no-existe")
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_a_folder_that_is_a_link_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    link = tmp_path / "enlace"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    with pytest.raises(TrazabilidadError) as raised:
        read_quality_data(link)
    assert raised.value.code == ErrorCode.PATH_NOT_ALLOWED
