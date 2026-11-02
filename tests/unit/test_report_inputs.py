"""Entradas de las vistas de Caso y de Datos (DEV09 F1, decisiones D4 y D5)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from quality_tools import DEMO_CASE_TEXT, demo_case, publish_demo_quality, write_case
from semaforo.app import report_inputs
from semaforo.app.report_inputs import load_case_inputs, load_data_inputs
from semaforo.caso.case_report_models import CaseReport, ReportStatus
from semaforo.caso.errors import CasoError
from semaforo.dominio.case import canonical_sha256
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad.store import TrazabilidadError
from workspace_tools import writable


def case_text(**changes: object) -> str:
    data = json.loads(DEMO_CASE_TEXT)
    data.update(changes)
    return json.dumps(data)


def incoherent_case_text() -> str:
    """Un caso con estructura válida pero un grupo que apunta a un tramo que no existe."""
    data = json.loads(DEMO_CASE_TEXT)
    data["green_groups"][0]["slot_ids"] = ["NO_EXISTE"]
    return json.dumps(data)


def code_of(error: DomainError) -> ErrorCode:
    return error.code


# --- vista del caso ---------------------------------------------------------------------------


def test_a_valid_case_comes_with_its_report_and_its_content(tmp_path: Path) -> None:
    inputs = load_case_inputs(write_case(tmp_path))
    assert inputs.report.status in {"valid", "valid_with_warnings"}
    assert inputs.case is not None
    assert inputs.report.case_sha256 == canonical_sha256(inputs.case)
    assert inputs.case.case_id == "SYNTHETIC_DEMO"
    assert inputs.report.origin == "synthetic"


def test_an_incoherent_case_is_shown_through_its_report_without_the_case(tmp_path: Path) -> None:
    inputs = load_case_inputs(write_case(tmp_path, incoherent_case_text()))
    assert inputs.case is None
    assert inputs.report.status == "invalid"
    assert inputs.report.case_sha256 is not None
    failed = [rule.rule_id for rule in inputs.report.rules if rule.status == "failed"]
    assert failed


def test_a_case_without_structure_is_shown_through_its_report(tmp_path: Path) -> None:
    inputs = load_case_inputs(write_case(tmp_path, "{}"))
    assert inputs.case is None
    assert inputs.report.status == "invalid"
    assert inputs.report.case_sha256 is None


def test_a_case_that_is_not_json_is_shown_through_its_report(tmp_path: Path) -> None:
    inputs = load_case_inputs(write_case(tmp_path, "esto no es json"))
    assert inputs.case is None
    assert inputs.report.status == "invalid"


def test_a_missing_case_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        load_case_inputs(tmp_path / "no-existe.json")
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_a_case_path_that_is_a_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        load_case_inputs(tmp_path)
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_a_case_file_that_is_a_link_is_refused(tmp_path: Path) -> None:
    real = write_case(tmp_path / "real")
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    with pytest.raises(CasoError) as raised:
        load_case_inputs(link)
    assert raised.value.code == ErrorCode.PATH_NOT_ALLOWED


def valid_report(case_sha256: str | None, status: ReportStatus = "valid") -> CaseReport:
    return CaseReport(
        case_id="SYNTHETIC_DEMO",
        case_version="1.0.0",
        origin="synthetic",
        representation_status="synthetic_fixture",
        case_sha256=case_sha256,
        status=status,
        exit_code=0,
        network="not_declared",
        limits=None,
        error=None,
        rules=[],
    )


def returning(report: CaseReport) -> Callable[[Path], CaseReport]:
    """Un ``validate_case`` que siempre devuelve ``report``: otra lectura del mismo archivo."""

    def validate(_path: Path) -> CaseReport:
        return report

    return validate


def test_a_case_that_changes_between_the_two_readings_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_case(tmp_path)
    monkeypatch.setattr(report_inputs, "validate_case", returning(valid_report("0" * 64)))
    with pytest.raises(CasoError, match="cambió mientras se leía") as raised:
        load_case_inputs(path)
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_a_case_that_was_invalid_and_became_valid_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_case(tmp_path, incoherent_case_text())
    digest = canonical_sha256(demo_case())
    monkeypatch.setattr(report_inputs, "validate_case", returning(valid_report(digest)))
    with pytest.raises(CasoError, match="cambió mientras se leía"):
        load_case_inputs(path)


def test_a_case_that_became_unreadable_between_readings_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_case(tmp_path)
    unreadable = valid_report(None, "invalid").model_copy(
        update={"error": "ya no se puede leer", "exit_code": 5}
    )
    monkeypatch.setattr(report_inputs, "validate_case", returning(unreadable))
    with pytest.raises(CasoError, match="ya no se puede leer") as raised:
        load_case_inputs(path)
    assert raised.value.code == ErrorCode.PATH_NOT_ALLOWED


# --- vista de datos ---------------------------------------------------------------------------


def quality_for(tmp_path: Path) -> Path:
    return publish_demo_quality(tmp_path / "calidad", tmp_path / "trabajo")


def test_the_data_of_a_case_come_with_its_quality_report(tmp_path: Path) -> None:
    inputs = load_data_inputs(write_case(tmp_path / "caso"), quality_for(tmp_path))
    assert inputs.quality.manifest.case_id == inputs.case.report.case_id == "SYNTHETIC_DEMO"
    assert len(inputs.quality.rows) == 4
    assert inputs.quality.manifest.case_sha256 == inputs.case.report.case_sha256


def test_a_quality_report_of_another_case_is_refused(tmp_path: Path) -> None:
    other = write_case(tmp_path / "caso", case_text(case_id="OTRO_CASO"))
    with pytest.raises(TrazabilidadError, match="de otro caso") as raised:
        load_data_inputs(other, quality_for(tmp_path))
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_a_case_edited_after_the_quality_report_is_refused(tmp_path: Path) -> None:
    edited = write_case(tmp_path / "caso", case_text(description="otra descripción"))
    with pytest.raises(TrazabilidadError, match="cambió desde que se generó") as raised:
        load_data_inputs(edited, quality_for(tmp_path))
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_a_case_without_structure_cannot_be_linked_to_the_report(tmp_path: Path) -> None:
    broken = write_case(tmp_path / "caso", "{}")
    with pytest.raises(CasoError, match="sin su huella") as raised:
        load_data_inputs(broken, quality_for(tmp_path))
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_an_incoherent_case_can_still_be_linked_to_its_report(tmp_path: Path) -> None:
    folder = quality_for(tmp_path)
    case = write_case(tmp_path / "caso", incoherent_case_text())
    # La huella del caso incoherente no es la del reporte: se rechaza por eso, no por no leerse.
    with pytest.raises(TrazabilidadError, match="cambió desde que se generó"):
        load_data_inputs(case, folder)


def test_an_altered_quality_report_is_refused(tmp_path: Path) -> None:
    folder = quality_for(tmp_path)
    writable(folder / "calidad.csv").write_bytes(b"cambiado")
    with pytest.raises(TrazabilidadError) as raised:
        load_data_inputs(write_case(tmp_path / "caso"), folder)
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_a_missing_quality_report_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TrazabilidadError) as raised:
        load_data_inputs(write_case(tmp_path / "caso"), tmp_path / "no-existe")
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_the_case_is_checked_before_the_quality_report_is_opened(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        load_data_inputs(tmp_path / "no-existe.json", quality_for(tmp_path))
    assert raised.value.code == ErrorCode.INPUT_SCHEMA
