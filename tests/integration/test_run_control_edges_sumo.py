"""Bordes del corredor con SUMO real: qué se vigila y cuánto se exige antes de empezar (DEV07 F2).

Cierran los huecos de la primera pasada de mutaciones: los registros vigilados, el tamaño de
referencia, y el valor exacto de espacio y de memoria que se exige para empezar.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion import runner
from semaforo.simulacion.process import ProcessOutcome
from semaforo.simulacion.runner import RunLimits, SimulacionError, run_simulation
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.store import RunSpec

pytestmark = pytest.mark.sumo

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"
SPEC = RunSpec(kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", seed=301)


def clock() -> datetime:
    return datetime(2026, 10, 31, 23, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


def free_of(value: int) -> Callable[[Path], int]:
    def free(_path: Path) -> int:
        return value

    return free


def inputs_bytes() -> int:
    return sum(path.stat().st_size for path in DEMO.rglob("*") if path.is_file())


def run(runs: Path, sumo: Path, limits: RunLimits) -> str:
    return run_simulation(
        DEMO, "demo.sumocfg", runs, SPEC, limits=limits, sumo=sumo, clock=clock
    ).manifest.status


# --- qué se le pasa al proceso --------------------------------------------------------------


def test_the_process_watches_the_three_logs_and_does_not_count_the_inputs(
    runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []
    real = runner.run_controlled

    def spy(*args: Any, **kwargs: Any) -> ProcessOutcome:  # noqa: ANN401
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "run_controlled", spy)
    assert run(runs, sumo_binary, RunLimits()) == "succeeded"
    ((kwargs,),) = [(call,) for call in seen]
    assert [path.name for path in kwargs["logs"]] == [
        "sumo.stdout.txt",
        "sumo.stderr.txt",
        "sumo.log",
    ]
    assert kwargs["baseline_bytes"] >= inputs_bytes() > 0
    assert kwargs["watched"] == kwargs["cwd"]
    assert [kwargs["stdout_path"].name, kwargs["stderr_path"].name] == [
        "sumo.stdout.txt",
        "sumo.stderr.txt",
    ]


# --- valores exactos antes de empezar -------------------------------------------------------


def test_the_disk_needed_is_the_output_limit_plus_twice_the_inputs(
    runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits = RunLimits(max_output_bytes=50_000_000, min_free_memory_bytes=0)
    needed = 50_000_000 + 2 * inputs_bytes()
    monkeypatch.setattr(runner, "free_disk_bytes", free_of(needed - 1))
    with pytest.raises(SimulacionError, match="no hay espacio para la corrida") as error:
        run(runs, sumo_binary, limits)
    assert error.value.code is ErrorCode.SIM_FAILED
    assert f"hacen falta {needed // (1024 * 1024)} MiB" in error.value.message
    assert not runs.exists()
    monkeypatch.setattr(runner, "free_disk_bytes", free_of(needed))
    assert run(runs, sumo_binary, limits) == "succeeded"


def test_the_memory_needed_is_exactly_the_minimum(
    runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    minimum = 700 * 1024 * 1024
    limits = RunLimits(min_free_memory_bytes=minimum)
    monkeypatch.setattr(runner, "available_memory_bytes", lambda: minimum - 1)
    with pytest.raises(SimulacionError, match="no hay memoria para la corrida") as error:
        run(runs, sumo_binary, limits)
    assert "hacen falta 700 MiB disponibles y quedan 699 MiB" in error.value.message
    assert not runs.exists()
    monkeypatch.setattr(runner, "available_memory_bytes", lambda: minimum)
    assert run(runs, sumo_binary, limits) == "succeeded"


def test_a_memory_that_cannot_be_measured_does_not_stop_the_run(
    runs: Path, sumo_binary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "available_memory_bytes", lambda: None)
    assert run(runs, sumo_binary, RunLimits(min_free_memory_bytes=10**15)) == "succeeded"
