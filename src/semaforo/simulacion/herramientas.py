"""Herramientas cortas del sistema: git, icacls, pg_dump y pg_restore (DEV31 F3).

Por la regla de estructura del proyecto, solo ``semaforo.simulacion`` lanza procesos hijos. La base
de datos (``semaforo.bd``) necesita algunas herramientas cortas, que no son SUMO: dar permisos a una
carpeta (``icacls``), respaldar y restaurar (``pg_dump`` y ``pg_restore``) y saber si un acta está
confirmada en git. Se lanzan aquí, siempre con una lista fija de argumentos, sin consola y con un
tiempo máximo. Para vigilar procesos largos está ``process.run_controlled``.
"""

import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ToolResult", "git_output", "run_tool"]

GIT_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ToolResult:
    """Cómo terminó una herramienta: su código y lo que escribió."""

    returncode: int
    stdout: str
    stderr: str


def run_tool(
    command: Sequence[str],
    *,
    timeout_s: float,
    environment: Mapping[str, str] | None = None,
) -> ToolResult | None:
    """Ejecuta ``command`` (programa y argumentos) y devuelve su resultado.

    ``None`` si el programa no se pudo lanzar o no terminó a tiempo.
    """
    try:
        completed = subprocess.run(  # noqa: S603  (lista de argumentos fija, sin shell)
            list(command),
            capture_output=True,
            timeout=timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
            env=None if environment is None else dict(environment),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return ToolResult(
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )


def git_output(root: Path, *arguments: str) -> str | None:
    """Lo que responde ``git -C root <arguments>``; ``None`` si falla o no hay git."""
    result = run_tool(["git", "-C", str(root), *arguments], timeout_s=GIT_TIMEOUT_S)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip()
