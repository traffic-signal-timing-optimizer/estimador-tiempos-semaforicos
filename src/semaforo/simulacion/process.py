"""Proceso controlado: lanza un programa y lo vigila hasta que termina (DEV07 F2, D4 a D6 y D19).

Reemplaza a ``subprocess.run`` del corredor de DEV00, que no se podía cancelar y guardaba toda la
salida en memoria. Aquí:

- ``stdout`` y ``stderr`` van directo a archivos, no a memoria.
- Un ciclo revisa cada ``poll_s`` segundos si el proceso terminó, si se pidió cancelar, si se
  pasó el tiempo real, si las salidas superaron su tope y si el proceso superó su tope de memoria.
- Al cortar el proceso (por tiempo, cancelación o tope) se le pide terminar, a los 5 s se fuerza
  y se espera a que muera: nunca queda un proceso huérfano. Las salidas parciales se conservan.
- Ctrl+C en la consola cancela la corrida de forma ordenada. En Windows el proceso hijo nace en su
  propio grupo, para que Ctrl+C no llegue directo a él y lo corte a medias.

El resultado dice por qué terminó (``cause``); decidir si eso es éxito, fallo o cancelación es de
quien llama.
"""

import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from semaforo.simulacion.resources import MemoryProbe
from semaforo.simulacion.summary import Termination

__all__ = ["ProcessLimits", "ProcessOutcome", "run_controlled", "tree_bytes"]

GRACE_S = 5.0
MIB = 1024 * 1024
# En Windows: el proceso hijo nace en un grupo propio (no recibe el Ctrl+C de la consola).
NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


@dataclass(frozen=True)
class ProcessLimits:
    """Topes de un proceso controlado. Todos positivos."""

    wall_timeout_s: float
    max_output_bytes: int
    max_log_bytes: int
    max_memory_bytes: int
    poll_s: float = 0.25

    def __post_init__(self) -> None:
        values = (
            self.wall_timeout_s,
            self.max_output_bytes,
            self.max_log_bytes,
            self.max_memory_bytes,
            self.poll_s,
        )
        if min(values) <= 0:
            raise ValueError("los topes del proceso deben ser positivos")


@dataclass(frozen=True)
class ProcessOutcome:
    """Cómo terminó el proceso.

    ``returncode`` solo existe si el proceso terminó por su cuenta (``completed`` o
    ``sumo_error``); si se lo cortó, es ``None``. ``output_bytes`` es lo que escribió, sin contar
    lo que había antes de lanzarlo. ``pid`` es el número del proceso, útil para comprobar que ya
    no existe.
    """

    pid: int
    returncode: int | None
    cause: Termination
    detail: str | None
    duration_s: float
    peak_memory_bytes: int | None
    output_bytes: int


def tree_bytes(folder: Path) -> int:
    """Suma de los tamaños de los archivos de ``folder`` y sus subcarpetas."""
    total = 0
    pending = [folder]
    while pending:
        try:
            entries = list(pending.pop().iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir() and not entry.is_symlink():
                    pending.append(entry)
                elif entry.is_file():
                    total += entry.stat().st_size
            except OSError:
                continue  # el archivo desapareció o está bloqueado mientras se escribe
    return total


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _mib(value: int) -> str:
    return f"{value / MIB:.0f} MiB"


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Termina el proceso: se lo pide, a los 5 s lo fuerza y espera a que muera."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=GRACE_S)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@dataclass(frozen=True)
class _Watch:
    """Lo que el ciclo de vigilancia necesita saber de la corrida."""

    watched: Path
    baseline_bytes: int
    logs: Sequence[Path]
    limits: ProcessLimits


def _limit_problem(watch: _Watch, probe: MemoryProbe) -> tuple[Termination, str] | None:
    """Primer tope superado (salidas, registros o memoria), con su motivo; ``None`` si ninguno."""
    limits = watch.limits
    written = tree_bytes(watch.watched) - watch.baseline_bytes
    if written > limits.max_output_bytes:
        return "output_budget", f"las salidas superaron el tope de {_mib(limits.max_output_bytes)}"
    for log in watch.logs:
        if _size(log) > limits.max_log_bytes:
            return (
                "output_budget",
                f"el registro {log.name} superó el tope de {_mib(limits.max_log_bytes)}",
            )
    peak = probe.peak_bytes()
    if peak is not None and peak > limits.max_memory_bytes:
        return (
            "memory_budget",
            f"SUMO usó {_mib(peak)} de memoria y el tope es {_mib(limits.max_memory_bytes)}",
        )
    return None


def _supervise(
    process: subprocess.Popen[bytes],
    probe: MemoryProbe,
    watch: _Watch,
    cancel: threading.Event | None,
    pause: Callable[[float], object],
) -> tuple[Termination, str | None]:
    """Vigila al proceso hasta que termine o haya que cortarlo."""
    started = time.monotonic()
    limits = watch.limits
    while True:
        code = process.poll()
        if code is not None:
            cause: Termination = "completed" if code == 0 else "sumo_error"
            problem = _limit_problem(watch, probe)
            return (cause, None) if problem is None else problem
        if cancel is not None and cancel.is_set():
            _stop(process)
            return "cancelled", "se pidió cancelar la corrida"
        remaining = limits.wall_timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            _stop(process)
            return "timeout", f"SUMO superó el límite de {limits.wall_timeout_s:g} s de tiempo real"
        problem = _limit_problem(watch, probe)
        if problem is not None:
            _stop(process)
            return problem
        pause(min(limits.poll_s, remaining))  # despierta justo en el límite de tiempo


def run_controlled(  # noqa: PLR0913  (todos de solo palabra clave, cada uno es un dato distinto)
    command: Sequence[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    watched: Path,
    baseline_bytes: int,
    logs: Sequence[Path],
    limits: ProcessLimits,
    cancel: threading.Event | None = None,
    pause: Callable[[float], object] | None = None,
) -> ProcessOutcome:
    """Lanza ``command`` en ``cwd`` y lo vigila hasta que termine o haya que cortarlo.

    Args:
        command: programa y argumentos como lista; nunca pasa por un shell.
        cwd: carpeta donde corre.
        stdout_path: archivo donde va la salida estándar (se crea).
        stderr_path: archivo donde va la salida de error (se crea).
        watched: carpeta cuyo tamaño se vigila (la de la corrida).
        baseline_bytes: tamaño de ``watched`` antes de lanzar; no cuenta para el tope.
        logs: archivos que no pueden superar ``limits.max_log_bytes``.
        limits: topes de tiempo, salidas y memoria.
        cancel: evento que, al activarse, cancela el proceso (se revisa en cada vuelta).
        pause: espera entre vueltas; por defecto espera sobre ``cancel`` o duerme ``poll_s``.

    Raises:
        OSError: si el programa no se puede lanzar.
    """
    wait: Callable[[float], object] = pause or (cancel.wait if cancel is not None else time.sleep)
    started = time.monotonic()
    watch = _Watch(watched, baseline_bytes, logs, limits)
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        process = subprocess.Popen(  # noqa: S603  (lista de argumentos, sin shell: ADR04)
            list(command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=NEW_PROCESS_GROUP,
        )
        probe = MemoryProbe(process.pid)
        try:
            cause, detail = _supervise(process, probe, watch, cancel, wait)
        except KeyboardInterrupt:
            _stop(process)
            cause, detail = "cancelled", "interrupción con Ctrl+C"
        finally:
            _stop(process)  # nada queda vivo, ocurra lo que ocurra
            peak = probe.peak_bytes()
            probe.close()
    finished_by_itself = cause in ("completed", "sumo_error")
    return ProcessOutcome(
        pid=process.pid,
        returncode=process.returncode if finished_by_itself else None,
        cause=cause,
        detail=detail,
        duration_s=time.monotonic() - started,
        peak_memory_bytes=peak,
        output_bytes=max(0, tree_bytes(watched) - baseline_bytes),
    )
