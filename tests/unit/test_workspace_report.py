"""Revisión del espacio de trabajo sin SUMO: estados especiales y reportes de calidad (DEV08 F2)."""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.app.integrity import QUALITY, verify_workspace
from semaforo.datos.quality_report import QualityManifest
from semaforo.trazabilidad.fs import publish_files, remove_tree
from semaforo.trazabilidad.store import RunSpec, RunWriter

NOW = datetime(2026, 11, 1, 22, 0, tzinfo=UTC)
DETAIL = b"col;valor\r\n"


def clock() -> datetime:
    return NOW


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    yield root
    remove_tree(root)


def quality(workspace: Path, name: str = "Q1") -> Path:
    manifest = QualityManifest(
        schema_version="1.0.0",
        created_at=NOW.isoformat(),
        case_id="CASO_A",
        case_sha256="a" * 64,
        observed_sha256="b" * 64,
        control_sha256="c" * 64,
        max_relative_error=None,
        files={"calidad.csv": hashlib.sha256(DETAIL).hexdigest()},
    )
    final = workspace / QUALITY / "CASO_A" / name
    publish_files(
        final, {"calidad.csv": DETAIL, "manifiesto.json": manifest.model_dump_json().encode()}
    )
    return final


def by_path(workspace: Path) -> dict[str, tuple[str, str]]:
    report = verify_workspace(workspace, clock=clock)
    return {item.path: (item.family, item.status) for item in report.items}


def test_an_empty_workspace_is_intact_and_has_nothing_to_report(workspace: Path) -> None:
    report = verify_workspace(workspace, clock=clock)
    assert (report.status, report.items) == ("intact", [])
    assert report.counts == {
        "intact": 0,
        "altered": 0,
        "incomplete": 0,
        "temporary": 0,
        "unknown": 0,
    }
    assert not workspace.exists()  # revisar no crea nada


def test_a_quality_report_is_checked(workspace: Path) -> None:
    folder = quality(workspace)
    assert by_path(workspace) == {f"{QUALITY}/CASO_A/Q1": ("quality", "intact")}
    (folder / "extra.txt").write_text("sobra", encoding="utf-8")
    report = verify_workspace(workspace, clock=clock)
    assert report.status == "altered"
    assert report.items[0].detail is not None and "HASH_MISMATCH" in report.items[0].detail


def test_temporary_and_set_aside_folders_are_reported_but_do_not_alter_the_status(
    workspace: Path,
) -> None:
    quality(workspace)
    group = workspace / QUALITY / "CASO_A"
    (group / ".tmp-Q2-abc123").mkdir()
    (group / ".incompletas" / "Q3-def456").mkdir(parents=True)
    (group / ".lock-Q1").write_bytes(b"")
    found = by_path(workspace)
    assert found[f"{QUALITY}/CASO_A/.tmp-Q2-abc123"] == ("quality", "temporary")
    assert found[f"{QUALITY}/CASO_A/.incompletas/Q3-def456"] == ("quality", "incomplete")
    assert f"{QUALITY}/CASO_A/.lock-Q1" not in found  # los candados no se informan
    assert verify_workspace(workspace, clock=clock).status == "intact"


def test_interrupted_runs_are_reported_as_incomplete(workspace: Path) -> None:
    spec = RunSpec(kind="simulation", case_id="C", case_version="1")
    runs = workspace / "ejecuciones"
    with pytest.raises(RuntimeError), RunWriter(runs, spec, run_id="20261101T220000Z_simulation_a"):
        raise RuntimeError("caída simulada")
    (temporary,) = [p for p in runs.iterdir() if p.name.startswith(".tmp-")]
    assert by_path(workspace) == {f"ejecuciones/{temporary.name}": ("runs", "temporary")}


def test_loose_files_and_unknown_names_are_reported_as_unknown(workspace: Path) -> None:
    (workspace / "ejecuciones").mkdir(parents=True)
    (workspace / "ejecuciones" / "notas.txt").write_text("suelto", encoding="utf-8")
    (workspace / "derivados" / "recepcion" / "pruebas-viejas").mkdir(parents=True)
    (workspace / "originales" / "sumo" / "R0-provisional").mkdir(parents=True)
    found = by_path(workspace)
    assert found == {
        "ejecuciones/notas.txt": ("runs", "unknown"),
        "derivados/recepcion/pruebas-viejas": ("receptions", "unknown"),
        "originales/sumo/R0-provisional": ("snapshots", "unknown"),
    }
    assert verify_workspace(workspace, clock=clock).status == "intact"


def test_a_folder_that_looks_like_a_run_but_is_not_published_is_altered(workspace: Path) -> None:
    (workspace / "ejecuciones" / "20261101T220000Z_simulation_falsa").mkdir(parents=True)
    report = verify_workspace(workspace, clock=clock)
    assert (report.status, report.items[0].status) == ("altered", "altered")


def test_a_copy_of_the_originals_with_another_content_is_altered(workspace: Path) -> None:
    folder = workspace / "originales" / "sumo" / ("0" * 64)
    folder.mkdir(parents=True)
    (folder / "a.xml").write_text("<a/>", encoding="utf-8")
    empty = workspace / "originales" / "sumo" / ("1" * 64)
    empty.mkdir()
    report = verify_workspace(workspace, clock=clock)
    details = {item.path.rsplit("/", 1)[-1][:1]: item.detail for item in report.items}
    assert report.status == "altered"
    assert details["0"] == "el contenido no corresponde a su identificador"
    assert details["1"] == "la copia está vacía"
