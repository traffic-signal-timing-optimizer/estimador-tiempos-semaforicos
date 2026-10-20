"""Pruebas del servicio de recepción completo con SUMO real (F7 de DEV00)."""

import json
import shutil
import stat
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.app.reception import ReceptionRecord, receive_case
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
        "inventory.json",
        "reception.json",
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


def test_errors_before_running_are_raised_without_a_reception(
    workspace: Path, sumo_binary: Path
) -> None:
    with pytest.raises(DomainError) as raised:
        receive(workspace, sumo_binary, source=FIXTURES / "invalid" / "absolute_output")
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (workspace / RECEPTIONS).exists() or list((workspace / RECEPTIONS).iterdir()) == []
