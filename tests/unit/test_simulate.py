"""El informe de una corrida y sus códigos de salida, sin ejecutar SUMO (DEV07 F4, D12)."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from semaforo.app import simulate
from semaforo.app.simulate import CANCELLED_EXIT, RunReport, exit_code_of, run_prepared
from semaforo.simulacion.runner import RunLimits, SimulationResult
from semaforo.simulacion.summary import RunTiming
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.interrupted import INCOMPLETE_DIR
from semaforo.trazabilidad.manifest import Error as RunError
from semaforo.trazabilidad.manifest import RunManifest, TerminalStatus
from semaforo.trazabilidad.store import RunSpec, RunWriter

NOW = datetime(2026, 11, 1, 15, 0, 0, tzinfo=UTC)
SPEC = RunSpec(kind="simulation", case_id="CASO_A", case_version="2.0.0", scenario_id="ESC_1")
TIMING = RunTiming(
    started_at=NOW,
    finished_at=NOW,
    duration_s=7.5,
    wall_timeout_s=900,
    end_s=2100,
    termination="completed",
    peak_memory_bytes=35_000_000,
    output_bytes=800_000,
)


def clock() -> datetime:
    return NOW


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    yield root
    remove_tree(root)


def publish(
    workspace: Path,
    status: TerminalStatus,
    code: str | None = None,
    *,
    extra: dict[str, str] | None = None,
) -> RunManifest:
    # como el corredor: una cancelada no lleva error
    error = (
        RunError(code=code or "SIM_FAILED", field=None, message="falló")
        if status == "failed"
        else None
    )
    with RunWriter(workspace / "ejecuciones", SPEC, clock=clock) as writer:
        writer.output_path("tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")
        for name, text in (extra or {}).items():
            writer.output_path(name).write_text(text, encoding="utf-8")
        return writer.publish(
            status=status,
            command=[],
            environment={},
            exit_code=0 if status == "succeeded" else 1,
            error=error,
        )


def result_of(manifest: RunManifest) -> SimulationResult:
    return SimulationResult(manifest=manifest, summary=None)


# --- códigos de salida ------------------------------------------------------------------------


def test_a_succeeded_run_exits_with_zero(workspace: Path) -> None:
    assert exit_code_of(result_of(publish(workspace, "succeeded"))) == 0


def test_a_cancelled_run_exits_with_four(workspace: Path) -> None:
    assert CANCELLED_EXIT == 4
    assert exit_code_of(result_of(publish(workspace, "cancelled"))) == 4


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("SIM_FAILED", 4),
        ("SIM_TIMEOUT", 4),
        ("OUTPUT_INVALID", 4),
        ("HASH_MISMATCH", 5),
        ("PATH_NOT_ALLOWED", 5),
        ("CODIGO_DESCONOCIDO", 1),
    ],
)
def test_a_failed_run_exits_with_the_code_of_its_error(
    workspace: Path, code: str, expected: int
) -> None:
    assert exit_code_of(result_of(publish(workspace, "failed", code))) == expected


def test_a_failed_run_without_an_error_is_an_internal_error(workspace: Path) -> None:
    manifest = publish(workspace, "failed").model_copy(update={"error": None})
    assert exit_code_of(result_of(manifest)) == 1


# --- el informe -------------------------------------------------------------------------------


class Fake:
    """Reemplaza a ``run_inputs``: anota con qué se lo llamó y devuelve una corrida publicada."""

    def __init__(
        self,
        workspace: Path,
        status: TerminalStatus = "succeeded",
        *,
        files: dict[str, str] | None = None,
    ) -> None:
        self.workspace = workspace
        self.status: TerminalStatus = status
        self.files = files or {}
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> SimulationResult:  # noqa: ANN401
        self.calls.append((args, kwargs))
        return result_of(publish(self.workspace, self.status, extra=self.files))


def install(monkeypatch: pytest.MonkeyPatch, fake: Fake) -> Fake:
    monkeypatch.setattr(simulate, "run_inputs", fake)
    return fake


def test_the_report_describes_the_published_run(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install(monkeypatch, Fake(workspace, "failed"))
    report = run_prepared(Path("entradas"), workspace, clock=clock)
    (args, _) = fake.calls[0]
    assert args == (Path("entradas"), workspace / "ejecuciones")
    assert report.status == "failed"
    assert report.path == f"ejecuciones/{report.run_id}"
    assert (report.error_code, report.error_message) == ("SIM_FAILED", "falló")
    assert report.scenario_id == "ESC_1"
    assert report.retry_of is None
    assert report.summary is None
    assert report.exit_code == 4
    assert (workspace / report.path / "manifest.json").is_file()


def test_a_succeeded_report_has_no_error(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, Fake(workspace))
    report = run_prepared(Path("entradas"), workspace, clock=clock)
    assert (report.status, report.error_code, report.error_message, report.exit_code) == (
        "succeeded",
        None,
        None,
        0,
    )


def test_the_timing_and_conciliation_are_read_from_the_run(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = (
        '{"scenario_id": "ESC_1", "vehicles_total": 10, "requested": 8, "finished": 6,'
        ' "unfinished": 1, "not_inserted": 1, "counts": []}'
    )
    install(
        monkeypatch,
        Fake(
            workspace,
            files={"tiempos.json": TIMING.model_dump_json(), "conciliacion.json": summary},
        ),
    )
    report = run_prepared(Path("entradas"), workspace, clock=clock)
    assert report.timing == TIMING
    assert report.conciliation is not None
    assert (report.conciliation.vehicles_total, report.conciliation.finished) == (10, 6)


def test_missing_or_damaged_side_files_do_not_break_the_report(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(
        monkeypatch, Fake(workspace, files={"tiempos.json": "{roto", "conciliacion.json": "{roto"})
    )
    report = run_prepared(Path("entradas"), workspace, clock=clock)
    assert (report.timing, report.conciliation) == (None, None)
    install(monkeypatch, Fake(workspace))
    report = run_prepared(Path("entradas"), workspace, clock=clock)
    assert (report.timing, report.conciliation) == (None, None)


def test_a_side_file_that_is_too_big_is_ignored(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    padded = TIMING.model_dump_json() + " " * (1024 * 1024 + 1)
    install(monkeypatch, Fake(workspace, files={"tiempos.json": padded}))
    assert run_prepared(Path("entradas"), workspace, clock=clock).timing is None


# --- con qué se ejecuta -----------------------------------------------------------------------


def test_the_limits_sumo_retry_and_cancel_reach_the_run(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install(monkeypatch, Fake(workspace))
    cancel = threading.Event()
    run_prepared(
        Path("entradas"),
        workspace,
        sumo=Path("sumo.exe"),
        wall_timeout_s=12.5,
        retry_of="20261101T100000Z_simulation_anterior",
        cancel=cancel,
        clock=clock,
    )
    ((_, options),) = fake.calls
    assert options["limits"].wall_timeout_s == 12.5
    assert options["limits"].max_output_bytes == RunLimits().max_output_bytes
    assert options["sumo"] == Path("sumo.exe")
    assert options["retry_of"] == "20261101T100000Z_simulation_anterior"
    assert options["cancel"] is cancel
    assert options["clock"] is clock


def test_without_options_the_defaults_are_used(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install(monkeypatch, Fake(workspace))
    run_prepared(Path("entradas"), workspace, clock=clock)
    ((_, options),) = fake.calls
    assert options["limits"] == RunLimits()
    assert (options["sumo"], options["retry_of"], options["cancel"]) == (None, None, None)


def test_interrupted_runs_are_set_aside_and_reported_before_running(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caida = "20261101T100000Z_simulation_caida000"
    with (
        pytest.raises(RuntimeError),
        RunWriter(workspace / "ejecuciones", SPEC, run_id=caida, clock=clock),
    ):
        raise RuntimeError("caída simulada")
    install(monkeypatch, Fake(workspace))
    report = run_prepared(Path("entradas"), workspace, clock=clock)
    assert report.recovered_interrupted == [f"{INCOMPLETE_DIR}/{caida}"]
    assert (workspace / "ejecuciones" / INCOMPLETE_DIR / caida / "manifest.json").is_file()


def test_with_nothing_to_recover_the_list_is_empty(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, Fake(workspace))
    assert run_prepared(Path("entradas"), workspace, clock=clock).recovered_interrupted == []


def test_the_report_is_a_closed_model(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, Fake(workspace))
    report = run_prepared(Path("entradas"), workspace, clock=clock)
    assert RunReport.model_validate_json(report.model_dump_json()) == report
