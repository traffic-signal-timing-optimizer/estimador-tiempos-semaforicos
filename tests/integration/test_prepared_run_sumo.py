"""Una carpeta de entradas de DEV06 ejecutada con SUMO real (QA07, QA10 y QA25, DEV06 F3)."""

import json
import shutil
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.prepare import MANIFEST_FILE, publish_inputs
from semaforo.simulacion.reconcile import (
    Reconciliation,
    ReconciliationError,
    reconcile,
    reconcile_run,
)
from semaforo.simulacion.runner import RunLimits, SimulationResult, run_simulation
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import RunSpec, read_run

pytestmark = pytest.mark.sumo

TOTAL = 160
COHORT = 150


def clock() -> datetime:
    return datetime(2026, 10, 31, 18, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


@pytest.fixture
def folder(tmp_path: Path) -> Iterator[Path]:
    published = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    yield published
    remove_tree(tmp_path / "entradas")


def manifest_of(folder: Path) -> dict[str, Any]:
    return json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))


def fingerprint(folder: Path) -> dict[str, str]:
    return {p.name: sha256_file(p) for p in sorted(folder.iterdir()) if p.is_file()}


def run_prepared(
    folder: Path, runs: Path, sumo: Path, end_s: float | None = None
) -> SimulationResult:
    """Ejecuta la carpeta con el corredor, con el fin de simulación del manifiesto."""
    manifest = manifest_of(folder)
    spec = RunSpec(
        kind="simulation",
        case_id=manifest["case_id"],
        case_version=manifest["case_version"],
        scenario_id=manifest["scenario_id"],
        seed=manifest["seeds"]["sumo_seed"],
    )
    return run_simulation(
        folder,
        manifest["entry_config"],
        runs,
        spec,
        limits=RunLimits(end_s=end_s or manifest["times"]["end_s"]),
        sumo=sumo,
        declared_vehicles=manifest["vehicles"]["total"],
        clock=clock,
    )


def tripinfo_of(runs: Path, result: SimulationResult) -> Path:
    return runs / result.manifest.run_id / "outputs" / "tripinfo.xml"


def reconcile_trips(folder: Path, runs: Path, result: SimulationResult) -> Reconciliation:
    return reconcile(folder, tripinfo_of(runs, result))


# --- QA07: ejecutar y comprobar archivos y versiones -----------------------------------------


def test_a_prepared_folder_runs_and_the_run_is_complete(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    manifest = result.manifest
    assert (manifest.status, manifest.exit_code, manifest.error) == ("succeeded", 0, None)
    assert manifest.environment["sumo"] == "1.27.1"
    assert result.summary is not None
    assert result.summary.vehicles_loaded == TOTAL
    assert (result.summary.collisions, result.summary.teleports_total) == (0, 0)
    assert {a.path for a in manifest.outputs} >= {
        "outputs/tripinfo.xml",
        "outputs/statistics.xml",
        "outputs/summary.json",
        "outputs/sumo.log",
    }
    assert read_run(runs, manifest.run_id) == manifest


def test_the_simulation_runs_until_the_end_the_manifest_declares(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    assert result.summary is not None
    assert result.summary.end_limit_s == manifest_of(folder)["times"]["end_s"] == 1860.0


def test_the_run_records_the_hash_of_every_input(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    recorded = {a.path.removeprefix("inputs/"): a.sha256 for a in result.manifest.inputs}
    assert recorded == fingerprint(folder)
    declared = manifest_of(folder)["files"]
    assert {name: recorded[name] for name in declared} == declared


def test_the_original_inputs_stay_intact_and_read_only(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    before = fingerprint(folder)
    run_prepared(folder, runs, sumo_binary)
    assert fingerprint(folder) == before
    assert sorted(p.name for p in folder.iterdir()) == sorted(before)
    for path in folder.iterdir():
        assert not path.stat().st_mode & stat.S_IWRITE


def test_two_runs_of_the_same_inputs_give_the_same_trips(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    first = run_prepared(folder, runs, sumo_binary)
    second = run_prepared(folder, runs / "otra", sumo_binary)
    assert reconcile_trips(folder, runs, first) == reconcile_trips(folder, runs / "otra", second)


# --- QA25: la cohorte se concilia por identificador ------------------------------------------


def test_the_full_run_accounts_for_every_requested_vehicle(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    assert result.summary is not None
    reconciliation = reconcile_trips(folder, runs, result)
    assert reconciliation.requested == COHORT
    assert (
        reconciliation.finished + reconciliation.unfinished + reconciliation.not_inserted
        == reconciliation.requested
    )
    assert len(reconciliation.outcomes) == TOTAL


def test_the_reconciliation_agrees_with_the_totals_sumo_reports(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary, end_s=250)
    assert result.summary is not None
    outcomes = reconcile_trips(folder, runs, result).outcomes
    states = [o.status for o in outcomes]
    assert states.count("finished") == result.summary.trips_finished
    assert states.count("unfinished") == result.summary.trips_unfinished
    assert states.count("not_inserted") == TOTAL - result.summary.vehicles_inserted


def test_a_short_run_leaves_unfinished_and_not_inserted_vehicles_without_losing_any(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary, end_s=250)
    reconciliation = reconcile_trips(folder, runs, result)
    assert reconciliation.finished > 0
    assert reconciliation.unfinished > 0
    assert reconciliation.not_inserted > 0
    assert reconciliation.requested == COHORT
    assert (
        reconciliation.finished + reconciliation.unfinished + reconciliation.not_inserted == COHORT
    )
    for count in reconciliation.counts:
        assert count.requested == count.finished + count.unfinished + count.not_inserted
    assert sum(count.requested for count in reconciliation.counts) == COHORT


def test_a_vehicle_that_was_never_inserted_departs_after_the_end(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary, end_s=250)
    for outcome in reconcile_trips(folder, runs, result).outcomes:
        if outcome.status == "not_inserted":
            assert outcome.scheduled_s > 200
            assert outcome.inserted_s is None


# --- QA10: nombres con caracteres especiales no llegan a ningún intérprete -------------------


def test_names_with_shell_characters_are_run_as_plain_names(
    tmp_path: Path, sumo_binary: Path
) -> None:
    root = tmp_path / "raiz & (copia) ;x ^y 'z' $HOME %PATH%"
    published = publish_inputs(root / "entradas", request_for(tmp_path), MOMENT)
    runs = root / "ejecuciones & mkdir pwned & echo x"
    try:
        result = run_prepared(published, runs, sumo_binary)
        assert result.manifest.status == "succeeded"
        assert reconcile_trips(published, runs, result).requested == COHORT
    finally:
        remove_tree(root)
    assert not any(p.name == "pwned" for p in tmp_path.rglob("*"))
    assert not Path("pwned").exists()


# --- la conciliación parte de una corrida publicada ---------------------------------------


def test_reconcile_run_gives_the_same_table_as_the_tripinfo_of_that_run(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    assert reconcile_run(folder, runs, result.manifest.run_id) == reconcile_trips(
        folder, runs, result
    )


def test_a_failed_run_is_not_reconciled(folder: Path, runs: Path, sumo_binary: Path) -> None:
    manifest = manifest_of(folder)
    spec = RunSpec(
        kind="simulation",
        case_id=manifest["case_id"],
        case_version=manifest["case_version"],
        scenario_id=manifest["scenario_id"],
        seed=manifest["seeds"]["sumo_seed"],
    )
    failed = run_simulation(
        folder,
        manifest["entry_config"],
        runs,
        spec,
        limits=RunLimits(end_s=1860, wall_timeout_s=0.001),
        sumo=sumo_binary,
        clock=clock,
    )
    assert failed.manifest.status == "failed"
    with pytest.raises(ReconciliationError, match="failed") as error:
        reconcile_run(folder, runs, failed.manifest.run_id)
    assert error.value.code is ErrorCode.OUTPUT_INVALID


def test_a_run_made_with_other_inputs_is_not_reconciled(
    folder: Path, runs: Path, tmp_path: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)

    def other_seed(data: dict[str, Any]) -> None:
        data["demand_seed"] = 101

    other_dir = tmp_path / "x"
    other_dir.mkdir()

    other = publish_inputs(
        tmp_path / "otras", request_for(other_dir, scenario_change=other_seed), MOMENT
    )
    with pytest.raises(ReconciliationError, match="estas entradas") as error:
        reconcile_run(other, runs, result.manifest.run_id)
    assert error.value.code is ErrorCode.HASH_MISMATCH
    remove_tree(tmp_path / "otras")


def altered_copy(folder: Path, tmp_path: Path, name: str) -> Path:
    """Copia de las entradas, con un salto de línea agregado al final de ``name``."""
    copy = tmp_path / "alterada"
    shutil.copytree(folder, copy)
    target = copy / name
    target.chmod(0o666)
    with target.open("ab") as handle:
        handle.write(b"\n")
    return copy


@pytest.mark.parametrize("name", [MANIFEST_FILE, "escenario.sumocfg", "cohorte.csv"])
def test_inputs_changed_after_the_run_are_not_reconciled(
    folder: Path, runs: Path, tmp_path: Path, sumo_binary: Path, name: str
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    altered = altered_copy(folder, tmp_path, name)
    with pytest.raises(ReconciliationError, match="estas entradas") as error:
        reconcile_run(altered, runs, result.manifest.run_id)
    assert error.value.code is ErrorCode.HASH_MISMATCH
    remove_tree(altered)


def test_an_extra_file_in_the_inputs_is_not_reconciled(
    folder: Path, runs: Path, tmp_path: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    altered = altered_copy(folder, tmp_path, MANIFEST_FILE)
    (altered / MANIFEST_FILE).write_bytes((folder / MANIFEST_FILE).read_bytes())
    (altered / "sobra.txt").write_text("de más", encoding="utf-8")
    with pytest.raises(ReconciliationError, match="estas entradas") as error:
        reconcile_run(altered, runs, result.manifest.run_id)
    assert error.value.code is ErrorCode.HASH_MISMATCH
    remove_tree(altered)


def test_a_missing_file_in_the_inputs_is_not_reconciled(
    folder: Path, runs: Path, tmp_path: Path, sumo_binary: Path
) -> None:
    result = run_prepared(folder, runs, sumo_binary)
    altered = altered_copy(folder, tmp_path, MANIFEST_FILE)
    (altered / MANIFEST_FILE).write_bytes((folder / MANIFEST_FILE).read_bytes())
    (altered / "programa.tll.xml").chmod(0o666)
    (altered / "programa.tll.xml").unlink()
    with pytest.raises(ReconciliationError, match="estas entradas") as error:
        reconcile_run(altered, runs, result.manifest.run_id)
    assert error.value.code is ErrorCode.HASH_MISMATCH
    remove_tree(altered)
