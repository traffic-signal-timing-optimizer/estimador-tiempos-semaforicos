"""Proceso controlado: tiempo, cancelación, topes de salida y de memoria (DEV07 F2, D4 a D6, D19).

Los procesos hijos son programas de Python escritos en un archivo. Se usa el intérprete base y no
el del entorno virtual: en Windows ese es un lanzador que crea otro proceso, y se mediría el
lanzador (5 MB) y no el programa.
"""

import ctypes
import os
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from semaforo.simulacion import process as process_module
from semaforo.simulacion.process import ProcessLimits, ProcessOutcome, run_controlled, tree_bytes

PYTHON = str(getattr(sys, "_base_executable", sys.executable))  # el real, no el lanzador
MIB = 1024 * 1024
BIG = 10**12


def limits(**changes: float) -> ProcessLimits:
    values: dict[str, float] = {
        "wall_timeout_s": 30,
        "max_output_bytes": BIG,
        "max_log_bytes": BIG,
        "max_memory_bytes": BIG,
        "poll_s": 0.05,
    }
    values.update(changes)
    return ProcessLimits(
        wall_timeout_s=values["wall_timeout_s"],
        max_output_bytes=int(values["max_output_bytes"]),
        max_log_bytes=int(values["max_log_bytes"]),
        max_memory_bytes=int(values["max_memory_bytes"]),
        poll_s=values["poll_s"],
    )


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "corrida"
    (folder / "outputs").mkdir(parents=True)
    (folder / "inputs").mkdir()
    (folder / "inputs" / "entrada.txt").write_bytes(b"x" * 1000)
    return folder


def script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "hijo.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [PYTHON, str(path)]


def control(
    run_dir: Path,
    command: list[str],
    *,
    cancel: threading.Event | None = None,
    pause: Callable[[float], object] | None = None,
    **changes: float,
) -> ProcessOutcome:
    return run_controlled(
        command,
        cwd=run_dir,
        stdout_path=run_dir / "outputs" / "stdout.txt",
        stderr_path=run_dir / "outputs" / "stderr.txt",
        watched=run_dir,
        baseline_bytes=tree_bytes(run_dir),
        logs=[run_dir / "outputs" / "stdout.txt", run_dir / "outputs" / "stderr.txt"],
        limits=limits(**changes),
        cancel=cancel,
        pause=pause,
    )


def alive(pid: int) -> bool:
    """Si el proceso ``pid`` sigue vivo. En Windows no se usa ``os.kill``: ahí mata al proceso."""
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


# --- terminar por su cuenta ----------------------------------------------------------------


def test_a_process_that_ends_well_is_completed(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, 'print("hola")'))
    assert (outcome.cause, outcome.returncode, outcome.detail) == ("completed", 0, None)
    assert (run_dir / "outputs" / "stdout.txt").read_text(encoding="utf-8").strip() == "hola"


def test_the_error_output_goes_to_its_own_file(tmp_path: Path, run_dir: Path) -> None:
    body = 'import sys\nprint("fallo", file=sys.stderr)\nprint("normal")\n'
    control(run_dir, script(tmp_path, body))
    assert (run_dir / "outputs" / "stderr.txt").read_text(encoding="utf-8").strip() == "fallo"
    assert (run_dir / "outputs" / "stdout.txt").read_text(encoding="utf-8").strip() == "normal"


def test_a_process_that_fails_keeps_its_exit_code(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, "import sys\nsys.exit(3)"))
    assert (outcome.cause, outcome.returncode, outcome.detail) == ("sumo_error", 3, None)


def test_the_duration_and_the_output_are_measured(tmp_path: Path, run_dir: Path) -> None:
    body = 'import sys, time\nsys.stdout.write("x" * 5000)\nsys.stdout.flush()\ntime.sleep(0.3)\n'
    outcome = control(run_dir, script(tmp_path, body))
    assert outcome.duration_s >= 0.3
    assert outcome.output_bytes >= 5000


def test_the_baseline_does_not_count_as_output(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, "pass"), max_output_bytes=100)
    assert outcome.cause == "completed"


# --- tiempo --------------------------------------------------------------------------------


def test_a_process_over_the_time_limit_is_stopped(tmp_path: Path, run_dir: Path) -> None:
    started = time.monotonic()
    outcome = control(run_dir, script(tmp_path, "import time\ntime.sleep(60)"), wall_timeout_s=0.5)
    assert outcome.cause == "timeout"
    assert outcome.returncode is None
    assert outcome.detail == "SUMO superó el límite de 0.5 s de tiempo real"
    assert time.monotonic() - started < 10


def test_the_loop_wakes_up_at_the_time_limit_even_with_a_long_poll(
    tmp_path: Path, run_dir: Path
) -> None:
    """Un proceso que termina después del límite pero antes de la siguiente vuelta es un exceso."""
    body = "import time; time.sleep(1.5)"
    started = time.monotonic()
    outcome = control(run_dir, script(tmp_path, body), wall_timeout_s=0.3, poll_s=5)
    assert outcome.cause == "timeout"
    assert time.monotonic() - started < 4


def test_the_outcome_gives_the_process_number(tmp_path: Path, run_dir: Path) -> None:
    body = "import os; open('pid.txt', 'w').write(str(os.getpid()))"
    outcome = control(run_dir, script(tmp_path, body))
    assert outcome.pid == int((run_dir / "pid.txt").read_text(encoding="utf-8"))


def test_the_partial_output_of_a_stopped_process_is_kept(tmp_path: Path, run_dir: Path) -> None:
    body = 'import time\nprint("parcial", flush=True)\ntime.sleep(60)\n'
    outcome = control(run_dir, script(tmp_path, body), wall_timeout_s=1.5)
    assert outcome.cause == "timeout"
    assert (run_dir / "outputs" / "stdout.txt").read_text(encoding="utf-8").strip() == "parcial"


# --- cancelación ---------------------------------------------------------------------------


def test_a_cancel_event_stops_the_process(tmp_path: Path, run_dir: Path) -> None:
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    outcome = control(run_dir, script(tmp_path, "import time\ntime.sleep(60)"), cancel=cancel)
    assert (outcome.cause, outcome.returncode) == ("cancelled", None)
    assert outcome.detail == "se pidió cancelar la corrida"
    assert time.monotonic() - started < 10


def test_a_cancel_already_asked_stops_before_anything_else(tmp_path: Path, run_dir: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    outcome = control(run_dir, script(tmp_path, "import time\ntime.sleep(60)"), cancel=cancel)
    assert outcome.cause == "cancelled"


def test_ctrl_c_cancels_in_an_orderly_way(tmp_path: Path, run_dir: Path) -> None:
    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    outcome = control(
        run_dir, script(tmp_path, "import time\ntime.sleep(60)"), pause=interrupt, poll_s=0.05
    )
    assert (outcome.cause, outcome.returncode) == ("cancelled", None)
    assert outcome.detail == "interrupción con Ctrl+C"


PID_WRITER = """
    import os, time
    open("pid.txt", "w").write(str(os.getpid()))
    time.sleep(60)
"""


def test_the_process_is_dead_after_each_way_of_stopping(tmp_path: Path, run_dir: Path) -> None:
    sleeper = script(tmp_path, PID_WRITER)
    control(run_dir, sleeper, wall_timeout_s=1.5)
    by_time = int((run_dir / "pid.txt").read_text(encoding="utf-8"))
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    control(run_dir, sleeper, cancel=cancel)
    by_cancel = int((run_dir / "pid.txt").read_text(encoding="utf-8"))
    assert by_time != by_cancel
    assert not alive(by_time)
    assert not alive(by_cancel)


def test_a_process_that_ignores_the_request_is_forced(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si no muere a los pocos segundos de pedírselo, se lo fuerza."""
    monkeypatch.setattr(process_module, "GRACE_S", 0.3)
    kill = subprocess.Popen[bytes].kill
    forced: list[bool] = []

    def ignore_request(_: subprocess.Popen[bytes]) -> None:
        return None

    def record_kill(self: subprocess.Popen[bytes]) -> None:
        forced.append(True)
        kill(self)

    monkeypatch.setattr(subprocess.Popen, "terminate", ignore_request)
    monkeypatch.setattr(subprocess.Popen, "kill", record_kill)
    outcome = control(run_dir, script(tmp_path, PID_WRITER), wall_timeout_s=1.5)
    assert outcome.cause == "timeout"
    assert forced == [True]
    assert not alive(int((run_dir / "pid.txt").read_text(encoding="utf-8")))


# --- topes de salida -----------------------------------------------------------------------

SPAMMER = """
    import sys, time
    for _ in range(600):
        sys.stdout.write("x" * 100_000)
        sys.stdout.flush()
        time.sleep(0.01)
"""


def test_an_output_over_the_total_limit_stops_the_process(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, SPAMMER), max_output_bytes=2 * MIB)
    assert outcome.cause == "output_budget"
    assert outcome.returncode is None
    assert outcome.detail == "las salidas superaron el tope de 2 MiB"
    assert 2 * MIB <= outcome.output_bytes < 40 * MIB


def test_a_log_over_its_limit_stops_the_process(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, SPAMMER), max_log_bytes=1 * MIB)
    assert outcome.cause == "output_budget"
    assert outcome.detail == "el registro stdout.txt superó el tope de 1 MiB"


def test_an_output_over_the_limit_is_noticed_even_if_the_process_already_ended(
    tmp_path: Path, run_dir: Path
) -> None:
    body = 'import sys\nsys.stdout.write("x" * 3_000_000)\n'
    outcome = control(run_dir, script(tmp_path, body), max_output_bytes=1 * MIB)
    assert outcome.cause == "output_budget"


def test_the_output_is_not_held_in_memory(tmp_path: Path, run_dir: Path) -> None:
    body = 'import sys\nfor _ in range(30):\n    sys.stdout.write("x" * 1_000_000)\n'
    outcome = control(run_dir, script(tmp_path, body))
    assert outcome.cause == "completed"
    assert (run_dir / "outputs" / "stdout.txt").stat().st_size == 30_000_000


# --- memoria -------------------------------------------------------------------------------

HUNGRY = """
    import time
    memory = bytearray(b"\\x01") * (120 * 1024 * 1024)
    print("listo", flush=True)
    time.sleep(60)
"""


def test_a_process_over_the_memory_limit_is_stopped(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, HUNGRY), max_memory_bytes=60 * MIB)
    assert outcome.cause == "memory_budget"
    assert outcome.returncode is None
    assert outcome.detail is not None
    assert "el tope es 60 MiB" in outcome.detail
    assert outcome.peak_memory_bytes is not None
    assert outcome.peak_memory_bytes > 60 * MIB


def test_the_peak_memory_is_reported_when_the_process_ends(tmp_path: Path, run_dir: Path) -> None:
    body = 'memory = bytearray(b"\\x01") * (80 * 1024 * 1024)\n'
    outcome = control(run_dir, script(tmp_path, body))
    assert outcome.cause == "completed"
    assert outcome.peak_memory_bytes is not None
    assert outcome.peak_memory_bytes > 70 * MIB


# --- límites y errores ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["wall_timeout_s", "max_output_bytes", "max_log_bytes", "max_memory_bytes", "poll_s"]
)
def test_every_limit_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError, match="positivos"):
        limits(**{field: 0})


def test_a_program_that_cannot_be_launched_raises(tmp_path: Path, run_dir: Path) -> None:
    with pytest.raises(OSError):
        control(run_dir, [str(tmp_path / "no-existe.exe")])


def test_the_tree_size_counts_files_in_subfolders(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "x.bin").write_bytes(b"1" * 10)
    (tmp_path / "a" / "b" / "y.bin").write_bytes(b"2" * 32)
    assert tree_bytes(tmp_path) == 42
    assert tree_bytes(tmp_path / "no-existe") == 0
