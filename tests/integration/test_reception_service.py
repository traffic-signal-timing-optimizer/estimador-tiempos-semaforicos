"""Pruebas del servicio de recepción completo con SUMO real (F7 de DEV00)."""

import json
import os
import shutil
import stat
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.app.comparison import compare_receptions
from semaforo.app.reception import (
    ReceptionRecord,
    publish_public_report,
    read_reception,
    receive_case,
)
from semaforo.app.reception_report import find_machine_paths
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import RunSpec, RunWriter, read_run

pytestmark = pytest.mark.sumo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sumo"
DEMO = FIXTURES / "demo"
RECEPTIONS = Path("derivados") / "recepcion"


class Clock:
    """Reloj de prueba: cada llamada avanza un segundo."""

    def __init__(self) -> None:
        self.second = 0

    def __call__(self) -> datetime:
        self.second += 1
        return datetime(2026, 10, 20, 19, 0, self.second, tzinfo=UTC)


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    yield root
    remove_tree(root)


def receive(
    workspace: Path,
    sumo_binary: Path,
    source: Path = DEMO,
    clock: Callable[[], datetime] | None = None,
) -> ReceptionRecord:
    return receive_case(
        source,
        "demo.sumocfg",
        workspace,
        case_id="SYNTHETIC_DEMO",
        sumo=sumo_binary,
        clock=clock or Clock(),
    )


def test_a_reception_produces_every_artifact(workspace: Path, sumo_binary: Path) -> None:
    record = receive(workspace, sumo_binary)
    folder = workspace / RECEPTIONS / record.reception_id
    assert record.reception_id == f"20261020T190001Z_{record.snapshot_id[:8]}"
    assert sorted(p.name for p in folder.iterdir()) == [
        "audit.json",
        "hallazgos.md",
        "informe_publico.md",
        "inventory.json",
        "movements.json",
        "reception.json",
        "revision_qa23.csv",
        "revision_qa24.csv",
        "snapshot_manifest.json",
    ]
    for artifact in record.artifacts:
        assert sha256_file(folder / artifact.path) == artifact.sha256
    assert (workspace / record.snapshot_path).is_dir()
    assert record.snapshot_reused is False
    assert record.sumo_version == "1.27.1"
    assert (
        ReceptionRecord.model_validate_json((folder / "reception.json").read_text("utf-8"))
        == record
    )


def test_the_base_run_is_linked_by_the_hash_of_its_manifest(
    workspace: Path, sumo_binary: Path
) -> None:
    record = receive(workspace, sumo_binary)
    run = record.base_run
    manifest = read_run(workspace / "ejecuciones", run.run_id)
    assert manifest.status == run.status == "succeeded"
    assert sha256_file(workspace / run.path / "manifest.json") == run.manifest_sha256
    assert manifest.case_version == record.snapshot_id
    assert manifest.seed == 301
    assert run.summary is not None
    assert run.summary.vehicles_inserted == 150
    assert run.summary.declared_vehicles == 150


def test_the_proposed_status_reflects_the_findings(workspace: Path, sumo_binary: Path) -> None:
    record = receive(workspace, sumo_binary)
    # La auditoría del fixture avisa que su .sumocfg no fija end (NO_END_TIME).
    assert record.finding_counts == {"inventory": 0, "audit": 1, "run": 0}
    assert record.proposed_status == "with_findings"
    assert record.exit_code == 0


def variant(tmp_path: Path, old: str, new: str, file: str = "demo.sumocfg") -> Path:
    """Copia del fixture con un reemplazo de texto en uno de sus archivos."""
    case = tmp_path / "caso"
    shutil.copytree(DEMO, case)
    path = case / file
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return case


def test_a_reception_without_findings_is_acceptable(
    workspace: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    case = variant(tmp_path, '<begin value="0"/>', '<begin value="0"/><end value="3600"/>')
    record = receive(workspace, sumo_binary, source=case)
    assert record.finding_counts == {"inventory": 0, "audit": 0, "run": 0}
    assert record.proposed_status == "acceptable"


def test_inventory_findings_are_counted(workspace: Path, sumo_binary: Path, tmp_path: Path) -> None:
    case = variant(tmp_path, 'duration="30', 'minDur="40" duration="30', file="demo.net.xml")
    record = receive(workspace, sumo_binary, source=case)
    assert record.finding_counts["inventory"] == 1
    assert record.proposed_status == "with_findings"


def test_receiving_again_reuses_the_snapshot_and_creates_a_new_reception(
    workspace: Path, sumo_binary: Path
) -> None:
    clock = Clock()
    first = receive(workspace, sumo_binary, clock=clock)
    second = receive(workspace, sumo_binary, clock=clock)
    assert second.snapshot_id == first.snapshot_id
    assert second.snapshot_reused is True
    assert second.reception_id != first.reception_id
    assert second.base_run.run_id != first.base_run.run_id


def test_a_reception_is_never_overwritten(workspace: Path, sumo_binary: Path) -> None:
    def fixed() -> datetime:
        return datetime(2026, 10, 20, 19, 0, 0, tzinfo=UTC)

    first = receive(workspace, sumo_binary, clock=fixed)
    folder = workspace / RECEPTIONS / first.reception_id
    before = {p.name: sha256_file(p) for p in folder.iterdir()}
    with pytest.raises(DomainError) as raised:
        receive(workspace, sumo_binary, clock=fixed)
    assert raised.value.code is ErrorCode.RUN_EXISTS
    assert {p.name: sha256_file(p) for p in folder.iterdir()} == before
    # Se detecta antes de correr SUMO: no queda una corrida inútil.
    assert [p.name for p in (workspace / "ejecuciones").iterdir()] == [first.base_run.run_id]


def test_a_failed_base_run_is_recorded(workspace: Path, sumo_binary: Path) -> None:
    record = receive(workspace, sumo_binary, source=FIXTURES / "invalid" / "missing_edge")
    assert record.proposed_status == "failed"
    assert record.base_run.status == "failed"
    assert record.base_run.error_code == "SIM_FAILED"
    assert record.base_run.summary is None
    assert record.exit_code == 4
    assert (workspace / RECEPTIONS / record.reception_id / "reception.json").is_file()


def test_incomplete_runs_left_by_a_crash_are_listed(workspace: Path, sumo_binary: Path) -> None:
    spec = RunSpec(kind="simulation", case_id="X", case_version="1")
    with (
        pytest.raises(RuntimeError),
        RunWriter(workspace / "ejecuciones", spec, run_id="20261020T180000Z_simulation_caida000"),
    ):
        raise RuntimeError("caída simulada")
    record = receive(workspace, sumo_binary)
    (incomplete,) = record.incomplete_runs
    assert incomplete.run_id == "20261020T180000Z_simulation_caida000"
    assert incomplete.folder.startswith(".tmp-")


def test_the_reception_files_are_read_only_and_have_no_machine_paths(
    workspace: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    record = receive(workspace, sumo_binary)
    folder = workspace / RECEPTIONS / record.reception_id
    for path in folder.iterdir():
        assert not path.stat().st_mode & stat.S_IWRITE
        assert str(tmp_path) not in path.read_text(encoding="utf-8")
    assert json.loads((folder / "reception.json").read_text("utf-8"))["source_name"] == "demo"


def test_the_public_report_is_published_after_verifying_the_reception(
    workspace: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    record = receive(workspace, sumo_binary)
    docs = tmp_path / "docs" / "recepcion"
    target = publish_public_report(workspace, record.reception_id, docs)
    assert target == docs / f"{record.reception_id}.md"
    text = target.read_text(encoding="utf-8")
    assert record.base_run.manifest_sha256 in text
    assert find_machine_paths(text) == []
    with pytest.raises(DomainError) as raised:
        publish_public_report(workspace, record.reception_id, docs)
    assert raised.value.code is ErrorCode.RUN_EXISTS


def test_a_tampered_reception_is_not_published(
    workspace: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    record = receive(workspace, sumo_binary)
    audit = workspace / RECEPTIONS / record.reception_id / "audit.json"
    os.chmod(audit, stat.S_IWRITE | stat.S_IREAD)
    audit.write_text("{}", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        publish_public_report(workspace, record.reception_id, tmp_path / "docs")
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert not (tmp_path / "docs").exists()


def test_a_tampered_base_run_is_not_published(
    workspace: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    record = receive(workspace, sumo_binary)
    tripinfo = workspace / record.base_run.path / "outputs" / "tripinfo.xml"
    os.chmod(tripinfo, stat.S_IWRITE | stat.S_IREAD)
    tripinfo.write_text("<tripinfos/>", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        publish_public_report(workspace, record.reception_id, tmp_path / "docs")
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert not (tmp_path / "docs").exists()


def test_a_rewritten_base_run_manifest_is_detected_by_its_fingerprint(
    workspace: Path, sumo_binary: Path
) -> None:
    """La corrida sigue siendo coherente consigo misma, pero no es la que registró la recepción."""
    record = receive(workspace, sumo_binary)
    path = workspace / record.base_run.path / "manifest.json"
    manifest = read_run(workspace / "ejecuciones", record.base_run.run_id)
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    read_run(workspace / "ejecuciones", record.base_run.run_id)  # la corrida por sí sola pasa
    with pytest.raises(DomainError) as raised:
        read_reception(workspace, record.reception_id)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_an_extra_file_in_the_reception_is_named(workspace: Path, sumo_binary: Path) -> None:
    # Una planilla completada guardada dentro de la recepción la invalida: el error dice cuál.
    record = receive(workspace, sumo_binary)
    folder = workspace / "derivados" / "recepcion" / record.reception_id
    (folder / "revision_qa23_revisada.csv").write_text("x", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        read_reception(workspace, record.reception_id)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert "sobra revision_qa23_revisada.csv" in raised.value.message
    assert f"revisiones/{record.reception_id}" in raised.value.message


def test_a_missing_artifact_is_named(workspace: Path, sumo_binary: Path) -> None:
    record = receive(workspace, sumo_binary)
    path = workspace / "derivados" / "recepcion" / record.reception_id / "hallazgos.md"
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.unlink()
    with pytest.raises(DomainError) as raised:
        read_reception(workspace, record.reception_id)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert "falta hallazgos.md" in raised.value.message


def test_a_reception_without_its_base_run_is_rejected(workspace: Path, sumo_binary: Path) -> None:
    record = receive(workspace, sumo_binary)
    remove_tree(workspace / record.base_run.path)
    with pytest.raises(DomainError) as raised:
        read_reception(workspace, record.reception_id)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_a_report_with_machine_paths_is_not_published(
    workspace: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    """Simula un informe contaminado: se rehace también su huella para que pase la verificación."""
    record = receive(workspace, sumo_binary)
    folder = workspace / RECEPTIONS / record.reception_id
    for path in folder.iterdir():
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    report = folder / "informe_publico.md"
    report.write_text(report.read_text("utf-8") + "\nC:\\Users\\alguien\\x\n", encoding="utf-8")
    artifacts = [
        a.model_copy(update={"sha256": sha256_file(report)}) if a.path == report.name else a
        for a in record.artifacts
    ]
    (folder / "reception.json").write_text(
        record.model_copy(update={"artifacts": artifacts}).model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(DomainError) as raised:
        publish_public_report(workspace, record.reception_id, tmp_path / "docs")
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.parametrize("reception_id", ["../x", "20261020T190001Z_ZZZ", ""])
def test_unsafe_reception_ids_are_rejected(workspace: Path, reception_id: str) -> None:
    with pytest.raises(DomainError) as raised:
        read_reception(workspace, reception_id)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


def test_two_receptions_of_the_same_simulation_have_no_changes(
    workspace: Path, sumo_binary: Path
) -> None:
    clock = Clock()
    first = receive(workspace, sumo_binary, clock=clock)
    second = receive(workspace, sumo_binary, clock=clock)
    comparison = compare_receptions(workspace, first.reception_id, second.reception_id)
    assert comparison.same_snapshot is True
    assert comparison.changes == []


def test_the_comparison_shows_what_changed(
    workspace: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    clock = Clock()
    first = receive(workspace, sumo_binary, clock=clock)
    case = variant(tmp_path, 'number="90"', 'number="60"', file="demo.rou.xml")
    second = receive(workspace, sumo_binary, source=case, clock=clock)
    comparison = compare_receptions(workspace, first.reception_id, second.reception_id)
    assert comparison.same_snapshot is False
    items = {(c.area, c.item) for c in comparison.changes}
    assert ("snapshot", "demo.rou.xml") in items
    assert ("audit", "vehículos declarados") in items
    assert ("audit", "demanda N_S_car") in items
    assert ("run", "vehicles_loaded") in items
    assert not any(area == "inventory" for area, _ in items)
    loaded = next(c for c in comparison.changes if c.item == "vehicles_loaded")
    assert (loaded.before, loaded.after) == ("150", "120")


def test_errors_before_running_are_raised_without_a_reception(
    workspace: Path, sumo_binary: Path
) -> None:
    with pytest.raises(DomainError) as raised:
        receive(workspace, sumo_binary, source=FIXTURES / "invalid" / "absolute_output")
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (workspace / RECEPTIONS).exists() or list((workspace / RECEPTIONS).iterdir()) == []
