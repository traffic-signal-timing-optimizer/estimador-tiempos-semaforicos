"""Pruebas del runner con SUMO real sobre el fixture (QA07, QA08, QA09 parcial y QA10)."""

import json
import re
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.runner import (
    RunLimits,
    SimulacionError,
    SimulationResult,
    run_simulation,
)
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.store import RunSpec, read_run

pytestmark = pytest.mark.sumo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sumo"
DEMO = FIXTURES / "demo"
INVALID = FIXTURES / "invalid"
SPEC = RunSpec(kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", seed=301)


def clock() -> datetime:
    return datetime(2026, 10, 20, 18, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


def outputs_of(result: SimulationResult) -> set[str]:
    return {artifact.path for artifact in result.manifest.outputs}


def without_header(path: Path) -> str:
    """Contenido sin el comentario inicial, que lleva la configuración y rutas del equipo."""
    return re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), count=1, flags=re.S)


def fingerprint(folder: Path) -> dict[str, str]:
    return {p.name: sha256_file(p) for p in folder.iterdir() if p.is_file()}


def test_a_base_run_of_the_fixture_succeeds(runs: Path, sumo_binary: Path) -> None:
    before = fingerprint(DEMO)
    result = run_simulation(
        DEMO, "demo.sumocfg", runs, SPEC, sumo=sumo_binary, declared_vehicles=150, clock=clock
    )
    manifest = result.manifest
    assert (manifest.status, manifest.exit_code, manifest.error) == ("succeeded", 0, None)
    assert {
        "outputs/tripinfo.xml",
        "outputs/statistics.xml",
        "outputs/summary.json",
        "outputs/sumo.log",
        "outputs/sumo.stdout.txt",
        "outputs/sumo.stderr.txt",
    } <= outputs_of(result)
    assert manifest.environment["sumo"] == "1.27.1"
    assert manifest.command[:5] == ["sumo", "-c", "inputs/demo.sumocfg", "--end", "7200"]
    summary = result.summary
    assert summary is not None
    assert (summary.vehicles_loaded, summary.vehicles_inserted, summary.trips_finished) == (
        150,
        150,
        150,
    )
    assert (summary.vehicles_running, summary.vehicles_waiting, summary.teleports_total) == (
        0,
        0,
        0,
    )
    assert summary.demand_unmet is False
    assert summary.mode == "base"
    assert read_run(runs, manifest.run_id) == manifest
    assert fingerprint(DEMO) == before
    stored = json.loads((runs / manifest.run_id / "outputs" / "summary.json").read_text("utf-8"))
    assert stored["vehicles_inserted"] == 150


def test_the_manifest_has_no_machine_paths(runs: Path, sumo_binary: Path, tmp_path: Path) -> None:
    result = run_simulation(DEMO, "demo.sumocfg", runs, SPEC, sumo=sumo_binary, clock=clock)
    text = result.manifest.model_dump_json()
    assert str(tmp_path) not in text
    assert str(sumo_binary) not in text


def test_a_smoke_run_stops_early_and_flags_the_unmet_demand(runs: Path, sumo_binary: Path) -> None:
    limits = RunLimits(smoke_end_s=60)
    result = run_simulation(
        DEMO,
        "demo.sumocfg",
        runs,
        SPEC,
        mode="smoke",
        limits=limits,
        sumo=sumo_binary,
        declared_vehicles=150,
        clock=clock,
    )
    assert result.manifest.status == "succeeded"
    assert result.manifest.command[3:5] == ["--end", "60"]
    summary = result.summary
    assert summary is not None
    assert summary.mode == "smoke"
    assert summary.demand_unmet is True
    assert "LOADED_BELOW_DECLARED" in [f.code for f in summary.findings]


def test_two_runs_with_the_same_seed_give_the_same_trips(runs: Path, sumo_binary: Path) -> None:
    first = run_simulation(DEMO, "demo.sumocfg", runs, SPEC, sumo=sumo_binary)
    second = run_simulation(DEMO, "demo.sumocfg", runs, SPEC, sumo=sumo_binary)
    assert first.manifest.run_id != second.manifest.run_id
    trips = [
        without_header(runs / r.manifest.run_id / "outputs" / "tripinfo.xml")
        for r in (first, second)
    ]
    assert trips[0] == trips[1]
    assert first.summary == second.summary


@pytest.mark.parametrize("variant", ["missing_edge", "truncated_net"])
def test_an_invalid_case_fails_with_a_reason_and_no_metrics(
    runs: Path, sumo_binary: Path, variant: str
) -> None:
    result = run_simulation(INVALID / variant, "demo.sumocfg", runs, SPEC, sumo=sumo_binary)
    manifest = result.manifest
    assert manifest.status == "failed"
    assert manifest.exit_code == 1
    assert manifest.error is not None
    assert manifest.error.code == "SIM_FAILED"
    assert result.summary is None
    assert "outputs/summary.json" not in outputs_of(result)
    assert "outputs/sumo.stderr.txt" in outputs_of(result)
    assert read_run(runs, manifest.run_id) == manifest


def test_a_run_over_the_wall_clock_limit_times_out(runs: Path, sumo_binary: Path) -> None:
    limits = RunLimits(wall_timeout_s=0.05)
    result = run_simulation(DEMO, "demo.sumocfg", runs, SPEC, limits=limits, sumo=sumo_binary)
    assert result.manifest.status == "failed"
    assert result.manifest.error is not None
    assert result.manifest.error.code == "SIM_TIMEOUT"
    assert result.summary is None


def test_incoherent_outputs_fail_without_metrics(
    runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def incoherent(*_args: object, **_kwargs: object) -> None:
        raise SimulacionError(ErrorCode.OUTPUT_INVALID, "hay 9 viajes y 10 vehículos", "tripinfo")

    monkeypatch.setattr("semaforo.simulacion.runner.summarize_outputs", incoherent)
    result = run_simulation(DEMO, "demo.sumocfg", runs, SPEC, sumo=sumo_binary)
    assert result.manifest.status == "failed"
    assert result.manifest.exit_code == 0
    assert result.manifest.error is not None
    assert result.manifest.error.code == "OUTPUT_INVALID"
    assert result.summary is None
    assert "outputs/summary.json" not in outputs_of(result)


def test_a_config_with_absolute_paths_is_not_run(runs: Path, sumo_binary: Path) -> None:
    with pytest.raises(DomainError) as raised:
        run_simulation(INVALID / "absolute_output", "demo.sumocfg", runs, SPEC, sumo=sumo_binary)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not runs.exists() or list(runs.iterdir()) == []


def test_outputs_declared_by_the_config_are_kept_as_outputs(
    runs: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    case = tmp_path / "case"
    shutil.copytree(DEMO, case)
    config = case / "demo.sumocfg"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "<output>", '<output>\n        <summary-output value="resumen.xml"/>'
        ),
        encoding="utf-8",
    )
    result = run_simulation(case, "demo.sumocfg", runs, SPEC, sumo=sumo_binary)
    assert result.manifest.status == "succeeded"
    assert "outputs/config/resumen.xml" in outputs_of(result)


def test_a_missing_gui_only_file_does_not_stop_a_headless_run(
    runs: Path, sumo_binary: Path, tmp_path: Path
) -> None:
    """La copia de F2 no incluye las vistas (ADR09), pero SUMO exige que existan."""
    case = tmp_path / "case"
    shutil.copytree(DEMO, case)
    config = case / "demo.sumocfg"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "</configuration>",
            '<gui_only><gui-settings-file value="vista.xml"/></gui_only></configuration>',
        ),
        encoding="utf-8",
    )
    result = run_simulation(case, "demo.sumocfg", runs, SPEC, sumo=sumo_binary)
    assert result.manifest.status == "succeeded"
    command = result.manifest.command
    assert command[command.index("--gui-settings-file") + 1] == ""


def test_a_run_folder_too_deep_for_sumo_fails_before_running(runs: Path, sumo_binary: Path) -> None:
    result = run_simulation(
        DEMO, "demo.sumocfg", runs, SPEC, limits=RunLimits(max_path_chars=50), sumo=sumo_binary
    )
    assert result.manifest.status == "failed"
    assert result.manifest.error is not None
    assert result.manifest.error.code == "PATH_NOT_ALLOWED"
    assert result.manifest.exit_code is None
    assert "outputs/sumo.stdout.txt" not in outputs_of(result)


def test_a_missing_entry_config_is_rejected_before_running(runs: Path, sumo_binary: Path) -> None:
    with pytest.raises(DomainError) as raised:
        run_simulation(DEMO, "no-existe.sumocfg", runs, SPEC, sumo=sumo_binary)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
