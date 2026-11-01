"""Corrida de una carpeta de entradas: ``python -m semaforo simulate run`` (DEV07 F4, D12).

Une lo que hicieron las fases anteriores de DEV07 y lo deja listo para la interfaz de comandos:
aparta las corridas que una caída dejó a medias, ejecuta la carpeta de entradas con sus límites,
y resume cómo terminó en un informe que la interfaz escribe en JSON.

Códigos de salida (diseño técnico, «Errores y códigos de salida»): 0 si la corrida fue exitosa;
el de su error si fracasó (SIM_FAILED y SIM_TIMEOUT dan 4); 4 si fue cancelada, con
``status: cancelled``. Quien lea la salida debe mirar ``status``, no solo el código.
"""

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from semaforo.app.exit_codes import INTERNAL_ERROR_EXIT, exit_code_for
from semaforo.app.reception import RUNS
from semaforo.dominio.base_model import FrozenModel
from semaforo.simulacion.run_inputs import CONCILIATION_SUMMARY, ConciliationSummary, run_inputs
from semaforo.simulacion.runner import TIMING, RunLimits, SimulationResult
from semaforo.simulacion.summary import RunTiming, SimulationSummary
from semaforo.trazabilidad.fs import read_at_most
from semaforo.trazabilidad.interrupted import recover_interrupted
from semaforo.trazabilidad.store import OUTPUTS, utc_now

__all__ = ["CANCELLED_EXIT", "RunReport", "exit_code_of", "run_prepared"]

CANCELLED_EXIT = 4
MAX_SMALL_FILE_BYTES = 1024 * 1024


class RunReport(FrozenModel):
    """Cómo terminó la corrida. Las rutas son relativas al espacio de trabajo.

    ``status`` es ``succeeded``, ``failed`` o ``cancelled``. ``error_code`` y ``error_message``
    solo existen si fracasó. ``recovered_interrupted`` lista las corridas caídas que se apartaron
    antes de empezar (carpetas dentro de ``.incompletas``).
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["succeeded", "failed", "cancelled"]
    run_id: str
    path: str
    retry_of: str | None
    scenario_id: str | None
    error_code: str | None
    error_message: str | None
    timing: RunTiming | None
    summary: SimulationSummary | None
    conciliation: ConciliationSummary | None
    recovered_interrupted: list[str]
    exit_code: int


def _small_file(path: Path) -> bytes | None:
    try:
        with path.open("rb") as stream:
            data = read_at_most(stream, MAX_SMALL_FILE_BYTES + 1)
    except OSError:
        return None
    return data if len(data) <= MAX_SMALL_FILE_BYTES else None


def _timing(run_folder: Path) -> RunTiming | None:
    data = _small_file(run_folder / OUTPUTS / TIMING)
    if data is None:
        return None
    try:
        return RunTiming.model_validate_json(data)
    except ValidationError:
        return None


def _conciliation(run_folder: Path) -> ConciliationSummary | None:
    data = _small_file(run_folder / OUTPUTS / CONCILIATION_SUMMARY)
    if data is None:
        return None
    try:
        return ConciliationSummary.model_validate_json(data)
    except ValidationError:
        return None


def exit_code_of(result: SimulationResult) -> int:
    """Código de salida de una corrida ya publicada."""
    manifest = result.manifest
    if manifest.status == "succeeded":
        return 0
    if manifest.status == "cancelled":
        return CANCELLED_EXIT
    return INTERNAL_ERROR_EXIT if manifest.error is None else exit_code_for(manifest.error.code)


def run_prepared(  # noqa: PLR0913  (los opcionales son de solo palabra clave)
    inputs: Path,
    workspace: Path,
    *,
    sumo: Path | None = None,
    wall_timeout_s: float | None = None,
    retry_of: str | None = None,
    cancel: threading.Event | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> RunReport:
    """Ejecuta la carpeta de entradas ``inputs`` y publica la corrida en ``workspace/ejecuciones``.

    Una corrida fallida o cancelada no es una excepción: se devuelve publicada, con su estado.

    Args:
        inputs: carpeta de entradas que publicó DEV06.
        workspace: espacio de trabajo; las corridas van en ``<workspace>/ejecuciones``.
        sumo: ejecutable de SUMO; si es None, se busca con ``SUMO_HOME``.
        wall_timeout_s: tiempo real máximo; si es None, el provisional (900 s).
        retry_of: ``run_id`` de la corrida que se reintenta.
        cancel: evento que cancela la corrida al activarse (Ctrl+C hace lo mismo).
        clock: reloj con zona horaria.

    Raises:
        DomainError: antes de ejecutar nada, si la carpeta de entradas no es válida o está
            alterada, falta SUMO, ``retry_of`` no es reintentable o no hay memoria o disco.
    """
    runs_root = workspace / RUNS
    limits = RunLimits()
    if wall_timeout_s is not None:
        limits = replace(limits, wall_timeout_s=wall_timeout_s)
    recovered = recover_interrupted(runs_root, clock=clock)
    result = run_inputs(
        inputs, runs_root, limits=limits, sumo=sumo, clock=clock, cancel=cancel, retry_of=retry_of
    )
    manifest = result.manifest
    status = manifest.status
    if status not in ("succeeded", "failed", "cancelled"):
        raise ValueError(f"una corrida publicada no puede estar {status!r}")
    run_folder = runs_root / manifest.run_id
    return RunReport(
        status=status,
        run_id=manifest.run_id,
        path=f"{RUNS}/{manifest.run_id}",
        retry_of=manifest.retry_of,
        scenario_id=manifest.scenario_id,
        error_code=None if manifest.error is None else manifest.error.code,
        error_message=None if manifest.error is None else manifest.error.message,
        timing=_timing(run_folder),
        summary=result.summary,
        conciliation=_conciliation(run_folder),
        recovered_interrupted=[item.folder for item in recovered],
        exit_code=exit_code_of(result),
    )
