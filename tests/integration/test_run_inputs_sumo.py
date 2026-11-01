"""Ejecución de una carpeta de entradas con SUMO real (DEV07 F1; decisiones D1 a D3 y D10)."""

import csv
import io
import json
import shutil
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion import run_inputs as run_inputs_module
from semaforo.simulacion.prepare import CONFIG_FILE, InputsManifest, publish_inputs
from semaforo.simulacion.reconcile import ReconciliationError, reconcile, reconcile_run
from semaforo.simulacion.reconcile import reconciliation_csv as table_of
from semaforo.simulacion.run_inputs import (
    CONCILIATION_SUMMARY,
    CONCILIATION_TABLE,
    ConciliationSummary,
    run_inputs,
)
from semaforo.simulacion.runner import (
    RunLimits,
    SimulacionError,
    SimulationResult,
    run_simulation,
)
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.store import RunSpec, read_run

pytestmark = pytest.mark.sumo

COHORT = 150
TOTAL = 160


def clock() -> datetime:
    return datetime(2026, 10, 31, 20, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


@pytest.fixture
def folder(tmp_path: Path) -> Iterator[Path]:
    yield publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    remove_tree(tmp_path / "entradas")


def outputs(runs: Path, result: SimulationResult) -> Path:
    return runs / result.manifest.run_id / "outputs"


def conciliation_of(runs: Path, result: SimulationResult) -> ConciliationSummary:
    path = outputs(runs, result) / CONCILIATION_SUMMARY
    return ConciliationSummary.model_validate_json(path.read_bytes())


# --- la corrida -----------------------------------------------------------------------------


def test_a_prepared_folder_runs_and_publishes_its_conciliation(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_inputs(folder, runs, sumo=sumo_binary, clock=clock)
    assert (result.manifest.status, result.manifest.exit_code) == ("succeeded", 0)
    published = {artifact.path for artifact in result.manifest.outputs}
    assert {f"outputs/{CONCILIATION_TABLE}", f"outputs/{CONCILIATION_SUMMARY}"} <= published
    assert read_run(runs, result.manifest.run_id) == result.manifest
    summary = conciliation_of(runs, result)
    assert (summary.requested, summary.vehicles_total) == (COHORT, TOTAL)
    assert summary.finished + summary.unfinished + summary.not_inserted == COHORT
    assert summary.scenario_id == "SCENARIO_DEMO_001"


def test_the_run_takes_end_seed_and_scenario_from_the_manifest(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    manifest = InputsManifest.model_validate_json((folder / "manifiesto.json").read_bytes())
    result = run_inputs(folder, runs, limits=RunLimits(end_s=5), sumo=sumo_binary, clock=clock)
    assert result.summary is not None
    assert result.summary.end_limit_s == manifest.times.end_s == 1860
    assert result.summary.declared_vehicles == TOTAL
    run = result.manifest
    assert (run.case_id, run.case_version, run.scenario_id, run.seed) == (
        manifest.case_id,
        manifest.case_version,
        manifest.scenario_id,
        manifest.seeds.sumo_seed,
    )
    assert run.command[run.command.index("--end") + 1] == "1860"


def test_the_published_table_is_the_conciliation_of_the_run(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    result = run_inputs(folder, runs, sumo=sumo_binary, clock=clock)
    published = (outputs(runs, result) / CONCILIATION_TABLE).read_bytes()
    assert published == table_of(reconcile(folder, outputs(runs, result) / "tripinfo.xml"))
    assert published == table_of(reconcile_run(folder, runs, result.manifest.run_id))
    rows = list(csv.reader(io.StringIO(published.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == TOTAL + 1


def test_the_counts_add_up_by_movement_and_class(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    summary = conciliation_of(runs, run_inputs(folder, runs, sumo=sumo_binary, clock=clock))
    for count in summary.counts:
        assert count.requested == count.finished + count.unfinished + count.not_inserted
    assert sum(count.requested for count in summary.counts) == COHORT


def test_unfinished_vehicles_are_counted_without_failing_the_run(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    def no_drain(data: dict[str, Any]) -> None:
        data["drain_max_s"] = 1

    short = publish_inputs(
        tmp_path / "corta", request_for(tmp_path, scenario_change=no_drain), MOMENT
    )
    result = run_inputs(short, runs, sumo=sumo_binary, clock=clock)
    assert result.manifest.status == "succeeded"
    summary = conciliation_of(runs, result)
    assert summary.unfinished > 0
    assert summary.finished + summary.unfinished + summary.not_inserted == COHORT
    remove_tree(tmp_path / "corta")


def test_the_inputs_stay_intact(folder: Path, runs: Path, sumo_binary: Path) -> None:
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    run_inputs(folder, runs, sumo=sumo_binary, clock=clock)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


# --- antes de ejecutar ----------------------------------------------------------------------


def test_an_altered_folder_is_not_run(
    folder: Path, runs: Path, tmp_path: Path, sumo_binary: Path
) -> None:
    copy = tmp_path / "alterada"
    shutil.copytree(folder, copy)
    (copy / CONFIG_FILE).chmod(0o666)
    with (copy / CONFIG_FILE).open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(SimulacionError) as error:
        run_inputs(copy, runs, sumo=sumo_binary, clock=clock)
    assert error.value.code is ErrorCode.HASH_MISMATCH
    assert not runs.exists() or not any(runs.iterdir())
    remove_tree(copy)


# --- el paso previo a publicar ---------------------------------------------------------------


def test_a_failed_conciliation_leaves_the_run_failed_without_metrics(
    folder: Path, runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise ReconciliationError(ErrorCode.OUTPUT_INVALID, "viaje desconocido", "tripinfo.xml")

    monkeypatch.setattr(run_inputs_module, "reconcile", broken)
    result = run_inputs(folder, runs, sumo=sumo_binary, clock=clock)
    assert result.manifest.status == "failed"
    assert result.summary is None
    assert result.manifest.error is not None
    assert result.manifest.error.code == ErrorCode.OUTPUT_INVALID.value
    assert "viaje desconocido" in result.manifest.error.message
    names = {artifact.path for artifact in result.manifest.outputs}
    assert "outputs/summary.json" not in names
    assert f"outputs/{CONCILIATION_TABLE}" not in names
    assert read_run(runs, result.manifest.run_id) == result.manifest


def test_a_copy_that_differs_from_the_checked_folder_fails_the_run(
    folder: Path, runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = run_inputs_module.verify_inputs
    calls: list[Path] = []

    def second_differs(path: Path) -> InputsManifest:
        calls.append(path)
        manifest = real(path)
        if len(calls) == 1:
            return manifest
        return manifest.model_copy(update={"scenario_id": "OTRO"})

    monkeypatch.setattr(run_inputs_module, "verify_inputs", second_differs)
    result = run_inputs(folder, runs, sumo=sumo_binary, clock=clock)
    assert result.manifest.status == "failed"
    assert result.manifest.error is not None
    assert "no es la que se comprobó" in result.manifest.error.message
    assert calls[1].name == "inputs"


def run_with(
    folder: Path, runs: Path, sumo: Path, finalize: Mapping[str, bytes] | Exception
) -> SimulationResult:
    seen: list[Path] = []

    def step(run_folder: Path) -> Mapping[str, bytes]:
        seen.append(run_folder)
        assert (run_folder / "inputs" / CONFIG_FILE).is_file()
        assert (run_folder / "outputs" / "tripinfo.xml").is_file()
        if isinstance(finalize, Exception):
            raise finalize
        return finalize

    spec = RunSpec(kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", seed=100)
    result = run_simulation(
        folder,
        CONFIG_FILE,
        runs,
        spec,
        limits=RunLimits(end_s=1860),
        sumo=sumo,
        clock=clock,
        finalize=step,
    )
    assert len(seen) == 1
    return result


def test_the_final_step_can_add_outputs(folder: Path, runs: Path, sumo_binary: Path) -> None:
    result = run_with(folder, runs, sumo_binary, {"extra/nota.txt": b"hola"})
    assert result.manifest.status == "succeeded"
    assert (outputs(runs, result) / "extra" / "nota.txt").read_bytes() == b"hola"
    assert "outputs/extra/nota.txt" in {a.path for a in result.manifest.outputs}


@pytest.mark.parametrize("name", ["tripinfo.xml", "summary.json", "statistics.xml"])
def test_the_final_step_cannot_replace_an_output(
    folder: Path, runs: Path, sumo_binary: Path, name: str
) -> None:
    result = run_with(folder, runs, sumo_binary, {name: b"falso"})
    assert result.manifest.status == "failed"
    assert result.manifest.error is not None
    assert f"reemplazar la salida {name}" in result.manifest.error.message
    path = outputs(runs, result) / name
    assert not path.exists() or path.read_bytes() != b"falso"


def test_an_error_in_the_final_step_fails_the_run(
    folder: Path, runs: Path, sumo_binary: Path
) -> None:
    problem = SimulacionError(ErrorCode.HASH_MISMATCH, "algo no cuadra", None)
    result = run_with(folder, runs, sumo_binary, problem)
    assert result.manifest.status == "failed"
    assert result.manifest.error is not None
    assert (result.manifest.error.code, result.manifest.error.message) == (
        ErrorCode.OUTPUT_INVALID.value,
        "algo no cuadra",
    )
    assert result.summary is None


def test_the_conciliation_file_is_plain_json(folder: Path, runs: Path, sumo_binary: Path) -> None:
    result = run_inputs(folder, runs, sumo=sumo_binary, clock=clock)
    data = json.loads((outputs(runs, result) / CONCILIATION_SUMMARY).read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0.0"
    assert set(data) == {
        "schema_version",
        "scenario_id",
        "vehicles_total",
        "requested",
        "finished",
        "unfinished",
        "not_inserted",
        "counts",
    }
