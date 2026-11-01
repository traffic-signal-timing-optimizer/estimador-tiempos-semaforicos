"""SUMO real bajo control: tiempo, cancelación, topes y tiempos de la corrida (DEV07 F2).

Una corrida larga se obtiene con un fin de simulación enorme sobre la red de demostración: SUMO
sigue corriendo (más de 40 s) aunque ya no queden vehículos. Se comprueba además que, después de
cada forma de cortarlo, el proceso de SUMO ya no existe (riesgo D16 de F0).
"""

import ctypes
import os
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion import runner
from semaforo.simulacion.prepare import publish_inputs
from semaforo.simulacion.process import ProcessLimits, ProcessOutcome
from semaforo.simulacion.run_inputs import CONCILIATION_TABLE, run_inputs
from semaforo.simulacion.runner import (
    TIMING,
    RunLimits,
    SimulacionError,
    SimulationResult,
    run_simulation,
)
from semaforo.simulacion.summary import RunTiming
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.store import RunSpec, read_run

pytestmark = pytest.mark.sumo

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"
SPEC = RunSpec(kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", seed=301)
LONG = 20_000_000  # segundos simulados: SUMO tarda más de 40 s en llegar


def clock() -> datetime:
    return datetime(2026, 10, 31, 22, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


@pytest.fixture
def pids(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Los números de proceso de SUMO que lanza cada corrida de la prueba."""
    seen: list[int] = []
    real = runner.run_controlled

    def spy(*args: Any, **kwargs: Any) -> ProcessOutcome:  # noqa: ANN401 - envuelve la función real
        outcome = real(*args, **kwargs)
        seen.append(outcome.pid)
        return outcome

    monkeypatch.setattr(runner, "run_controlled", spy)
    return seen


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel32.OpenProcess(0x00100000, 0, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return bool(kernel32.WaitForSingleObject(handle, 0) == 0x102)  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def long_run(runs: Path, sumo: Path, **limits: Any) -> SimulationResult:  # noqa: ANN401
    cancel = limits.pop("cancel", None)
    return run_simulation(
        DEMO,
        "demo.sumocfg",
        runs,
        SPEC,
        limits=RunLimits(end_s=LONG, **limits),
        sumo=sumo,
        clock=clock,
        cancel=cancel,
    )


def timing_of(runs: Path, result: SimulationResult) -> RunTiming:
    path = runs / result.manifest.run_id / "outputs" / TIMING
    return RunTiming.model_validate_json(path.read_bytes())


def published(result: SimulationResult) -> set[str]:
    return {artifact.path for artifact in result.manifest.outputs}


# --- corrida normal: tiempos ----------------------------------------------------------------


def test_a_successful_run_publishes_its_timing(runs: Path, sumo_binary: Path) -> None:
    result = run_simulation(DEMO, "demo.sumocfg", runs, SPEC, sumo=sumo_binary, clock=clock)
    assert result.manifest.status == "succeeded"
    assert f"outputs/{TIMING}" in published(result)
    timing = timing_of(runs, result)
    assert timing.termination == "completed"
    assert 0 < timing.duration_s < 60
    assert timing.wall_timeout_s == 900
    assert timing.end_s == 7200
    assert timing.output_bytes > 0
    assert timing.peak_memory_bytes is not None
    assert 1 * 1024 * 1024 < timing.peak_memory_bytes < 500 * 1024 * 1024
    assert (timing.started_at, timing.finished_at) == (clock(), clock())


def test_the_timing_is_part_of_the_verified_run(runs: Path, sumo_binary: Path) -> None:
    result = run_simulation(DEMO, "demo.sumocfg", runs, SPEC, sumo=sumo_binary, clock=clock)
    assert read_run(runs, result.manifest.run_id) == result.manifest


# --- tiempo agotado -------------------------------------------------------------------------


def test_a_run_over_the_time_limit_is_failed_and_keeps_its_partial_outputs(
    runs: Path, sumo_binary: Path, pids: list[int]
) -> None:
    result = long_run(runs, sumo_binary, wall_timeout_s=2.0)
    manifest = result.manifest
    assert manifest.status == "failed"
    assert manifest.exit_code is None
    assert manifest.error is not None
    assert (manifest.error.code, manifest.error.message) == (
        ErrorCode.SIM_TIMEOUT.value,
        "SUMO superó el límite de 2 s de tiempo real",
    )
    assert result.summary is None
    assert "outputs/summary.json" not in published(result)
    assert {"outputs/sumo.stdout.txt", "outputs/sumo.stderr.txt", f"outputs/{TIMING}"} <= published(
        result
    )
    assert timing_of(runs, result).termination == "timeout"
    assert read_run(runs, manifest.run_id) == manifest
    assert not alive(pids[0])


# --- cancelación ----------------------------------------------------------------------------


def test_a_cancelled_run_is_published_cancelled_without_metrics(
    runs: Path, sumo_binary: Path, pids: list[int]
) -> None:
    cancel = threading.Event()
    threading.Timer(2.0, cancel.set).start()
    result = long_run(runs, sumo_binary, cancel=cancel)
    manifest = result.manifest
    assert (manifest.status, manifest.exit_code, manifest.error) == ("cancelled", None, None)
    assert result.summary is None
    assert "outputs/summary.json" not in published(result)
    assert f"outputs/{TIMING}" in published(result)
    assert "outputs/sumo.stderr.txt" in published(result)
    assert timing_of(runs, result).termination == "cancelled"
    assert 1.5 < timing_of(runs, result).duration_s < 30
    assert read_run(runs, manifest.run_id) == manifest
    assert not alive(pids[0])


def test_a_run_cancelled_before_it_starts_is_published_cancelled(
    runs: Path, sumo_binary: Path, pids: list[int]
) -> None:
    cancel = threading.Event()
    cancel.set()
    result = long_run(runs, sumo_binary, cancel=cancel)
    assert result.manifest.status == "cancelled"
    assert not alive(pids[0])


def test_ctrl_c_cancels_the_run_in_an_orderly_way(
    runs: Path, sumo_binary: Path, pids: list[int]
) -> None:
    class Interrupting(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            raise KeyboardInterrupt

    result = long_run(runs, sumo_binary, cancel=Interrupting())
    assert result.manifest.status == "cancelled"
    assert timing_of(runs, result).termination == "cancelled"
    assert not alive(pids[0])


def test_a_cancelled_prepared_folder_is_not_conciliated(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    cancel = threading.Event()
    cancel.set()
    result = run_inputs(folder, runs, sumo=sumo_binary, clock=clock, cancel=cancel)
    assert result.manifest.status == "cancelled"
    assert f"outputs/{CONCILIATION_TABLE}" not in published(result)
    remove_tree(tmp_path / "entradas")


# --- topes ----------------------------------------------------------------------------------


def test_a_run_over_the_output_limit_is_failed_and_stopped(
    runs: Path, sumo_binary: Path, pids: list[int]
) -> None:
    result = long_run(runs, sumo_binary, max_output_bytes=2000)
    manifest = result.manifest
    assert manifest.status == "failed"
    assert manifest.error is not None
    assert manifest.error.code == ErrorCode.SIM_FAILED.value
    assert "superaron el tope" in manifest.error.message
    assert timing_of(runs, result).termination == "output_budget"
    assert result.summary is None
    assert not alive(pids[0])


def test_a_run_over_the_memory_limit_is_failed_and_stopped(
    runs: Path, sumo_binary: Path, pids: list[int]
) -> None:
    result = long_run(runs, sumo_binary, max_memory_bytes=1024 * 1024)
    manifest = result.manifest
    assert manifest.status == "failed"
    assert manifest.error is not None
    assert manifest.error.code == ErrorCode.SIM_FAILED.value
    assert "de memoria y el tope es 1 MiB" in manifest.error.message
    timing = timing_of(runs, result)
    assert timing.termination == "memory_budget"
    assert timing.peak_memory_bytes is not None
    assert timing.peak_memory_bytes > 1024 * 1024
    assert not alive(pids[0])


def test_the_limits_given_to_the_process_are_the_ones_of_the_run(
    runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[ProcessLimits] = []
    real = runner.run_controlled

    def spy(*args: Any, **kwargs: Any) -> ProcessOutcome:  # noqa: ANN401
        seen.append(kwargs["limits"])
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "run_controlled", spy)
    limits = RunLimits(
        wall_timeout_s=111, max_output_bytes=222_000_000, max_log_bytes=333_000, poll_s=0.5
    )
    run_simulation(DEMO, "demo.sumocfg", runs, SPEC, limits=limits, sumo=sumo_binary, clock=clock)
    assert seen == [
        ProcessLimits(
            wall_timeout_s=111,
            max_output_bytes=222_000_000,
            max_log_bytes=333_000,
            max_memory_bytes=4 * 1024**3,
            poll_s=0.5,
        )
    ]


# --- antes de empezar -----------------------------------------------------------------------


def test_without_enough_memory_the_run_is_not_created(runs: Path, sumo_binary: Path) -> None:
    with pytest.raises(SimulacionError, match="no hay memoria para la corrida") as error:
        run_simulation(
            DEMO,
            "demo.sumocfg",
            runs,
            SPEC,
            limits=RunLimits(min_free_memory_bytes=10**15),
            sumo=sumo_binary,
        )
    assert error.value.code is ErrorCode.SIM_FAILED
    assert not runs.exists()


def test_without_enough_disk_the_run_is_not_created(runs: Path, sumo_binary: Path) -> None:
    with pytest.raises(SimulacionError, match="no hay espacio para la corrida") as error:
        run_simulation(
            DEMO,
            "demo.sumocfg",
            runs,
            SPEC,
            limits=RunLimits(max_output_bytes=10**18),
            sumo=sumo_binary,
        )
    assert error.value.code is ErrorCode.SIM_FAILED
    assert not runs.exists()


def test_a_run_that_cannot_start_for_its_path_still_publishes_its_timing(
    runs: Path, sumo_binary: Path
) -> None:
    result = run_simulation(
        DEMO,
        "demo.sumocfg",
        runs,
        SPEC,
        limits=RunLimits(max_path_chars=50),
        sumo=sumo_binary,
        clock=clock,
    )
    assert result.manifest.status == "failed"
    timing = timing_of(runs, result)
    assert (timing.termination, timing.duration_s, timing.peak_memory_bytes) == (
        "not_started",
        0.0,
        None,
    )
