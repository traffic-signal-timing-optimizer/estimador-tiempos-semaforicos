"""Procesos reales para las pruebas de corridas interrumpidas (DEV07 F3).

Una corrida «caída de verdad» se prueba lanzando otro programa de Python, esperando a que avise
que ya está trabajando y terminándolo a la fuerza. Se usa el intérprete base y no el del entorno
virtual: en Windows el del entorno es un lanzador que crea otro proceso, y terminar al lanzador
dejaría vivo al verdadero.
"""

import contextlib
import ctypes
import os
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from pathlib import Path

PYTHON = str(getattr(sys, "_base_executable", sys.executable))
SOURCE = str(Path(__file__).resolve().parents[1] / "src")
WAIT_S = 30.0


def child_env() -> dict[str, str]:
    """El entorno del programa hijo: ve los mismos paquetes que esta prueba."""
    env = dict(os.environ)
    paths = [SOURCE, *(item for item in sys.path if item)]
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def spawn(folder: Path, body: str, *arguments: str) -> subprocess.Popen[bytes]:
    """Lanza un programa de Python (texto ``body``) con ``arguments``."""
    script = folder / "hijo.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return subprocess.Popen(  # noqa: S603  (lista de argumentos, sin shell)
        [PYTHON, str(script), *arguments],
        env=child_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_until(condition: Callable[[], bool], what: str, timeout_s: float = WAIT_S) -> None:
    """Espera a que ``condition`` se cumpla; falla con ``what`` si no pasa en ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"no ocurrió a tiempo: {what}")


def alive(pid: int) -> bool:
    """¿Existe un proceso con ese número? No lo mata (``os.kill(pid, 0)`` lo haría en Windows)."""
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


def kill_hard(process: subprocess.Popen[bytes]) -> None:
    """Termina el proceso sin darle oportunidad de limpiar: como un cierre a la fuerza."""
    process.kill()
    process.wait(timeout=WAIT_S)


def kill_pid(pid: int) -> None:
    """Termina el proceso con ese número si existe (limpieza al final de una prueba)."""
    with contextlib.suppress(OSError):
        if alive(pid):
            os.kill(pid, signal.SIGTERM)  # en Windows termina el proceso
