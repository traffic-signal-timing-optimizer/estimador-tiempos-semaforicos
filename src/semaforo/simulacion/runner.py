"""Runner de SUMO (decisión D3 de DEV00, ampliado en DEV07 F2).

Ejecuta la configuración intacta de una simulación sobre una copia, dentro de una carpeta de
ejecución de F5. SUMO se lanza como proceso controlado (``process.run_controlled``): lista de
argumentos y sin shell (ADR04), con un límite de tiempo simulado (``--end``, D4) y uno de tiempo
real, y vigilado hasta el final: se puede cancelar y tiene topes de salidas y de memoria. Las
salidas se dirigen a ``outputs/`` por línea de comandos, que tiene precedencia sobre el .sumocfg.

El éxito exige código de salida 0 y salidas coherentes (QA07). Si SUMO falla, se pasa del tiempo
o de un tope, o sus salidas no son coherentes, la ejecución se publica como ``failed`` con su
motivo y sin métricas (QA08); si se cancela, como ``cancelled``. Toda ejecución publicada lleva
``outputs/tiempos.json`` con su duración y por qué terminó. Con una zona de medición (ADR11, DEV19)
SUMO escribe además los viajes que nunca entraron y la FCD de la zona. Una configuración con rutas
absolutas no se ejecuta, porque SUMO escribiría fuera de la carpeta de la corrida (QA10).
"""

import os
import platform
import re
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import Element

from semaforo.caso.sumo_config import GUI_ONLY, read_config_references
from semaforo.caso.xml_input import integer, optional_number, parse_root
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.process import ProcessLimits, ProcessOutcome, run_controlled, tree_bytes
from semaforo.simulacion.resources import available_memory_bytes, free_disk_bytes
from semaforo.simulacion.summary import (
    UNMET_DEMAND,
    FindingCode,
    Mode,
    RunTiming,
    SimulationFinding,
    SimulationSummary,
)
from semaforo.simulacion.tripinfo import read_trips
from semaforo.trazabilidad.interrupted import recover_interrupted
from semaforo.trazabilidad.manifest import Error, RunManifest
from semaforo.trazabilidad.paths import check_relative_path
from semaforo.trazabilidad.retry import check_retry
from semaforo.trazabilidad.store import RunSpec, RunWriter, utc_now

# Límites provisionales, pendientes del piloto (D4).
END_S = 7200.0
WALL_TIMEOUT_S = 900.0
SMOKE_END_S = 60.0
VERSION_TIMEOUT_S = 30.0
MAX_CONFIG_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
# Topes de una corrida (DEV07 F0, D6 y D19). Provisionales: medidos con el caso real, que usa
# 35 MB de memoria, escribe 0,85 MB y tarda unos 8 s, así que tienen más de 100 veces de margen.
MAX_RUN_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_MEMORY_BYTES = 4 * 1024**3
MIN_FREE_MEMORY_BYTES = 1024**3
POLL_S = 0.25
MIB = 1024 * 1024
VERSION_PATTERN = re.compile(r"^Eclipse SUMO \S+ (\S+)", re.MULTILINE)
DECLARED_OUTPUTS = "config"
STATISTICS = "statistics.xml"
TRIPINFO = "tripinfo.xml"
SUMMARY = "summary.json"
TIMING = "tiempos.json"
LOG = "sumo.log"
FCD = "fcd.xml"
# Lo que la evaluación necesita de cada vehículo en cada paso (ADR11).
FCD_ATTRIBUTES = "id,lane,speed"
TOLERANCE = 1e-9
# SUMO 1.27.1 en Windows no abre una ruta de más de 257 caracteres (medido en F6). En otros
# sistemas no hay un límite práctico.
MAX_PATH_CHARS: int | None = 257 if os.name == "nt" else None
PLANNED_OUTPUTS = (
    f"outputs/{TRIPINFO}",
    f"outputs/{STATISTICS}",
    f"outputs/{LOG}",
    f"outputs/{FCD}",
)


class SimulacionError(DomainError):
    """Error del runner de SUMO."""


@dataclass(frozen=True)
class RunLimits:
    """Límites de una corrida. Valores provisionales, pendientes del piloto (D4, D6 y D19).

    Los tiempos van en segundos y los topes en bytes. ``min_free_memory_bytes`` es la memoria
    disponible que se exige antes de empezar.
    """

    end_s: float = END_S
    wall_timeout_s: float = WALL_TIMEOUT_S
    smoke_end_s: float = SMOKE_END_S
    max_path_chars: int | None = MAX_PATH_CHARS
    max_output_bytes: int = MAX_RUN_OUTPUT_BYTES
    max_log_bytes: int = MAX_LOG_BYTES
    max_memory_bytes: int = MAX_MEMORY_BYTES
    min_free_memory_bytes: int = MIN_FREE_MEMORY_BYTES
    poll_s: float = POLL_S

    def __post_init__(self) -> None:
        positive = (
            self.end_s,
            self.wall_timeout_s,
            self.smoke_end_s,
            self.max_output_bytes,
            self.max_log_bytes,
            self.max_memory_bytes,
            self.poll_s,
        )
        if min(positive) <= 0:
            raise ValueError("los límites de la corrida deben ser positivos")
        if self.max_path_chars is not None and self.max_path_chars <= 0:
            raise ValueError("max_path_chars debe ser positivo")
        if self.min_free_memory_bytes < 0:
            raise ValueError("min_free_memory_bytes no puede ser negativo")

    def process_limits(self) -> ProcessLimits:
        """Los topes que vigila el proceso controlado."""
        return ProcessLimits(
            wall_timeout_s=self.wall_timeout_s,
            max_output_bytes=self.max_output_bytes,
            max_log_bytes=self.max_log_bytes,
            max_memory_bytes=self.max_memory_bytes,
            poll_s=self.poll_s,
        )


@dataclass(frozen=True)
class SimulationResult:
    """Ejecución publicada y, si tuvo éxito, su resumen."""

    manifest: RunManifest
    summary: SimulationSummary | None


def find_sumo(environment: Mapping[str, str] | None = None) -> Path:
    """Ejecutable de SUMO a partir de ``SUMO_HOME`` (con o sin barra final).

    Raises:
        SimulacionError: DEPENDENCY_MISSING si ``SUMO_HOME`` falta o no contiene ``bin/sumo``.
    """
    home = (os.environ if environment is None else environment).get("SUMO_HOME", "").strip()
    if home:
        for name in ("sumo.exe", "sumo"):
            candidate = Path(home) / "bin" / name  # pathlib descarta la barra final
            if candidate.is_file():
                return candidate
    raise SimulacionError(
        ErrorCode.DEPENDENCY_MISSING, "no se encuentra SUMO: revise SUMO_HOME", "SUMO_HOME"
    )


def parse_sumo_version(text: str) -> str:
    """Versión de la primera línea de ``sumo --version`` (``Eclipse SUMO sumo 1.27.1``)."""
    match = VERSION_PATTERN.search(text)
    if match is None:
        raise SimulacionError(
            ErrorCode.DEPENDENCY_MISSING, "no se reconoce la versión de SUMO", "sumo --version"
        )
    return match.group(1)


def sumo_version(binary: Path) -> str:
    """Versión del ejecutable ``binary``."""
    try:
        completed = subprocess.run(  # noqa: S603  (lista de argumentos fija, sin shell)
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SimulacionError(
            ErrorCode.DEPENDENCY_MISSING,
            f"no se pudo ejecutar SUMO ({type(error).__name__})",
            "sumo --version",
        ) from error
    return parse_sumo_version(completed.stdout)


def _seconds(value: float) -> str:
    return f"{value:g}"


def sumo_arguments(
    entry: str,
    end_s: float,
    gui_options: Sequence[str] = (),
    zone_file: str | None = None,
) -> list[str]:
    """Argumentos de SUMO, relativos a la carpeta de la ejecución (sin el ejecutable).

    Las opciones de archivo de ``<gui_only>`` (``gui_options``) se anulan con un valor vacío: no
    afectan a una corrida sin interfaz, pero SUMO exige que sus archivos existan y la copia de F2
    no incluye las vistas (ADR09). ``zone_file`` (relativo a las entradas) es la lista de calles
    de la zona de medición: con él se piden los viajes no iniciados y la FCD de la zona (ADR11).
    """
    neutralized = [item for option in gui_options for item in (f"--{option}", "")]
    measurement = [] if zone_file is None else _measurement_arguments(zone_file)
    return [
        *_base_arguments(entry, end_s),
        *measurement,
        *neutralized,
    ]


def _measurement_arguments(zone_file: str) -> list[str]:
    return [
        "--tripinfo-output.write-undeparted",
        "true",
        "--fcd-output",
        f"outputs/{FCD}",
        "--fcd-output.filter-edges.input-file",
        f"inputs/{zone_file}",
        "--fcd-output.attributes",
        FCD_ATTRIBUTES,
    ]


def _base_arguments(entry: str, end_s: float) -> list[str]:
    return [
        "-c",
        f"inputs/{entry}",
        "--end",
        _seconds(end_s),
        "--tripinfo-output",
        f"outputs/{TRIPINFO}",
        "--tripinfo-output.write-unfinished",
        "true",
        "--statistic-output",
        f"outputs/{STATISTICS}",
        "--duration-log.statistics",
        "true",
        "--no-step-log",
        "true",
        "--log",
        "outputs/" + LOG,
    ]


@dataclass(frozen=True)
class _Plan:
    """Lo que se decide antes de crear la corrida: nada de esto escribe en disco."""

    entry: str
    zone_file: str | None
    files: list[str]
    binary: Path
    arguments: list[str]
    command: list[str]
    environment: dict[str, str]
    end_s: float
    input_bytes: int


def _plan(  # noqa: PLR0913  (todo lo que define la corrida)
    source: Path,
    entry_config: str,
    mode: Mode,
    limits: RunLimits,
    sumo: Path | None,
    *,
    zone_file: str | None,
) -> _Plan:
    """Comprueba la entrada y arma el comando. Raises: ver ``run_simulation``."""
    entry = _checked_entry(entry_config)
    zone = None if zone_file is None else _checked_entry(zone_file, "zone_file")
    if not (source / entry).is_file():
        raise SimulacionError(
            ErrorCode.INPUT_SCHEMA, "no existe el .sumocfg de entrada", "entry_config"
        )
    references = read_config_references(source / entry, MAX_CONFIG_BYTES)
    if references.absolute_paths:
        raise SimulacionError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el .sumocfg declara rutas absolutas: SUMO escribiría fuera de la corrida",
            references.absolute_paths[0].option,
        )
    files = _source_files(source)
    if zone is not None and zone not in files:
        raise SimulacionError(
            ErrorCode.INPUT_SCHEMA, "no existe el archivo de la zona de medición", "zone_file"
        )
    binary = sumo or find_sumo()
    version = sumo_version(binary)
    end_s = limits.smoke_end_s if mode == "smoke" else limits.end_s
    gui_options = sorted({ref.option for ref in references.files if ref.section == GUI_ONLY})
    arguments = sumo_arguments(entry, end_s, gui_options=gui_options, zone_file=zone)
    return _Plan(
        entry=entry,
        zone_file=zone,
        files=files,
        binary=binary,
        arguments=arguments,
        command=["sumo", *arguments],
        environment={
            "sumo": version,
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
        },
        end_s=end_s,
        input_bytes=sum((source / relative).stat().st_size for relative in files),
    )


def _check_resources(runs_root: Path, input_bytes: int, limits: RunLimits) -> None:
    """Exige espacio en disco y memoria antes de crear la corrida (DEV07 F0, D6 y D19).

    Raises:
        SimulacionError: SIM_FAILED si no hay espacio para el tope de salidas más el doble de las
            entradas, o si la memoria disponible es menor que ``min_free_memory_bytes``.
    """
    needed = limits.max_output_bytes + 2 * input_bytes
    free = free_disk_bytes(runs_root)
    if free < needed:
        raise SimulacionError(
            ErrorCode.SIM_FAILED,
            f"no hay espacio para la corrida: hacen falta {needed // MIB} MiB libres y quedan "
            f"{free // MIB} MiB",
            "runs_root",
        )
    available = available_memory_bytes()
    if available is not None and available < limits.min_free_memory_bytes:
        raise SimulacionError(
            ErrorCode.SIM_FAILED,
            f"no hay memoria para la corrida: hacen falta {limits.min_free_memory_bytes // MIB} "
            f"MiB disponibles y quedan {available // MIB} MiB; cierre programas e intente de nuevo",
            "memory",
        )


class _Execution:
    """Una corrida en curso: sabe publicarse como exitosa, fallida o cancelada."""

    def __init__(
        self,
        writer: RunWriter,
        plan: _Plan,
        limits: RunLimits,
        clock: Callable[[], datetime],
    ) -> None:
        self._writer = writer
        self._plan = plan
        self._limits = limits
        self._clock = clock
        self._started_at = clock()

    def _write_timing(self, outcome: ProcessOutcome | None) -> None:
        timing = RunTiming(
            started_at=self._started_at,
            finished_at=self._clock(),
            duration_s=0.0 if outcome is None else outcome.duration_s,
            wall_timeout_s=self._limits.wall_timeout_s,
            end_s=self._plan.end_s,
            termination="not_started" if outcome is None else outcome.cause,
            peak_memory_bytes=None if outcome is None else outcome.peak_memory_bytes,
            output_bytes=0 if outcome is None else outcome.output_bytes,
        )
        self._writer.output_path(TIMING).write_text(timing.model_dump_json(indent=2), "utf-8")

    def fail(
        self,
        code: ErrorCode,
        message: str,
        exit_code: int | None,
        outcome: ProcessOutcome | None = None,
    ) -> SimulationResult:
        """Publica la corrida como ``failed`` con su motivo y sin métricas."""
        self._write_timing(outcome)
        error = Error(code=code.value, field=None, message=message)
        manifest = self._writer.publish(
            status="failed",
            command=self._plan.command,
            environment=self._plan.environment,
            exit_code=exit_code,
            error=error,
        )
        return SimulationResult(manifest=manifest, summary=None)

    def cancel(self, outcome: ProcessOutcome) -> SimulationResult:
        """Publica la corrida como ``cancelled``, con sus registros y sin métricas."""
        self._write_timing(outcome)
        manifest = self._writer.publish(
            status="cancelled",
            command=self._plan.command,
            environment=self._plan.environment,
            exit_code=None,
        )
        return SimulationResult(manifest=manifest, summary=None)

    def succeed(
        self, summary: SimulationSummary, extra: Mapping[str, bytes], outcome: ProcessOutcome
    ) -> SimulationResult:
        """Publica la corrida como ``succeeded`` con su resumen y las salidas del paso final."""
        self._write_timing(outcome)
        for name, data in extra.items():
            self._writer.output_path(name).write_bytes(data)
        self._writer.output_path(SUMMARY).write_text(summary.model_dump_json(indent=2), "utf-8")
        manifest = self._writer.publish(
            status="succeeded",
            command=self._plan.command,
            environment=self._plan.environment,
            exit_code=0,
        )
        return SimulationResult(manifest=manifest, summary=summary)

    def stopped(self, outcome: ProcessOutcome) -> SimulationResult | None:
        """La corrida publicada si el proceso no terminó bien; ``None`` si terminó con código 0."""
        detail = outcome.detail or ""
        match outcome.cause:
            case "cancelled":
                return self.cancel(outcome)
            case "timeout":
                return self.fail(ErrorCode.SIM_TIMEOUT, detail, None, outcome)
            case "output_budget" | "memory_budget":
                return self.fail(ErrorCode.SIM_FAILED, detail, None, outcome)
            case "sumo_error":
                message = (
                    f"SUMO terminó con código {outcome.returncode}; "
                    "detalle en outputs/sumo.stderr.txt"
                )
                return self.fail(ErrorCode.SIM_FAILED, message, outcome.returncode, outcome)
            case _:
                return None


def _launch(
    writer: RunWriter, plan: _Plan, limits: RunLimits, cancel: threading.Event | None
) -> ProcessOutcome:
    """Lanza SUMO como proceso controlado dentro de la carpeta de la corrida."""
    stdout = writer.output_path("sumo.stdout.txt")
    stderr = writer.output_path("sumo.stderr.txt")
    return run_controlled(
        [str(plan.binary), *plan.arguments],
        cwd=writer.path,
        stdout_path=stdout,
        stderr_path=stderr,
        watched=writer.path,
        baseline_bytes=tree_bytes(writer.path),
        logs=[stdout, stderr, writer.path / "outputs" / LOG],
        limits=limits.process_limits(),
        cancel=cancel,
    )


def run_simulation(  # noqa: PLR0913  (los argumentos opcionales son de solo palabra clave)
    source: Path,
    entry_config: str,
    runs_root: Path,
    spec: RunSpec,
    *,
    mode: Mode = "base",
    limits: RunLimits | None = None,
    sumo: Path | None = None,
    declared_vehicles: float | None = None,
    clock: Callable[[], datetime] = utc_now,
    finalize: Callable[[Path], Mapping[str, bytes]] | None = None,
    cancel: threading.Event | None = None,
    zone_file: str | None = None,
) -> SimulationResult:
    """Ejecuta la simulación de ``source`` y publica la corrida en ``runs_root``.

    Args:
        source: carpeta de la simulación (normalmente la copia inmutable de F2). Solo se lee.
        entry_config: .sumocfg de entrada, relativo a ``source``.
        runs_root: carpeta de ejecuciones (``datos/ejecuciones``).
        spec: identificación de la corrida en el manifiesto.
        mode: ``base`` (hasta ``limits.end_s``) o ``smoke`` (hasta ``limits.smoke_end_s``).
        limits: límites de tiempo, salidas y memoria; si es None, los provisionales.
        sumo: ejecutable de SUMO; si es None, se busca con ``SUMO_HOME``.
        declared_vehicles: vehículos que declara la demanda (auditoría de F4), para comparar.
        clock: reloj con zona horaria, para la fecha del manifiesto y de ``tiempos.json``.
        finalize: paso previo a publicar una corrida exitosa (DEV07 F1). Recibe la carpeta de la
            corrida (``inputs/`` y ``outputs/``) y devuelve archivos para agregar a ``outputs/``,
            que no pueden reemplazar a ninguno existente. Si lanza ``DomainError``, la corrida se
            publica ``failed`` con OUTPUT_INVALID y sin métricas.
        cancel: evento que, al activarse, cancela la corrida: SUMO se termina, se conservan sus
            registros y salidas parciales y la corrida se publica ``cancelled``. Ctrl+C en la
            consola hace lo mismo. Una corrida cancelada no lanza excepción: se devuelve publicada.
        zone_file: archivo de ``source`` con las calles de la zona de medición (``edge:<id>``
            por línea). Con él SUMO escribe también los viajes no iniciados y ``outputs/fcd.xml``
            de esas calles, y la corrida solo es exitosa si están (ADR11).

    Antes de empezar aparta las corridas interrumpidas de ``runs_root`` (``recover_interrupted``) y,
    si ``spec.retry_of`` está, comprueba que sea una corrida reintentable (``check_retry``).

    Raises:
        DomainError: antes de ejecutar nada, PATH_NOT_ALLOWED si la entrada sale de la carpeta,
            hay enlaces o el .sumocfg declara rutas absolutas; INPUT_SCHEMA si el .sumocfg no
            existe o no es válido, o si ``retry_of`` no es una corrida reintentable;
            DEPENDENCY_MISSING si no se encuentra SUMO; SIM_FAILED si no hay espacio en disco o
            memoria disponible para la corrida.
    """
    limits = limits or RunLimits()
    recover_interrupted(runs_root, clock=clock)  # aparta las corridas caídas; no borra nada
    check_retry(runs_root, spec)
    plan = _plan(source, entry_config, mode, limits, sumo, zone_file=zone_file)
    _check_resources(runs_root, plan.input_bytes, limits)
    with RunWriter(runs_root, spec, clock=clock) as writer:
        run = _Execution(writer, plan, limits, clock)
        for relative in plan.files:
            writer.add_input(source / relative, relative)
        longest = _longest_path(writer.path, [*writer.input_paths, *PLANNED_OUTPUTS])
        if limits.max_path_chars is not None and longest > limits.max_path_chars:
            return run.fail(
                ErrorCode.PATH_NOT_ALLOWED,
                f"una ruta de la corrida tiene {longest} caracteres y SUMO admite hasta "
                f"{limits.max_path_chars}: use una carpeta de ejecuciones menos profunda",
                None,
            )
        outcome = _launch(writer, plan, limits, cancel)
        _keep_declared_outputs(writer)
        stopped = run.stopped(outcome)
        if stopped is not None:
            return stopped
        try:
            summary = summarize_outputs(
                writer.path / "outputs",
                declared_vehicles,
                mode=mode,
                end_limit_s=plan.end_s,
                sumo_version=plan.environment["sumo"],
                measured=plan.zone_file is not None,
            )
        except DomainError as invalid:
            return run.fail(ErrorCode.OUTPUT_INVALID, invalid.message, outcome.returncode, outcome)
        extra, problem = _final_outputs(finalize, writer)
        if problem is not None:
            return run.fail(ErrorCode.OUTPUT_INVALID, problem, outcome.returncode, outcome)
        return run.succeed(summary, extra, outcome)


def _final_outputs(
    finalize: Callable[[Path], Mapping[str, bytes]] | None, writer: RunWriter
) -> tuple[Mapping[str, bytes], str | None]:
    """Archivos del paso final y, si falló, su motivo."""
    if finalize is None:
        return {}, None
    try:
        extra = finalize(writer.path)
    except DomainError as invalid:
        return {}, invalid.message
    taken = [name for name in extra if name == SUMMARY or writer.output_path(name).exists()]
    if taken:
        return {}, f"el paso final quiso reemplazar la salida {taken[0]}"
    return extra, None


def _checked_entry(entry_config: str, field: str = "entry_config") -> str:
    try:
        return check_relative_path(entry_config.strip().replace("\\", "/"))
    except ValueError as error:
        raise SimulacionError(ErrorCode.PATH_NOT_ALLOWED, str(error), field) from error


def _source_files(source: Path) -> list[str]:
    """Archivos de ``source`` por ruta relativa con ``/``. Rechaza enlaces y uniones."""
    if not source.is_dir():
        raise SimulacionError(ErrorCode.INPUT_SCHEMA, "la carpeta de origen no existe", "source")
    files: list[str] = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        if path.is_symlink() or path.is_junction():
            raise SimulacionError(
                ErrorCode.PATH_NOT_ALLOWED, "no se admiten enlaces ni uniones", relative
            )
        if path.is_file():
            files.append(relative)
    return files


def _longest_path(folder: Path, relatives: Iterable[str]) -> int:
    """Longitud de la ruta absoluta más larga que SUMO usará dentro de ``folder``."""
    base = len(str(folder.resolve()))
    return max((base + 1 + len(relative) for relative in relatives), default=base)


def _keep_declared_outputs(writer: RunWriter) -> None:
    """Mueve a ``outputs/config/`` lo que el .sumocfg escribió junto a sus entradas.

    Las salidas que declara el .sumocfg con rutas relativas se escriben en ``inputs/``, junto a
    él. Se conservan como salidas para que la ejecución quede completa y verificable.
    """
    inputs = writer.path / "inputs"
    for path in sorted(inputs.rglob("*")):
        relative = path.relative_to(writer.path).as_posix()
        if path.is_file() and relative not in writer.input_paths:
            target = writer.output_path(f"{DECLARED_OUTPUTS}/{path.relative_to(inputs).as_posix()}")
            shutil.move(path, target)


def _element(root: Element, tag: str, what: str) -> Element:
    found = root.find(tag)
    if found is None:
        raise SimulacionError(ErrorCode.OUTPUT_INVALID, f"{what}: falta <{tag}>", tag)
    return found


def _invalid(message: str, field: str) -> SimulacionError:
    return SimulacionError(ErrorCode.OUTPUT_INVALID, message, field)


def summarize_outputs(  # noqa: PLR0913  (los opcionales son de solo palabra clave)
    folder: Path,
    declared_vehicles: float | None,
    *,
    mode: Mode = "base",
    end_limit_s: float | None = None,
    sumo_version: str | None = None,
    measured: bool = False,
) -> SimulationSummary:
    """Resume ``statistics.xml`` y ``tripinfo.xml`` de ``folder`` y comprueba que sean coherentes.

    Coherencia (acta de F1): hay un ``tripinfo`` por vehículo insertado, los no terminados
    (``arrival`` negativo) son los que siguen en la red y no se insertan más de los cargados.
    Con ``measured`` (ADR11) hay además un registro por vehículo que esperaba entrar
    (``depart`` -1) y existe ``fcd.xml``; sin él no puede haber ninguno de esos registros.

    Raises:
        SimulacionError: OUTPUT_INVALID si falta un archivo, no es XML válido, le falta un dato
            o las cifras no son coherentes.
    """
    try:
        stats = parse_root(
            folder / STATISTICS, MAX_OUTPUT_BYTES, frozenset({"statistics"}), STATISTICS
        )
        trips = read_trips(folder / TRIPINFO, MAX_OUTPUT_BYTES)
        vehicles = _element(stats, "vehicles", STATISTICS)
        teleports = _element(stats, "teleports", STATISTICS)
        performance = stats.find("performance")
        safety = stats.find("safety")
        trip_stats = stats.find("vehicleTripStatistics")
        loaded, inserted = integer(vehicles, "loaded"), integer(vehicles, "inserted")
        running, waiting = integer(vehicles, "running"), integer(vehicles, "waiting")
        undeparted = sum(1 for trip in trips.values() if not trip.started)
        started = len(trips) - undeparted
        unfinished = sum(1 for trip in trips.values() if trip.started and (trip.arrival or 0) < 0)
        counts = {
            "teleports_total": integer(teleports, "total"),
            "teleports_jam": integer(teleports, "jam"),
            "teleports_yield": integer(teleports, "yield"),
            "teleports_wrong_lane": integer(teleports, "wrongLane"),
            "collisions": 0 if safety is None else integer(safety, "collisions"),
            "sumo_warnings": _count_warnings(folder / LOG),
        }
        simulated_end = None if performance is None else optional_number(performance, "end")
        depart_delay = None if trip_stats is None else optional_number(trip_stats, "departDelay")
    except SimulacionError:
        raise
    except DomainError as error:
        raise _invalid(error.message, error.field or STATISTICS) from error
    if inserted > loaded:
        raise _invalid(f"se insertaron {inserted} vehículos de {loaded} cargados", "vehicles")
    if started != inserted:
        raise _invalid(f"hay {started} viajes y {inserted} vehículos insertados", TRIPINFO)
    if undeparted != (waiting if measured else 0):
        raise _invalid(
            f"hay {undeparted} viajes que no entraron y {waiting} vehículos esperando para entrar",
            TRIPINFO,
        )
    if measured and not (folder / FCD).is_file():
        raise _invalid(f"falta {FCD}", FCD)
    if unfinished != running:
        raise _invalid(
            f"hay {unfinished} viajes sin terminar y {running} vehículos en la red", TRIPINFO
        )
    findings = _findings(declared_vehicles, loaded, waiting, running, counts)
    return SimulationSummary(
        mode=mode,
        end_limit_s=end_limit_s,
        sumo_version=sumo_version,
        simulated_end_s=simulated_end,
        vehicles_loaded=loaded,
        vehicles_inserted=inserted,
        vehicles_running=running,
        vehicles_waiting=waiting,
        trips_finished=started - unfinished,
        trips_unfinished=unfinished,
        mean_depart_delay_s=depart_delay,
        declared_vehicles=declared_vehicles,
        demand_unmet=any(finding.code in UNMET_DEMAND for finding in findings),
        findings=findings,
        teleports_total=counts["teleports_total"],
        teleports_jam=counts["teleports_jam"],
        teleports_yield=counts["teleports_yield"],
        teleports_wrong_lane=counts["teleports_wrong_lane"],
        collisions=counts["collisions"],
        sumo_warnings=counts["sumo_warnings"],
    )


def _count_warnings(log: Path) -> int:
    """Avisos (``Warning:``) del registro de SUMO; 0 si no hay registro."""
    if not log.is_file():
        return 0
    with log.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.startswith("Warning:"))


def _findings(
    declared: float | None, loaded: int, waiting: int, running: int, counts: dict[str, int]
) -> list[SimulationFinding]:
    found: list[tuple[FindingCode, str]] = []
    if declared is not None and loaded < declared - TOLERANCE:
        found.append(
            (
                "LOADED_BELOW_DECLARED",
                f"SUMO cargó {loaded} de {declared:g} vehículos declarados: terminó antes",
            )
        )
    if waiting > 0:
        found.append(("DEMAND_NOT_INSERTED", f"{waiting} vehículos nunca entraron a la red"))
    if running > 0:
        found.append(("VEHICLES_STILL_RUNNING", f"{running} vehículos seguían en la red al final"))
    if counts["teleports_total"] > 0:
        found.append(("TELEPORTS", f"{counts['teleports_total']} teletransportes"))
    if counts["collisions"] > 0:
        found.append(("COLLISIONS", f"{counts['collisions']} colisiones"))
    if counts["sumo_warnings"] > 0:
        found.append(
            ("SUMO_WARNINGS", f"{counts['sumo_warnings']} avisos de SUMO; ver outputs/{LOG}")
        )
    return [SimulationFinding(code=code, message=message) for code, message in found]
