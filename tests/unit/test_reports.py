"""Publicación de los informes: carpeta nueva, manifiesto con huellas y lectura (DEV09 F2)."""

import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from html_checks import assert_safe_page
from quality_tools import DEMO_CASE_TEXT, write_case
from semaforo.app.report_inputs import CaseInputs, load_case_inputs
from semaforo.app.reports import (
    INDEX_FILE,
    MANIFEST_FILE,
    REPORTS,
    ReportManifest,
    publish_case_report,
    read_report,
)
from semaforo.dominio.errors import ErrorCode
from semaforo.trazabilidad.store import TrazabilidadError
from workspace_tools import writable

NOW = datetime(2026, 11, 1, 14, 0, 5, tzinfo=UTC)


def inputs_of(tmp_path: Path, text: str = DEMO_CASE_TEXT) -> CaseInputs:
    return load_case_inputs(write_case(tmp_path / "caso", text))


def published(tmp_path: Path, now: datetime = NOW, text: str = DEMO_CASE_TEXT) -> Path:
    return publish_case_report(tmp_path / "datos", inputs_of(tmp_path, text), now)


def test_the_report_is_published_in_its_own_new_folder(tmp_path: Path) -> None:
    folder = published(tmp_path)
    parent = tmp_path / "datos" / "reportes" / "informes" / "caso" / "SYNTHETIC_DEMO"
    assert folder.parent == parent
    assert (folder / INDEX_FILE).is_file()
    assert (folder / MANIFEST_FILE).is_file()
    assert sorted(path.name for path in folder.iterdir()) == [INDEX_FILE, MANIFEST_FILE]


def test_the_folder_name_has_the_time_and_the_short_hash_of_the_page(tmp_path: Path) -> None:
    folder = published(tmp_path)
    digest = hashlib.sha256((folder / INDEX_FILE).read_bytes()).hexdigest()
    assert folder.name == f"20261101T140005Z_{digest[:8]}"


def test_the_page_that_is_published_is_the_safe_one(tmp_path: Path) -> None:
    folder = published(tmp_path)
    seen = assert_safe_page((folder / INDEX_FILE).read_text(encoding="utf-8"))
    assert "Informe del caso: SYNTHETIC_DEMO" in seen.visible_text
    assert "Generado el 2026-11-01 14:00 UTC" in seen.visible_text


def test_the_manifest_lists_the_hash_of_each_file_and_of_the_inputs(tmp_path: Path) -> None:
    folder = published(tmp_path)
    manifest = read_report(folder)
    inputs = inputs_of(tmp_path)
    assert manifest.kind == "caso"
    assert manifest.case_id == "SYNTHETIC_DEMO"
    assert manifest.created_at == "2026-11-01T14:00:05+00:00"
    assert manifest.files == {
        INDEX_FILE: hashlib.sha256((folder / INDEX_FILE).read_bytes()).hexdigest()
    }
    assert manifest.inputs == {"case_sha256": inputs.report.case_sha256}


def test_the_manifest_is_readable_json_with_the_accents_kept(tmp_path: Path) -> None:
    raw = (published(tmp_path) / MANIFEST_FILE).read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert json.loads(raw)["schema_version"] == "1.0.0"


def test_the_files_are_read_only(tmp_path: Path) -> None:
    folder = published(tmp_path)
    for name in (INDEX_FILE, MANIFEST_FILE):
        assert not (os.stat(folder / name).st_mode & stat.S_IWRITE)


def test_a_report_is_never_overwritten(tmp_path: Path) -> None:
    published(tmp_path)
    with pytest.raises(TrazabilidadError) as raised:
        published(tmp_path)
    assert raised.value.code == ErrorCode.RUN_EXISTS


def test_another_moment_gives_another_report_and_the_first_stays(tmp_path: Path) -> None:
    first = published(tmp_path)
    second = published(tmp_path, NOW + timedelta(seconds=1))
    assert first != second
    assert first.is_dir()
    assert second.is_dir()
    assert first.parent == second.parent


def test_a_moment_with_another_time_zone_is_written_in_utc(tmp_path: Path) -> None:
    lima = datetime(2026, 11, 1, 9, 0, 5, tzinfo=timezone(timedelta(hours=-5)))
    folder = published(tmp_path, lima)
    assert folder.name.startswith("20261101T140005Z_")
    assert read_report(folder).created_at == "2026-11-01T14:00:05+00:00"


def test_accents_in_the_manifest_are_written_as_utf8_not_as_escapes(tmp_path: Path) -> None:
    folder = published(tmp_path, text=case_named("Cañón"))
    raw = (folder / MANIFEST_FILE).read_bytes()
    assert "Cañón".encode() in raw
    assert rb"\u00f1" not in raw


def test_without_a_moment_it_uses_the_current_time(tmp_path: Path) -> None:
    folder = publish_case_report(tmp_path / "datos", inputs_of(tmp_path))
    assert read_report(folder).case_id == "SYNTHETIC_DEMO"
    assert abs(datetime.now(UTC) - datetime.fromisoformat(read_report(folder).created_at)) < (
        timedelta(minutes=5)
    )


def test_the_workspace_folder_is_created_if_it_does_not_exist(tmp_path: Path) -> None:
    workspace = tmp_path / "nuevo" / "datos"
    folder = publish_case_report(workspace, inputs_of(tmp_path), NOW)
    assert folder.is_relative_to(workspace / REPORTS)


# --- lectura verificada -----------------------------------------------------------------------


def test_a_changed_page_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    writable(folder / INDEX_FILE).write_text("<h1>otro</h1>", encoding="utf-8")
    with pytest.raises(TrazabilidadError) as raised:
        read_report(folder)
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_an_extra_file_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    (folder / "sobra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(TrazabilidadError) as raised:
        read_report(folder)
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_a_missing_page_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    writable(folder / INDEX_FILE).unlink()
    with pytest.raises(TrazabilidadError) as raised:
        read_report(folder)
    assert raised.value.code == ErrorCode.HASH_MISMATCH


def test_a_manifest_in_another_format_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    writable(folder / MANIFEST_FILE).write_text('{"kind": "otro"}', encoding="utf-8")
    with pytest.raises(TrazabilidadError) as raised:
        read_report(folder)
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_a_missing_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TrazabilidadError) as raised:
        read_report(tmp_path / "no-existe")
    assert raised.value.code == ErrorCode.INPUT_SCHEMA


def test_the_manifest_model_accepts_both_kinds_and_nothing_else() -> None:
    base: dict[str, object] = {"created_at": "x", "case_id": None, "inputs": {}, "files": {}}
    assert ReportManifest.model_validate({**base, "kind": "caso"}).kind == "caso"
    assert ReportManifest.model_validate({**base, "kind": "datos"}).kind == "datos"
    with pytest.raises(ValueError, match="kind"):
        ReportManifest.model_validate({**base, "kind": "otro"})
    with pytest.raises(ValueError, match="extra"):
        ReportManifest.model_validate({**base, "kind": "caso", "extra": 1})


# --- el nombre de la carpeta ------------------------------------------------------------------


def case_named(identifier: str) -> str:
    data = json.loads(DEMO_CASE_TEXT)
    data["case_id"] = identifier
    return json.dumps(data)


@pytest.mark.parametrize(
    "identifier", ["../fuera", "a/b", "a\\b", "<script>", "con espacio", ".oculto", "a:b"]
)
def test_an_identifier_that_is_not_a_safe_folder_name_is_published_as_unidentified(
    tmp_path: Path, identifier: str
) -> None:
    folder = published(tmp_path, text=case_named(identifier))
    assert folder.parent.name == "sin-identificar"
    assert folder.is_relative_to(tmp_path / "datos" / REPORTS)
    assert read_report(folder).case_id == identifier


@pytest.mark.parametrize("identifier", ["CASO-001", "caso_1.2", "A", "a.b-c_d"])
def test_a_safe_identifier_names_the_folder(tmp_path: Path, identifier: str) -> None:
    assert published(tmp_path, text=case_named(identifier)).parent.name == identifier


def test_a_case_without_identity_is_published_as_unidentified(tmp_path: Path) -> None:
    folder = published(tmp_path, text="{}")
    assert folder.parent.name == "sin-identificar"
    manifest = read_report(folder)
    assert manifest.case_id is None
    assert manifest.inputs == {}
