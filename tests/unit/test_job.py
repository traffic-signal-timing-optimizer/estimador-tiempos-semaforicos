"""Que el proceso lanzado muera con el programa que lo lanzó (DEV07 F3, D8)."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from process_tools import PYTHON, alive, child_env, kill_hard, kill_pid, spawn, wait_until
from semaforo.simulacion.job import KillOnClose

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="el grupo de procesos es de Windows"
)


def sleeper() -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603  (lista de argumentos, sin shell)
        [PYTHON, "-c", "import time; time.sleep(120)"], env=child_env()
    )


@pytest.mark.skipif(sys.platform == "win32", reason="en Windows sí hay grupo")
def test_without_process_groups_nothing_is_attached() -> None:
    process = sleeper()
    try:
        assert KillOnClose.attach(process.pid) is None
    finally:
        kill_hard(process)


@WINDOWS_ONLY
def test_closing_the_group_kills_what_is_inside() -> None:
    process = sleeper()
    try:
        group = KillOnClose.attach(process.pid)
        assert group is not None
        time.sleep(0.2)
        assert alive(process.pid)
        group.close()
        process.wait(timeout=10)
        assert not alive(process.pid)
        group.close()  # cerrar dos veces no hace nada
    finally:
        if process.poll() is None:
            kill_hard(process)


@WINDOWS_ONLY
def test_a_process_that_does_not_exist_is_not_attached() -> None:
    process = sleeper()
    kill_hard(process)
    assert KillOnClose.attach(process.pid) is None


PARENT = """
    import sys
    from pathlib import Path
    from semaforo.simulacion.process import ProcessLimits, run_controlled
    folder = Path(sys.argv[1])
    child = (
        "import os, time, pathlib;"
        "pathlib.Path('hijo.pid').write_text(str(os.getpid())); time.sleep(120)"
    )
    run_controlled(
        [sys.executable, "-c", child],
        cwd=folder,
        stdout_path=folder / "o.txt",
        stderr_path=folder / "e.txt",
        watched=folder,
        baseline_bytes=0,
        logs=[],
        limits=ProcessLimits(300, 10**9, 10**9, 10**12),
    )
"""


@WINDOWS_ONLY
def test_when_the_supervisor_is_killed_the_process_it_launched_dies_too(tmp_path: Path) -> None:
    parent = spawn(tmp_path, PARENT, str(tmp_path))
    child = 0
    try:
        pid_file = tmp_path / "hijo.pid"
        wait_until(
            lambda: pid_file.exists() and bool(pid_file.read_text()), "nació el proceso hijo"
        )
        child = int(pid_file.read_text())
        assert alive(child)
        kill_hard(parent)
        wait_until(lambda: not alive(child), "el sistema mató al proceso hijo")
    finally:
        if parent.poll() is None:
            kill_hard(parent)
        if child:
            kill_pid(child)


GRANDCHILD = """
    import subprocess, sys, time
    from pathlib import Path
    from semaforo.simulacion.process import ProcessLimits, run_controlled
    folder = Path(sys.argv[1])
    spawner = (
        "import subprocess, sys, pathlib;"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']);"
        "pathlib.Path('nieto.pid').write_text(str(g.pid))"
    )
    run_controlled(
        [sys.executable, "-c", spawner],
        cwd=folder,
        stdout_path=folder / "o.txt",
        stderr_path=folder / "e.txt",
        watched=folder,
        baseline_bytes=0,
        logs=[],
        limits=ProcessLimits(300, 10**9, 10**9, 10**12),
    )
    (folder / "devuelto.txt").write_text("1")
    time.sleep(120)  # el programa sigue vivo: el nieto debe morir por la corrida, no por esto
"""


@WINDOWS_ONLY
def test_a_process_left_behind_by_the_launched_one_does_not_outlive_the_run(
    tmp_path: Path,
) -> None:
    runner = spawn(tmp_path, GRANDCHILD, str(tmp_path))
    grandchild = 0
    try:
        wait_until((tmp_path / "devuelto.txt").exists, "la corrida terminó")
        grandchild = int((tmp_path / "nieto.pid").read_text())
        wait_until(lambda: not alive(grandchild), "el nieto murió al terminar la corrida")
    finally:
        if runner.poll() is None:
            kill_hard(runner)
        if grandchild:
            kill_pid(grandchild)
