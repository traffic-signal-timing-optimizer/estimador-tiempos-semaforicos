"""Corridas interrumpidas y reintentos con SUMO real (DEV07 F3, D8 y D9).

La prueba central termina a la fuerza el programa que está ejecutando SUMO: la corrida no puede
quedar publicada, SUMO no puede seguir vivo y lo escrito hasta ese momento no se pierde.
"""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prepared_inputs import MOMENT, request_for
from process_tools import alive, kill_hard, kill_pid, spawn, wait_until
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.prepare import publish_inputs
from semaforo.simulacion.run_inputs import run_inputs
from semaforo.simulacion.runner import RunLimits, SimulationResult, run_simulation
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.interrupted import INCOMPLETE_DIR, list_interrupted
from semaforo.trazabilidad.store import RunSpec, RunWriter, read_run

pytestmark = pytest.mark.sumo

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"
SPEC = RunSpec(kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", seed=301)
LONG = 20_000_000  # segundos simulados: SUMO tarda más de 40 s en llegar
CRASHED = "20261101T120000Z_simulation_caida000"


def clock() -> datetime:
    return datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


def run(  # noqa: PLR0913  (los opcionales son de solo palabra clave)
    runs: Path,
    sumo: Path,
    spec: RunSpec = SPEC,
    *,
    cancel: threading.Event | None = None,
    wall_timeout_s: float = 900.0,
    end_s: float = 7200.0,
) -> SimulationResult:
    return run_simulation(
        DEMO,
        "demo.sumocfg",
        runs,
        spec,
        limits=RunLimits(end_s=end_s, wall_timeout_s=wall_timeout_s),
        sumo=sumo,
        clock=clock,
        cancel=cancel,
    )


def retry_of(run_id: str) -> RunSpec:
    return RunSpec(
        kind=SPEC.kind,
        case_id=SPEC.case_id,
        case_version=SPEC.case_version,
        seed=SPEC.seed,
        retry_of=run_id,
    )


def crash(runs: Path) -> None:
    with pytest.raises(RuntimeError), RunWriter(runs, SPEC, run_id=CRASHED, clock=clock) as writer:
        writer.output_path("parcial.txt").write_text("hasta aquí llegó", encoding="utf-8")
        raise RuntimeError("caída simulada")


# --- reintentos -----------------------------------------------------------------------------


def test_a_run_that_ran_out_of_time_is_retried_as_a_new_run(runs: Path, sumo_binary: Path) -> None:
    first = run(runs, sumo_binary, wall_timeout_s=0.5, end_s=LONG).manifest
    assert (first.status, first.error and first.error.code) == ("failed", "SIM_TIMEOUT")
    before = sha256_file(runs / first.run_id / "manifest.json")

    second = run(runs, sumo_binary, retry_of(first.run_id)).manifest

    assert second.status == "succeeded"
    assert second.retry_of == first.run_id
    assert second.run_id != first.run_id
    assert read_run(runs, second.run_id) == second
    assert read_run(runs, first.run_id) == first  # sigue verificable e intacta
    assert sha256_file(runs / first.run_id / "manifest.json") == before
    assert first.retry_of is None


def test_a_cancelled_run_is_retried_as_a_new_run(runs: Path, sumo_binary: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    first = run(runs, sumo_binary, cancel=cancel, end_s=LONG).manifest
    assert first.status == "cancelled"
    second = run(runs, sumo_binary, retry_of(first.run_id)).manifest
    assert (second.status, second.retry_of) == ("succeeded", first.run_id)


def test_a_succeeded_run_is_not_retried_and_nothing_is_created(
    runs: Path, sumo_binary: Path
) -> None:
    first = run(runs, sumo_binary).manifest
    assert first.status == "succeeded"
    before = sorted(p.name for p in runs.iterdir())
    with pytest.raises(DomainError) as raised:
        run(runs, sumo_binary, retry_of(first.run_id))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert sorted(p.name for p in runs.iterdir()) == before  # ni carpeta temporal ni lock


def test_a_retry_of_something_that_does_not_exist_creates_nothing(
    runs: Path, sumo_binary: Path
) -> None:
    with pytest.raises(DomainError) as raised:
        run(runs, sumo_binary, retry_of("20261101T120000Z_simulation_noexiste"))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert not runs.exists()


# --- corridas que se cayeron ----------------------------------------------------------------


def test_starting_a_run_sets_aside_a_crashed_one(runs: Path, sumo_binary: Path) -> None:
    crash(runs)
    result = run(runs, sumo_binary).manifest
    assert result.status == "succeeded"
    (interrupted,) = list_interrupted(runs)
    assert interrupted.run_id == CRASHED
    assert (runs / INCOMPLETE_DIR / CRASHED / "outputs" / "parcial.txt").is_file()
    assert sorted(p.name for p in runs.iterdir()) == [INCOMPLETE_DIR, result.run_id]


def test_an_interrupted_run_is_retried_in_the_same_call(runs: Path, sumo_binary: Path) -> None:
    crash(runs)
    result = run(runs, sumo_binary, retry_of(CRASHED)).manifest
    assert (result.status, result.retry_of) == ("succeeded", CRASHED)
    assert (runs / INCOMPLETE_DIR / CRASHED / "manifest.json").is_file()  # la evidencia sigue


KILLED_SUPERVISOR = """
    import subprocess, sys
    from pathlib import Path
    from semaforo.simulacion import process
    from semaforo.simulacion.runner import RunLimits, run_simulation
    from semaforo.trazabilidad.store import RunSpec

    demo, runs, sumo, pid_file = (Path(argument) for argument in sys.argv[1:5])
    launch = subprocess.Popen

    def spy(*arguments, **options):
        started = launch(*arguments, **options)
        if options.get("cwd") is not None:  # la corrida; no la consulta de la versión
            pid_file.write_text(str(started.pid))
        return started

    process.subprocess.Popen = spy
    spec = RunSpec(kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", seed=301)
    run_simulation(
        demo, "demo.sumocfg", runs, spec, limits=RunLimits(end_s=20_000_000), sumo=sumo
    )
"""


def test_killing_the_program_for_real_leaves_no_published_run_and_no_live_sumo(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    pid_file = tmp_path / "sumo.pid"
    supervisor = spawn(
        tmp_path, KILLED_SUPERVISOR, str(DEMO), str(runs), str(sumo_binary), str(pid_file)
    )
    sumo_pid = 0
    try:
        wait_until(lambda: pid_file.exists() and bool(pid_file.read_text()), "SUMO arrancó")
        sumo_pid = int(pid_file.read_text())
        assert alive(sumo_pid)
        (working,) = [p for p in runs.iterdir() if p.name.startswith(".tmp-")]
        wait_until(lambda: any((working / "outputs").iterdir()), "SUMO empezó a escribir")

        kill_hard(supervisor)  # como cerrar el programa desde el administrador de tareas

        wait_until(lambda: not alive(sumo_pid), "SUMO murió junto con el programa")
    finally:
        if supervisor.poll() is None:
            kill_hard(supervisor)
        if sumo_pid:
            kill_pid(sumo_pid)

    # el sistema suelta el bloqueo del programa muerto; la siguiente corrida aparta la caída
    result = run(runs, sumo_binary).manifest
    assert result.status == "succeeded"
    (interrupted,) = list_interrupted(runs)
    assert interrupted.run_id is not None
    assert interrupted.provisional_status == "running"
    assert any((runs / interrupted.folder / "outputs").iterdir())  # lo escrito se conserva
    with pytest.raises(DomainError):
        read_run(runs, interrupted.run_id)  # nunca fue una corrida publicada
    assert sorted(p.name for p in runs.iterdir()) == [INCOMPLETE_DIR, result.run_id]

    retried = run(runs, sumo_binary, retry_of(interrupted.run_id)).manifest
    assert (retried.status, retried.retry_of) == ("succeeded", interrupted.run_id)


def test_running_a_prepared_folder_can_retry_a_cancelled_run(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    try:
        cancel = threading.Event()
        cancel.set()
        first = run_inputs(folder, runs, sumo=sumo_binary, clock=clock, cancel=cancel).manifest
        assert first.status == "cancelled"
        second = run_inputs(
            folder, runs, sumo=sumo_binary, clock=clock, retry_of=first.run_id
        ).manifest
        assert (second.status, second.retry_of) == ("succeeded", first.run_id)
        with pytest.raises(DomainError) as raised:  # una exitosa ya no se reintenta
            run_inputs(folder, runs, sumo=sumo_binary, clock=clock, retry_of=second.run_id)
        assert raised.value.code is ErrorCode.INPUT_SCHEMA
    finally:
        remove_tree(tmp_path / "entradas")
