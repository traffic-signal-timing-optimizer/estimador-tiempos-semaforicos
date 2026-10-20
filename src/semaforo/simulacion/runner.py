"""Runner mínimo de SUMO (decisión D3; adelanta el núcleo de DEV07).

Ejecuta la configuración intacta de una simulación sobre una copia, dentro de una carpeta de
ejecución de F5. SUMO se lanza con ``subprocess``, con lista de argumentos y sin shell (ADR04),
con un límite de tiempo simulado (``--end``, D4) y otro de tiempo real. Las salidas se dirigen a
``outputs/`` por línea de comandos, que tiene precedencia sobre el .sumocfg.

El éxito exige código de salida 0 y salidas coherentes (QA07). Si SUMO falla, se pasa del tiempo
o sus salidas no son coherentes, la ejecución se publica como ``failed`` con su motivo y sin
métricas (QA08). Una configuración con rutas absolutas no se ejecuta, porque SUMO escribiría fuera
de la carpeta de la corrida (QA10).
"""

import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import Element

from semaforo.caso.sumo_config import GUI_ONLY, read_config_references
from semaforo.caso.xml_input import integer, optional_number, parse_root
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.summary import (
    UNMET_DEMAND,
    FindingCode,
    Mode,
    SimulationFinding,
    SimulationSummary,
)
from semaforo.trazabilidad.manifest import Error, RunManifest
from semaforo.trazabilidad.paths import check_relative_path
from semaforo.trazabilidad.store import RunSpec, RunWriter, utc_now

# Límites provisionales, pendientes del piloto (D4).
END_S = 7200.0
WALL_TIMEOUT_S = 900.0
SMOKE_END_S = 60.0
VERSION_TIMEOUT_S = 30.0
MAX_CONFIG_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
VERSION_PATTERN = re.compile(r"^Eclipse SUMO \S+ (\S+)", re.MULTILINE)
DECLARED_OUTPUTS = "config"
STATISTICS = "statistics.xml"
TRIPINFO = "tripinfo.xml"
SUMMARY = "summary.json"
LOG = "sumo.log"
TOLERANCE = 1e-9
# SUMO 1.27.1 en Windows no abre una ruta de más de 257 caracteres (medido en F6). En otros
# sistemas no hay un límite práctico.
MAX_PATH_CHARS: int | None = 257 if os.name == "nt" else None
PLANNED_OUTPUTS = (f"outputs/{TRIPINFO}", f"outputs/{STATISTICS}", f"outputs/{LOG}")


class SimulacionError(DomainError):
    """Error del runner de SUMO."""


@dataclass(frozen=True)
class RunLimits:
    """Límites de una corrida, en segundos. Valores provisionales, pendientes del piloto (D4)."""

    end_s: float = END_S
    wall_timeout_s: float = WALL_TIMEOUT_S
    smoke_end_s: float = SMOKE_END_S
    max_path_chars: int | None = MAX_PATH_CHARS

    def __post_init__(self) -> None:
        if min(self.end_s, self.wall_timeout_s, self.smoke_end_s) <= 0:
            raise ValueError("los límites de la corrida deben ser positivos")
        if self.max_path_chars is not None and self.max_path_chars <= 0:
            raise ValueError("max_path_chars debe ser positivo")


@dataclass(frozen=True)
class SimulationResult:
    """Ejecución publicada y, si tuvo éxito, su resumen."""

    manifest: RunManifest
    summary: SimulationSummary | None


@dataclass(frozen=True)
class _Outcome:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool


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


def sumo_arguments(entry: str, end_s: float, gui_options: Sequence[str] = ()) -> list[str]:
    """Argumentos de SUMO, relativos a la carpeta de la ejecución (sin el ejecutable).

    Las opciones de archivo de ``<gui_only>`` (``gui_options``) se anulan con un valor vacío: no
    afectan a una corrida sin interfaz, pero SUMO exige que sus archivos existan y la copia de F2
    no incluye las vistas (ADR09).
    """
    neutralized = [item for option in gui_options for item in (f"--{option}", "")]
    return [
        *_base_arguments(entry, end_s),
        *neutralized,
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
) -> SimulationResult:
    """Ejecuta la simulación de ``source`` y publica la corrida en ``runs_root``.

    Args:
        source: carpeta de la simulación (normalmente la copia inmutable de F2). Solo se lee.
        entry_config: .sumocfg de entrada, relativo a ``source``.
        runs_root: carpeta de ejecuciones (``datos/ejecuciones``).
        spec: identificación de la corrida en el manifiesto.
        mode: ``base`` (hasta ``limits.end_s``) o ``smoke`` (hasta ``limits.smoke_end_s``).
        limits: límites de tiempo; si es None, los provisionales.
        sumo: ejecutable de SUMO; si es None, se busca con ``SUMO_HOME``.
        declared_vehicles: vehículos que declara la demanda (auditoría de F4), para comparar.
        clock: reloj con zona horaria, para la fecha del manifiesto.

    Raises:
        DomainError: antes de ejecutar nada, PATH_NOT_ALLOWED si la entrada sale de la carpeta,
            hay enlaces o el .sumocfg declara rutas absolutas; INPUT_SCHEMA si el .sumocfg no
            existe o no es válido; DEPENDENCY_MISSING si no se encuentra SUMO.
    """
    limits = limits or RunLimits()
    entry = _checked_entry(entry_config)
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
    binary = sumo or find_sumo()
    version = sumo_version(binary)
    end_s = limits.smoke_end_s if mode == "smoke" else limits.end_s
    gui_options = sorted({ref.option for ref in references.files if ref.section == GUI_ONLY})
    arguments = sumo_arguments(entry, end_s, gui_options=gui_options)
    command = ["sumo", *arguments]
    environment = {
        "sumo": version,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
    }
    with RunWriter(runs_root, spec, clock=clock) as writer:

        def failed(code: ErrorCode, message: str, exit_code: int | None) -> SimulationResult:
            error = Error(code=code.value, field=None, message=message)
            manifest = writer.publish(
                status="failed",
                command=command,
                environment=environment,
                exit_code=exit_code,
                error=error,
            )
            return SimulationResult(manifest=manifest, summary=None)

        for relative in files:
            writer.add_input(source / relative, relative)
        longest = _longest_path(writer.path, [*writer.input_paths, *PLANNED_OUTPUTS])
        if limits.max_path_chars is not None and longest > limits.max_path_chars:
            return failed(
                ErrorCode.PATH_NOT_ALLOWED,
                f"una ruta de la corrida tiene {longest} caracteres y SUMO admite hasta "
                f"{limits.max_path_chars}: use una carpeta de ejecuciones menos profunda",
                None,
            )
        outcome = _execute(binary, arguments, writer.path, limits.wall_timeout_s)
        writer.output_path("sumo.stdout.txt").write_bytes(outcome.stdout)
        writer.output_path("sumo.stderr.txt").write_bytes(outcome.stderr)
        _keep_declared_outputs(writer)
        if outcome.timed_out:
            return failed(
                ErrorCode.SIM_TIMEOUT,
                f"SUMO superó el límite de {_seconds(limits.wall_timeout_s)} s de tiempo real",
                None,
            )
        if outcome.returncode != 0:
            return failed(
                ErrorCode.SIM_FAILED,
                f"SUMO terminó con código {outcome.returncode}; detalle en outputs/sumo.stderr.txt",
                outcome.returncode,
            )
        try:
            summary = summarize_outputs(
                writer.path / "outputs",
                declared_vehicles,
                mode=mode,
                end_limit_s=end_s,
                sumo_version=version,
            )
        except DomainError as invalid:
            return failed(ErrorCode.OUTPUT_INVALID, invalid.message, outcome.returncode)
        writer.output_path(SUMMARY).write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        manifest = writer.publish(
            status="succeeded", command=command, environment=environment, exit_code=0
        )
        return SimulationResult(manifest=manifest, summary=summary)


def _checked_entry(entry_config: str) -> str:
    try:
        return check_relative_path(entry_config.strip().replace("\\", "/"))
    except ValueError as error:
        raise SimulacionError(ErrorCode.PATH_NOT_ALLOWED, str(error), "entry_config") from error


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


def _execute(binary: Path, arguments: list[str], cwd: Path, timeout_s: float) -> _Outcome:
    try:
        completed = subprocess.run(  # noqa: S603  (lista de argumentos, sin shell: ADR04)
            [str(binary), *arguments],
            cwd=cwd,
            capture_output=True,
            timeout=timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as expired:
        return _Outcome(None, _as_bytes(expired.stdout), _as_bytes(expired.stderr), timed_out=True)
    return _Outcome(completed.returncode, completed.stdout, completed.stderr, timed_out=False)


def _as_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value.encode("utf-8") if isinstance(value, str) else value


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


def summarize_outputs(
    folder: Path,
    declared_vehicles: float | None,
    *,
    mode: Mode = "base",
    end_limit_s: float | None = None,
    sumo_version: str | None = None,
) -> SimulationSummary:
    """Resume ``statistics.xml`` y ``tripinfo.xml`` de ``folder`` y comprueba que sean coherentes.

    Coherencia (acta de F1): hay un ``tripinfo`` por vehículo insertado, los no terminados
    (``arrival`` negativo) son los que siguen en la red y no se insertan más de los cargados.

    Raises:
        SimulacionError: OUTPUT_INVALID si falta un archivo, no es XML válido, le falta un dato
            o las cifras no son coherentes.
    """
    try:
        stats = parse_root(
            folder / STATISTICS, MAX_OUTPUT_BYTES, frozenset({"statistics"}), STATISTICS
        )
        trips = parse_root(folder / TRIPINFO, MAX_OUTPUT_BYTES, frozenset({"tripinfos"}), TRIPINFO)
        vehicles = _element(stats, "vehicles", STATISTICS)
        teleports = _element(stats, "teleports", STATISTICS)
        performance = stats.find("performance")
        safety = stats.find("safety")
        trip_stats = stats.find("vehicleTripStatistics")
        loaded, inserted = integer(vehicles, "loaded"), integer(vehicles, "inserted")
        running, waiting = integer(vehicles, "running"), integer(vehicles, "waiting")
        tripinfos = trips.findall("tripinfo")
        unfinished = sum(1 for trip in tripinfos if (optional_number(trip, "arrival") or 0) < 0)
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
    if len(tripinfos) != inserted:
        raise _invalid(f"hay {len(tripinfos)} viajes y {inserted} vehículos insertados", TRIPINFO)
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
        trips_finished=len(tripinfos) - unfinished,
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
