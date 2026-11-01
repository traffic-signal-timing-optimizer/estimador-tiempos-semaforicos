"""Bordes del proceso controlado: valores exactos de los topes y cierre ante errores (DEV07 F2).

Cierran los huecos que dejó la primera pasada de mutaciones: un tope igual al valor medido no
corta el proceso, y un error inesperado en la vigilancia nunca deja un proceso vivo.
"""

import ctypes
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from semaforo.simulacion import process as process_module
from semaforo.simulacion.process import (
    NEW_PROCESS_GROUP,
    ProcessLimits,
    ProcessOutcome,
    run_controlled,
    tree_bytes,
)

PYTHON = str(getattr(sys, "_base_executable", sys.executable))  # el real, no el lanzador
BIG = 10**12


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


def limits(*, max_output: int = BIG, max_log: int = BIG, max_memory: int = BIG) -> ProcessLimits:
    return ProcessLimits(30, max_output, max_log, max_memory, poll_s=0.05)


def control(
    run_dir: Path, command: list[str], bounds: ProcessLimits | None = None
) -> ProcessOutcome:
    return run_controlled(
        command,
        cwd=run_dir,
        stdout_path=run_dir / "outputs" / "stdout.txt",
        stderr_path=run_dir / "outputs" / "stderr.txt",
        watched=run_dir,
        baseline_bytes=tree_bytes(run_dir),
        logs=[run_dir / "outputs" / "stdout.txt"],
        limits=bounds or limits(),
    )


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


# --- valores exactos de los topes -----------------------------------------------------------

WRITES_EXACTLY = 'import sys\nsys.stdout.write("x" * 2000)\n'


def test_an_output_exactly_at_the_limit_is_allowed(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, WRITES_EXACTLY), limits(max_output=2000))
    assert (outcome.cause, outcome.output_bytes) == ("completed", 2000)


def test_one_byte_over_the_output_limit_is_not_allowed(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, WRITES_EXACTLY), limits(max_output=1999))
    assert outcome.cause == "output_budget"


def test_a_log_exactly_at_its_limit_is_allowed(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, WRITES_EXACTLY), limits(max_log=2000))
    assert outcome.cause == "completed"


def test_one_byte_over_the_log_limit_is_not_allowed(tmp_path: Path, run_dir: Path) -> None:
    outcome = control(run_dir, script(tmp_path, WRITES_EXACTLY), limits(max_log=1999))
    assert outcome.cause == "output_budget"


class FixedProbe:
    """Una medida de memoria que siempre da el mismo valor, para probar el borde exacto."""

    peak = 0

    def __init__(self, pid: int) -> None:
        self.pid = pid

    def peak_bytes(self) -> int | None:
        return FixedProbe.peak

    def close(self) -> None:
        return None


def test_a_memory_exactly_at_the_limit_is_allowed(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(process_module, "MemoryProbe", FixedProbe)
    FixedProbe.peak = 5_000_000
    outcome = control(run_dir, script(tmp_path, "pass"), limits(max_memory=5_000_000))
    assert (outcome.cause, outcome.peak_memory_bytes) == ("completed", 5_000_000)


def test_one_byte_over_the_memory_limit_is_not_allowed(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(process_module, "MemoryProbe", FixedProbe)
    FixedProbe.peak = 5_000_001
    outcome = control(run_dir, script(tmp_path, "pass"), limits(max_memory=5_000_000))
    assert outcome.cause == "memory_budget"


def test_an_unknown_memory_does_not_stop_the_process(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Blind(FixedProbe):
        def peak_bytes(self) -> int | None:
            return None

    monkeypatch.setattr(process_module, "MemoryProbe", Blind)
    outcome = control(run_dir, script(tmp_path, "pass"), limits(max_memory=1))
    assert (outcome.cause, outcome.peak_memory_bytes) == ("completed", None)


# --- cómo se lanza --------------------------------------------------------------------------


def test_the_process_is_launched_without_a_shell_in_its_own_group(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    real = subprocess.Popen

    def spy(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(process_module.subprocess, "Popen", spy)
    control(run_dir, script(tmp_path, "pass"))
    ((args, kwargs),) = calls
    assert isinstance(args[0], list)
    assert not kwargs.get("shell", False)
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["cwd"] == run_dir
    assert kwargs["creationflags"] == NEW_PROCESS_GROUP
    if sys.platform == "win32":
        assert NEW_PROCESS_GROUP == 0x00000200


# --- un error inesperado no deja procesos vivos ---------------------------------------------

PID_WRITER = """
    import os, time
    open("pid.txt", "w").write(str(os.getpid()))
    time.sleep(60)
"""


def test_an_unexpected_error_in_the_watch_never_leaves_a_process_alive(
    tmp_path: Path, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def breaks(*_: object) -> None:
        for _attempt in range(100):  # espera a que el hijo escriba su número de proceso
            if (run_dir / "pid.txt").exists() and (run_dir / "pid.txt").stat().st_size > 0:
                break
            time.sleep(0.05)
        raise RuntimeError("falló la vigilancia")

    monkeypatch.setattr(process_module, "_limit_problem", breaks)
    with pytest.raises(RuntimeError, match="falló la vigilancia"):
        control(run_dir, script(tmp_path, PID_WRITER))
    pid = int((run_dir / "pid.txt").read_text(encoding="utf-8"))
    assert not alive(pid)


# --- tamaño de una carpeta ------------------------------------------------------------------


def test_a_folder_that_is_a_link_is_not_followed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "grande.bin").write_bytes(b"x" * 500)
    watched = tmp_path / "vigilada"
    watched.mkdir()
    (watched / "propio.bin").write_bytes(b"y" * 10)
    try:
        (watched / "enlace").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    assert tree_bytes(watched) == 10
