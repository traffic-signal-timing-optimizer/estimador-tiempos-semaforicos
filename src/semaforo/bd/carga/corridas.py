"""Unidad de una corrida de SUMO (DEV31 F3).

De ``datos/ejecuciones/<run_id>/`` y de sus métricas publicadas
(``datos/derivados/metricas/<caso>/<run_id>/``, DEV31 F2) salen ``simulacion.corridas``,
``resultados_corrida``, ``resultados_acceso``, ``resultados_movimiento``, ``vehiculos``,
``eventos`` y ``cola_por_acceso``, más su entorno (``control.entornos``) y su plan. La serie de
cola va en arreglos: los pasos y su marca de ventana en ``resultados_corrida``, y un arreglo de
vehículos por acceso en ``cola_por_acceso`` (cambio de DEV31 F4, aprobado por el PO).

- La carpeta se lee con su lector oficial (``read_run``: exactamente los archivos del manifiesto,
  cada uno con su huella) y cada archivo que da filas se vuelve a comprobar con los bytes que se
  usan. La FCD no se carga: se enlaza (B11).
- Las métricas se copian de ``metricas.json``; no se calculan aquí (B10). Una corrida exitosa sin
  métricas publicadas espera: no se carga a medias, porque después no se podría completar (B2).
- La etapa (búsqueda o finalistas), el protocolo y el plan de una corrida de búsqueda salen de la
  traza que la usó. Una corrida que ninguna búsqueda usa es de diagnóstico y solo se carga si la
  carga lo autoriza (``--sueltas``): así una corrida de una búsqueda todavía en curso no queda
  marcada para siempre como diagnóstico. Su plan sale de su programa derivado.
"""

import csv
import io
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element

from defusedxml.ElementTree import ParseError, iterparse
from pydantic import ValidationError

from semaforo.bd.carga import crudo
from semaforo.bd.carga.modelo import (
    DATA_ROOT,
    CargaError,
    FileRecord,
    Pending,
    Row,
    Unit,
    read_file,
    verified_record,
)
from semaforo.bd.carga.planes import add_plan
from semaforo.dominio.case import Case
from semaforo.dominio.errors import ErrorCode
from semaforo.evaluacion.cohort import DelaySummary
from semaforo.evaluacion.metrics import QueueSummary, StopsSummary
from semaforo.evaluacion.published_metrics import MANIFEST_FILE as METRICS_MANIFEST
from semaforo.evaluacion.published_metrics import (
    METRICS,
    METRICS_FILE,
    RUNS,
    protocol_fingerprint,
    read_run_metrics,
)
from semaforo.evaluacion.run_metrics import RunMetrics
from semaforo.simulacion.prepare import InputsManifest, canonical_json_sha256
from semaforo.simulacion.runner import FCD, FCD_GZ, LOG, SUMMARY, TIMING, TRIPINFO
from semaforo.simulacion.summary import RunTiming, SimulationSummary
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import INPUTS, MANIFEST, read_run

__all__ = [
    "COHORT",
    "METRIC_COLUMNS",
    "PROGRAMS",
    "ProgramFinder",
    "SearchRun",
    "cohort_rows",
    "delay_columns",
    "entorno_row",
    "log_events",
    "metric_columns",
    "metric_rows",
    "queue_columns",
    "run_unit",
    "stop_columns",
]

COHORT = "cohorte_conciliada.csv"
INPUTS_MANIFEST = f"{INPUTS}/manifiesto.json"
PROGRAM_COPY = f"{INPUTS}/programa.tll.xml"
PROGRAMS = "derivados/programas"
PROGRAM_MANIFEST = "manifiesto.json"
PROGRAM_SLOTS = "tramos.json"
YES = "sí"
NO = "no"
SUMO_MISSING = -1.0  # SUMO escribe -1 cuando un dato no existe (no llegó, no entró)
MAX_LOG_EVENTS = 100_000
COHORT_HEADER = [
    "vehicle_id",
    "movement_id",
    "vehicle_class",
    "en_cohorte",
    "depart_programada_s",
    "estado",
    "entrada_real_s",
    "llegada_s",
]
KINDS = {
    MANIFEST: "manifest",
    INPUTS_MANIFEST: "inputs_manifest",
    f"outputs/{TRIPINFO}": "tripinfo",
    f"outputs/{FCD}": "fcd",
    f"outputs/{FCD_GZ}": "fcd",
    f"outputs/{COHORT}": "cohort",
    "outputs/conciliacion.json": "reconciliation",
    f"outputs/{SUMMARY}": "summary",
    f"outputs/{TIMING}": "timing",
    f"outputs/{LOG}": "sumo_log",
}

# Busca la carpeta de ``derivados/programas/<caso>`` cuyo manifiesto tiene esta huella.
type ProgramFinder = Callable[[str, str], str | None]


@dataclass(frozen=True)
class SearchRun:
    """Lo que dice de una corrida la traza de la búsqueda que la usó."""

    search_id: str
    stage: str
    protocol_id: str
    seed: int
    durations_s: Mapping[str, float]


def _model[M](parse: Callable[[bytes], M], data: bytes, where: str) -> M:
    try:
        return parse(data)
    except ValidationError as error:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, f"no cumple su formato ({error.error_count()} problemas)", where
        ) from error


# --- entorno ---------------------------------------------------------------------------------

LOCATIONS = {"local": "local", "cloud": "nube"}


def entorno_row(environment: Mapping[str, str]) -> Row:
    """La fila de ``control.entornos`` de un manifiesto (sin ``artefacto_id``).

    Los nombres del manifiesto están en inglés (F2); la ubicación se traduce (``cloud`` es
    ``nube``). Lo que el manifiesto no registra queda vacío, nunca en cero.
    """
    commit = environment.get("commit")
    modified = environment.get("code_modified")
    cores = environment.get("cpu_cores")
    memory = environment.get("memory_gb")
    values: Row = {
        "version_sumo": environment.get("sumo"),
        "version_python": environment.get("python"),
        "sistema_operativo": environment.get("os"),
        "commit_codigo": commit,
        "codigo_modificado": None if modified is None else modified == "true",
        "motivo_sin_commit": None
        if commit
        else "no registrado: corrida anterior a DEV31 F2 o fuera de un repositorio git",
        "librerias": {},
        "ubicacion": LOCATIONS.get(environment.get("location", "")),
        "proveedor_nube": environment.get("cloud_provider"),
        "tipo_maquina": environment.get("machine_type"),
        "region": environment.get("region"),
        "procesador": environment.get("cpu"),
        "nucleos": None if cores is None else int(cores),
        "memoria_gb": None if memory is None else float(memory),
    }
    return {"entorno_id": canonical_json_sha256(values), **values}


# --- registro de SUMO ------------------------------------------------------------------------

_TELEPORT = re.compile(r"Teleporting vehicle '([^']*)'; waited too long \(([^)]*)\)")
_COLLISION = re.compile(r"collision with vehicle '([^']*)'")
_VEHICLE = re.compile(r"[Vv]ehicle '([^']*)'")
_LANE = re.compile(r"lane[= ]'([^']*)'")
_TIME = re.compile(r"time=(-?\d+(?:\.\d+)?)")
_STAGE = re.compile(r"stage=(\w+)")
CAUSES = {"jam": "jam", "yield": "yield", "wrong lane": "wrong_lane"}


def _event_kind(line: str) -> tuple[str, str | None] | None:
    if line.startswith("Error:"):
        return "error", None
    if not line.startswith("Warning:"):
        return None
    teleport = _TELEPORT.search(line)
    if teleport is not None:
        return "teleport", CAUSES.get(teleport[2], teleport[2])
    if _COLLISION.search(line) is not None:
        stage = _STAGE.search(line)
        return "collision", None if stage is None else stage[1]
    return "warning", None


def log_events(text: str) -> list[Row]:
    """Avisos, errores, teletransportes y choques del registro de SUMO, con su línea.

    Solo las líneas que empiezan con «Warning:» o «Error:»; el resto (carga de archivos) no es un
    evento. Cada fila guarda la línea tal cual.
    """
    events: list[Row] = []
    for number, line in enumerate(text.splitlines(), start=1):
        kind = _event_kind(line)
        if kind is None:
            continue
        vehicle = _VEHICLE.search(line)
        other = _COLLISION.search(line)
        lane = _LANE.search(line)
        moment = _TIME.search(line)
        events.append(
            {
                "orden": number,
                "tiempo_s": None if moment is None else float(moment[1]),
                "tipo": kind[0],
                "subtipo": kind[1],
                "vehiculo_id": None if vehicle is None else vehicle[1],
                "otro_vehiculo_id": None if other is None else other[1],
                "carril_id": None if lane is None else lane[1],
                "texto": line,
            }
        )
        if len(events) > MAX_LOG_EVENTS:
            raise CargaError(ErrorCode.INPUT_SCHEMA, "el registro tiene demasiados avisos", LOG)
    return events


# --- cohorte y viajes ------------------------------------------------------------------------


def _cell(text: str) -> str:
    """Texto de una celda protegida para Excel (``="M01"``) o normal."""
    if text.startswith('="') and text.endswith('"'):
        return text[2:-1]
    return text


def _optional(text: str, where: str) -> float | None:
    if text == "":
        return None
    try:
        return float(text)
    except ValueError as error:
        raise CargaError(ErrorCode.INPUT_SCHEMA, f"número no válido {text!r}", where) from error


def cohort_rows(data: bytes) -> list[Row]:
    """Filas de ``cohorte_conciliada.csv`` (la conciliación oficial de DEV19)."""
    where = f"outputs/{COHORT}"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "no está en UTF-8", where) from error
    reader = csv.reader(io.StringIO(text), delimiter=";")
    if next(reader, None) != COHORT_HEADER:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "la cabecera no es la esperada", where)
    rows: list[Row] = []
    for cells in reader:
        if len(cells) != len(COHORT_HEADER):
            raise CargaError(ErrorCode.INPUT_SCHEMA, "una fila no tiene 8 columnas", where)
        vehicle, movement, klass, cohort, scheduled, status, inserted, arrival = cells
        if cohort not in (YES, NO):
            raise CargaError(ErrorCode.INPUT_SCHEMA, f"en_cohorte no válido {cohort!r}", where)
        rows.append(
            {
                "vehiculo_id": _cell(vehicle),
                "movimiento_id": _cell(movement),
                "clase_id": _cell(klass),
                "en_cohorte": cohort == YES,
                "salida_programada_s": _optional(scheduled, where),
                "estado": status,
                "entrada_real_s": _optional(inserted, where),
                "llegada_s": _optional(arrival, where),
            }
        )
    return rows


TRIP_NUMBERS = {
    "departDelay": "demora_salida_s",
    "duration": "duracion_s",
    "routeLength": "recorrido_m",
    "waitingTime": "espera_s",
    "waitingCount": "esperas",
    "stopTime": "tiempo_detenido_s",
    "timeLoss": "perdida_tiempo_s",
    "speedFactor": "factor_velocidad",
}
TRIP_TEXTS = {"departLane": "carril_salida", "arrivalLane": "carril_llegada", "vType": "tipo_sumo"}
TRIP_COLUMNS = (*TRIP_NUMBERS.values(), *TRIP_TEXTS.values(), "vaporizado")


def _trip_number(value: str | None, where: str) -> float | None:
    if value is None or value == "":
        return None
    number = _optional(value, where)
    return None if number == SUMO_MISSING else number


def _trip(element: Element, where: str) -> Row:
    get = element.get
    row: Row = {column: _trip_number(get(name), where) for name, column in TRIP_NUMBERS.items()}
    for name, column in TRIP_TEXTS.items():
        value = get(name)
        row[column] = value if isinstance(value, str) and value else None
    vaporized = get("vaporized")
    row["vaporizado"] = None if vaporized is None else vaporized != ""
    return row


def _trips(data: bytes) -> dict[str, Row]:
    """Columnas de ``tripinfo.xml`` por vehículo, leído en flujo, sin DTD ni entidades."""
    where = f"outputs/{TRIPINFO}"
    trips: dict[str, Row] = {}
    depth = 0
    try:
        for event, element in iterparse(io.BytesIO(data), events=("start", "end"), forbid_dtd=True):
            if event == "start":
                depth += 1
                continue
            depth -= 1
            if depth == 1 and element.tag == "tripinfo":
                identifier = element.get("id")
                if not identifier or identifier in trips:
                    raise CargaError(ErrorCode.INPUT_SCHEMA, "viaje sin id o repetido", where)
                trips[identifier] = _trip(element, where)
            if depth == 1:
                element.clear()
    except ParseError as error:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "no es XML válido", where) from error
    return trips


# --- métricas --------------------------------------------------------------------------------


def delay_columns(summary: DelaySummary | None) -> Row:
    if summary is None:
        return {name: None for name in DELAY_COLUMNS}
    return {
        "solicitados": summary.requested,
        "terminados": summary.finished,
        "sin_terminar": summary.unfinished,
        "no_insertados": summary.not_inserted,
        "estado_demora": summary.status,
        "suma_demora_s": summary.sum_delay_s,
        "demora_media_s": summary.mean_delay_s,
        "perdida_tiempo_media_s": summary.mean_time_loss_s,
        "demora_salida_media_s": summary.mean_depart_delay_s,
        "cota_inf_demora_s": summary.lower_bound_mean_delay_s,
        "cota_inf_perdida_tiempo_s": summary.lower_bound_mean_time_loss_s,
        "cota_inf_demora_salida_s": summary.lower_bound_mean_depart_delay_s,
    }


def queue_columns(summary: QueueSummary | None) -> Row:
    if summary is None:
        return {name: None for name in QUEUE_COLUMNS}
    return {
        "estado_cola": summary.status,
        "ticks_esperados": summary.ticks_expected,
        "ticks_observados": summary.ticks_observed,
        "cobertura_cola": summary.coverage,
        "vehiculo_ticks": summary.vehicle_ticks,
        "cola_media_veh": summary.mean_vehicles,
        "cola_maxima_veh": summary.max_vehicles,
    }


def stop_columns(summary: StopsSummary | None) -> Row:
    if summary is None:
        return {name: None for name in STOPS_COLUMNS}
    return {
        "estado_detenciones": summary.status,
        "detenciones_solicitados": summary.requested,
        "detenciones_total": summary.total_stops,
        "detenciones_media": summary.mean_stops,
        "cota_inf_detenciones": summary.lower_bound_mean_stops,
    }


DELAY_COLUMNS = (
    "solicitados",
    "terminados",
    "sin_terminar",
    "no_insertados",
    "estado_demora",
    "suma_demora_s",
    "demora_media_s",
    "perdida_tiempo_media_s",
    "demora_salida_media_s",
    "cota_inf_demora_s",
    "cota_inf_perdida_tiempo_s",
    "cota_inf_demora_salida_s",
)
QUEUE_COLUMNS = (
    "estado_cola",
    "ticks_esperados",
    "ticks_observados",
    "cobertura_cola",
    "vehiculo_ticks",
    "cola_media_veh",
    "cola_maxima_veh",
)
STOPS_COLUMNS = (
    "estado_detenciones",
    "detenciones_solicitados",
    "detenciones_total",
    "detenciones_media",
    "cota_inf_detenciones",
)
METRIC_COLUMNS = (
    "version_metricas",
    "protocolo_metricas_id",
    "estado_protocolo_metricas",
    "definicion_demora",
    "origen_caso",
    "origen_demanda",
    "origen_evidencia",
    "cohorte_solicitada",
    "cohorte_terminada",
    "cohorte_sin_terminar",
    "cohorte_no_insertada",
    "estado_demora",
    "suma_demora_s",
    "demora_media_s",
    "perdida_tiempo_media_s",
    "demora_salida_media_cohorte_s",
    "cota_inf_demora_s",
    "cota_inf_perdida_tiempo_s",
    "cota_inf_demora_salida_s",
    "vehiculos_calentamiento",
    "zona_disponible",
    "motivo_zona_no_disponible",
    "carriles_zona",
    "umbral_cola_mps",
    "umbral_detencion_mps",
    "muestreo_cola_s",
    "inicio_medicion_s",
    "fin_medicion_s",
    *QUEUE_COLUMNS,
    *STOPS_COLUMNS,
    "pasos_fcd",
    "pasos_cola_s",
    "pasos_en_ventana",
)


def metric_columns(metrics: RunMetrics | None) -> Row:
    """Columnas de ``resultados_corrida`` que salen de ``metricas.json`` (vacías si no hay)."""
    if metrics is None:
        return {name: None for name in METRIC_COLUMNS}
    total = metrics.cohort.total
    zone = metrics.zone
    settings = None if zone is None else zone.settings
    series = None if zone is None else zone.queue_series
    return {
        "version_metricas": metrics.schema_version,
        "protocolo_metricas_id": metrics.protocol_id,
        "estado_protocolo_metricas": metrics.protocol_status,
        "definicion_demora": metrics.delay_definition,
        "origen_caso": metrics.case_origin,
        "origen_demanda": metrics.demand_origin,
        "origen_evidencia": metrics.evidence_origin,
        "cohorte_solicitada": total.requested,
        "cohorte_terminada": total.finished,
        "cohorte_sin_terminar": total.unfinished,
        "cohorte_no_insertada": total.not_inserted,
        "estado_demora": total.status,
        "suma_demora_s": total.sum_delay_s,
        "demora_media_s": total.mean_delay_s,
        "perdida_tiempo_media_s": total.mean_time_loss_s,
        "demora_salida_media_cohorte_s": total.mean_depart_delay_s,
        "cota_inf_demora_s": total.lower_bound_mean_delay_s,
        "cota_inf_perdida_tiempo_s": total.lower_bound_mean_time_loss_s,
        "cota_inf_demora_salida_s": total.lower_bound_mean_depart_delay_s,
        "vehiculos_calentamiento": metrics.cohort.warmup_vehicles,
        "zona_disponible": zone is not None,
        "motivo_zona_no_disponible": metrics.zone_unavailable,
        "carriles_zona": None if settings is None else list(settings.zone_lane_ids),
        "umbral_cola_mps": None if settings is None else settings.queue_speed_threshold_mps,
        "umbral_detencion_mps": None if settings is None else settings.stop_speed_threshold_mps,
        "muestreo_cola_s": None if settings is None else settings.queue_sampling_s,
        "inicio_medicion_s": None if settings is None else settings.measure_start_s,
        "fin_medicion_s": None if settings is None else settings.measure_end_s,
        **queue_columns(None if zone is None else zone.queue),
        **stop_columns(None if zone is None else zone.stops),
        "pasos_fcd": None if zone is None else zone.fcd_steps,
        "pasos_cola_s": None if series is None else list(series.times_s),
        "pasos_en_ventana": None if series is None else list(series.in_window),
    }


def metric_rows(unit: Unit, run_id: str, metrics: RunMetrics, source: FileRecord) -> None:
    """Resultados por acceso y por movimiento, y la cola paso a paso."""
    zone = metrics.zone
    queues = {} if zone is None else zone.queue_by_access
    stops = {} if zone is None else zone.stops_by_access
    for access in sorted(set(metrics.cohort.by_access) | set(queues) | set(stops)):
        summary = metrics.cohort.by_access.get(access)
        unit.add(
            "simulacion.resultados_acceso",
            {
                "run_id": run_id,
                "acceso": access,
                "con_cohorte": summary is not None,
                **delay_columns(summary),
                **queue_columns(queues.get(access)),
                **stop_columns(stops.get(access)),
            },
            source,
        )
    for movement, summary in sorted(metrics.cohort.by_movement.items()):
        unit.add(
            "simulacion.resultados_movimiento",
            {
                "run_id": run_id,
                "caso_id": metrics.case_id,
                "caso_version": metrics.case_version,
                "movimiento_id": movement,
                **delay_columns(summary),
            },
            source,
        )
    series = None if zone is None else zone.queue_series
    if series is None:
        return
    steps = len(series.times_s)
    if len(series.in_window) != steps:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA, "la ventana de la cola no tiene un valor por paso", METRICS_FILE
        )
    for access, counts in sorted(series.vehicles_by_access.items()):
        if len(counts) != steps:
            raise CargaError(
                ErrorCode.INPUT_SCHEMA,
                f"la cola del acceso {access} no tiene un valor por paso",
                METRICS_FILE,
            )
        unit.add(
            "simulacion.cola_por_acceso",
            {"run_id": run_id, "acceso": access, "vehiculos_en_cola": list(counts)},
            source,
        )


# --- la carpeta ------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Folder:
    """La carpeta de la corrida, ya verificada, con un lector de archivos por su huella."""

    workspace: Path
    run_id: str
    manifest: RunManifest
    hashes: dict[str, str]

    @property
    def base(self) -> str:
        return f"{RUNS}/{self.run_id}"

    @property
    def manifest_id(self) -> str:
        return f"{DATA_ROOT}:{self.base}/{MANIFEST}"

    def has(self, name: str) -> bool:
        return name in self.hashes

    def read(self, name: str) -> tuple[FileRecord, bytes]:
        return read_file(
            self.workspace,
            DATA_ROOT,
            f"{self.base}/{name}",
            KINDS.get(name, "other"),
            expected=self.hashes[name],
            manifest=self.manifest_id,
        )

    def record(self, name: str) -> FileRecord:
        return verified_record(
            self.workspace,
            DATA_ROOT,
            f"{self.base}/{name}",
            KINDS.get(name, "other"),
            self.hashes[name],
            self.manifest_id,
        )


@dataclass(frozen=True)
class _Measured:
    """Las métricas publicadas de la corrida, con sus dos archivos."""

    metrics: RunMetrics
    manifest: FileRecord
    data: FileRecord
    protocol_sha256: str | None


def _measured(workspace: Path, case_id: str, run_id: str, run_sha: str) -> _Measured | None:
    folder = workspace / METRICS / case_id / run_id
    if not folder.exists():
        return None
    stored = read_run_metrics(folder)
    if stored.manifest.protocol_sha256 is not None:
        current = protocol_fingerprint(workspace, stored.metrics.protocol_id)
        if current != stored.manifest.protocol_sha256:
            raise CargaError(
                ErrorCode.HASH_MISMATCH,
                "la huella del protocolo de las métricas es distinta",
                f"{METRICS}/{run_id}",
            )
    if stored.manifest.run_manifest_sha256 != run_sha:
        raise CargaError(
            ErrorCode.HASH_MISMATCH, "las métricas no son de esta corrida", f"{METRICS}/{run_id}"
        )
    base = f"{METRICS}/{case_id}/{run_id}"
    manifest, _ = read_file(workspace, DATA_ROOT, f"{base}/{METRICS_MANIFEST}", "manifest")
    data = verified_record(
        workspace,
        DATA_ROOT,
        f"{base}/{METRICS_FILE}",
        "metrics",
        stored.manifest.files[METRICS_FILE],
        manifest.artifact_id,
    )
    return _Measured(stored.metrics, manifest, data, stored.manifest.protocol_sha256)


def _program_plan(
    unit: Unit, workspace: Path, case: Case, inputs: InputsManifest, programs: ProgramFinder
) -> str | None:
    """El plan de una corrida suelta, del ``tramos.json`` de su programa derivado (o None)."""
    folder = programs(inputs.case_id, inputs.program.source_manifest_sha256)
    if folder is None:
        return None
    manifest, data = read_file(workspace, DATA_ROOT, f"{folder}/{PROGRAM_MANIFEST}", "manifest")
    if manifest.sha256 != inputs.program.source_manifest_sha256:
        raise CargaError(ErrorCode.HASH_MISMATCH, "el programa cambió", folder)
    raw_files = crudo.mapping(crudo.mapping(crudo.loads(data, folder), folder).get("files"), folder)
    files = {name: crudo.text(digest, folder) for name, digest in raw_files.items()}
    slots, raw = read_file(
        workspace,
        DATA_ROOT,
        f"{folder}/{PROGRAM_SLOTS}",
        "other",
        expected=files.get(PROGRAM_SLOTS),
        manifest=manifest.artifact_id,
    )
    unit.add_file(manifest)
    unit.add_file(slots)
    for name, digest in sorted(files.items()):
        if name != PROGRAM_SLOTS:
            unit.add_file(
                verified_record(
                    workspace, DATA_ROOT, f"{folder}/{name}", "other", digest, manifest.artifact_id
                )
            )
    content = crudo.mapping(crudo.loads(raw, slots.relative), slots.relative)
    durations = {
        crudo.text(slot.get("id"), slots.relative): crudo.number(
            slot.get("duration_s"), slots.relative
        )
        for slot in (
            crudo.mapping(item, slots.relative)
            for item in crudo.items(content.get("slots"), slots.relative)
        )
    }
    cycle = crudo.optional_number(content.get("cycle_s"), slots.relative)
    return add_plan(unit, case, durations, slots, cycle_s=cycle)


def _open(workspace: Path, run_id: str) -> tuple[_Folder, FileRecord]:
    """La carpeta verificada y el registro de su manifiesto, leído una sola vez."""
    manifest = read_run(workspace / RUNS, run_id)
    hashes = {a.path: a.sha256 for a in (*manifest.inputs, *manifest.outputs)}
    folder = _Folder(workspace, run_id, manifest, hashes)
    record, data = read_file(workspace, DATA_ROOT, f"{folder.base}/{MANIFEST}", "manifest")
    if RunManifest.model_validate_json(data) != manifest:
        raise CargaError(ErrorCode.HASH_MISMATCH, "el manifiesto cambió mientras se leía", run_id)
    if manifest.scenario_id is None or not folder.has(INPUTS_MANIFEST):
        raise CargaError(
            ErrorCode.INPUT_SCHEMA,
            "la corrida no tiene escenario ni entradas de DEV06: no es cargable",
            run_id,
        )
    return folder, record


def _needs(unit: Unit, manifest: RunManifest, protocol: str | None) -> None:
    unit.need(
        "experimento.escenarios",
        {"escenario_id": manifest.scenario_id},
        f"falta el escenario {manifest.scenario_id}",
    )
    if protocol is not None:
        unit.need(
            "experimento.protocolos", {"protocolo_id": protocol}, f"falta el protocolo {protocol}"
        )
    if manifest.retry_of is not None:
        unit.need(
            "simulacion.corridas",
            {"run_id": manifest.retry_of},
            f"falta la corrida anterior {manifest.retry_of}",
        )


def _run_row(  # noqa: PLR0913, PLR0917  (cada argumento es una fuente de la fila)
    folder: _Folder,
    inputs: InputsManifest,
    inputs_sha: str,
    timing: RunTiming | None,
    stage: str,
    protocol: str | None,
    plan: str | None,
    entorno_id: object,
) -> Row:
    manifest = folder.manifest
    times = inputs.times
    return {
        "run_id": folder.run_id,
        "estado": manifest.status,
        "creada_en": manifest.created_at,
        "caso_id": manifest.case_id,
        "caso_version": manifest.case_version,
        "escenario_id": manifest.scenario_id,
        "etapa": stage,
        "semilla_sumo": manifest.seed,
        "semilla_demanda": inputs.seeds.demand_seed,
        "protocolo_id": protocol,
        "plan_id": plan,
        "programa_id": inputs.program.program_id,
        "tls_id": inputs.program.tls_id,
        "red_sha256": inputs.network.sha256,
        "programa_sha256": inputs.program.sha256,
        "rutas_sha256": inputs.routes_sha256,
        "tipos_sha256": inputs.vehicle_types_sha256,
        "entradas_sha256": inputs_sha,
        "politica_frontera": inputs.boundary_policy_id,
        "paso_s": times.step_length_s,
        "calentamiento_s": times.warmup_s,
        "medicion_s": times.measure_s,
        "vaciado_max_s": times.drain_max_s,
        "fin_s": times.end_s,
        "inicio_cohorte_s": times.cohort_start_s,
        "fin_cohorte_s": times.cohort_end_s,
        "vehiculos_total": inputs.vehicles.total,
        "vehiculos_cohorte": inputs.vehicles.cohort,
        "vehiculos_calentamiento": inputs.vehicles.warmup,
        "opciones_sumo": dict(inputs.sumo_options),
        "limitaciones": list(inputs.limitations),
        "comando": list(manifest.command),
        "entorno_id": entorno_id,
        "codigo_salida": manifest.exit_code,
        "error": None if manifest.error is None else manifest.error.model_dump(mode="json"),
        "reintento_de": manifest.retry_of,
        "terminacion": None if timing is None else timing.termination,
        "inicio_ejecucion": None if timing is None else timing.started_at,
        "fin_ejecucion": None if timing is None else timing.finished_at,
        "duracion_s": None if timing is None else timing.duration_s,
        "limite_tiempo_s": None if timing is None else timing.wall_timeout_s,
        "memoria_pico_bytes": None if timing is None else timing.peak_memory_bytes,
        "bytes_salida": None if timing is None else timing.output_bytes,
    }


def _results_row(summary: SimulationSummary, measured: _Measured | None, run_id: str) -> Row:
    return {
        "run_id": run_id,
        "artefacto_metricas_id": None if measured is None else measured.data.artifact_id,
        "modo": summary.mode,
        "fin_limite_s": summary.end_limit_s,
        "fin_simulado_s": summary.simulated_end_s,
        "vehiculos_declarados": summary.declared_vehicles,
        "vehiculos_cargados": summary.vehicles_loaded,
        "vehiculos_insertados": summary.vehicles_inserted,
        "vehiculos_en_red": summary.vehicles_running,
        "vehiculos_esperando": summary.vehicles_waiting,
        "viajes_terminados": summary.trips_finished,
        "viajes_sin_terminar": summary.trips_unfinished,
        "teletransportes_total": summary.teleports_total,
        "teletransportes_atasco": summary.teleports_jam,
        "teletransportes_cruce": summary.teleports_yield,
        "teletransportes_carril": summary.teleports_wrong_lane,
        "choques": summary.collisions,
        "avisos_sumo": summary.sumo_warnings,
        "demora_salida_media_s": summary.mean_depart_delay_s,
        "demanda_insatisfecha": summary.demand_unmet,
        "hallazgos": [f.model_dump(mode="json") for f in summary.findings],
        **metric_columns(None if measured is None else measured.metrics),
    }


def _vehicles(unit: Unit, folder: _Folder, metrics: RunMetrics | None) -> None:
    manifest = folder.manifest
    cohort_record, cohort_bytes = folder.read(f"outputs/{COHORT}")
    _, trip_bytes = folder.read(f"outputs/{TRIPINFO}")
    trips = _trips(trip_bytes)
    delays = {} if metrics is None else {v.vehicle_id: v for v in metrics.cohort.vehicles}
    zone = None if metrics is None else metrics.zone
    stops = {} if zone is None else zone.vehicle_stops
    no_trip: Row = {name: None for name in TRIP_COLUMNS}
    for row in cohort_rows(cohort_bytes):
        vehicle = str(row["vehiculo_id"])
        delay = delays.get(vehicle)
        counted = delay is not None and zone is not None
        unit.add(
            "simulacion.vehiculos",
            {
                "run_id": folder.run_id,
                "caso_id": manifest.case_id,
                "caso_version": manifest.case_version,
                **row,
                **trips.get(vehicle, no_trip),
                "acceso": None if delay is None else delay.access_id,
                "perdida_tiempo_cohorte_s": None if delay is None else delay.time_loss_s,
                "demora_salida_cohorte_s": None if delay is None else delay.depart_delay_s,
                "fuente_demora_salida": None if delay is None else delay.depart_delay_source,
                "detenciones": stops.get(vehicle) if counted else None,
            },
            cohort_record,
        )


def _outcomes(unit: Unit, folder: _Folder, measured: _Measured | None) -> None:
    """Lo que sale de una corrida exitosa: resultados, vehículos y, con métricas, el resto."""
    manifest = folder.manifest
    if measured is not None:
        metrics = measured.metrics
        if metrics.scenario_id != manifest.scenario_id or metrics.sumo_seed != manifest.seed:
            raise CargaError(
                ErrorCode.INPUT_SCHEMA, "las métricas no son de esta corrida", folder.run_id
            )
        unit.add_file(measured.manifest)
        unit.add_file(measured.data)
    record, data = folder.read(f"outputs/{SUMMARY}")
    summary = _model(SimulationSummary.model_validate_json, data, SUMMARY)
    if summary.end_limit_s is None:
        raise CargaError(ErrorCode.INPUT_SCHEMA, "el resumen no dice el fin previsto", SUMMARY)
    unit.add(
        "simulacion.resultados_corrida", _results_row(summary, measured, folder.run_id), record
    )
    _vehicles(unit, folder, None if measured is None else measured.metrics)
    if measured is not None:
        metric_rows(unit, folder.run_id, measured.metrics, measured.data)


def run_unit(  # noqa: PLR0912, PLR0913  (la corrida reúne todas las fuentes)
    workspace: Path,
    run_id: str,
    cases: Mapping[tuple[str, str], Case],
    searches: Mapping[str, SearchRun],
    programs: ProgramFinder,
    *,
    diagnostics: bool,
    require_metrics: bool = True,
) -> Unit:
    """La unidad de la corrida ``run_id``.

    Raises:
        Pending: si falta algo que se publica aparte (sus métricas, su caso, o la búsqueda que la
            usó si no se autorizan corridas sueltas).
        CargaError o DomainError: si la carpeta no es cargable (alterada, sin escenario o sin
            entradas de DEV06).
    """
    folder, manifest_record = _open(workspace, run_id)
    manifest = folder.manifest
    case = cases.get((manifest.case_id, manifest.case_version))
    if case is None:
        raise Pending(f"falta el caso {manifest.case_id} {manifest.case_version}")
    search = searches.get(run_id)
    if search is None and not diagnostics:
        raise Pending("ninguna búsqueda publicada la usa (se carga como suelta con --sueltas)")
    measured = _measured(workspace, manifest.case_id, run_id, manifest_record.sha256)
    if manifest.status == "succeeded" and measured is None and require_metrics:
        raise Pending(
            "faltan sus métricas publicadas (derivados/metricas); sin ellas, --sin-metricas"
        )
    unit = Unit(key=f"corrida:{run_id}", kind="run")
    if measured is not None and measured.protocol_sha256 is None:
        unit.notes.append("métricas de manifiesto 1.0.0: sin huella de protocolo registrada")
    unit.add_file(manifest_record)
    inputs_record, inputs_bytes = folder.read(INPUTS_MANIFEST)
    inputs = _model(InputsManifest.model_validate_json, inputs_bytes, INPUTS_MANIFEST)
    unit.add_file(inputs_record)
    for name in sorted(folder.hashes):
        if name != INPUTS_MANIFEST:
            unit.add_file(folder.record(name))
    environment = entorno_row(manifest.environment)
    unit.add("control.entornos", environment, manifest_record)
    if search is not None:
        if manifest.seed != search.seed:
            raise CargaError(
                ErrorCode.INPUT_SCHEMA, "la semilla no es la que registró la búsqueda", run_id
            )
        program = next(f for f in unit.files if f.relative == f"{folder.base}/{PROGRAM_COPY}")
        plan = add_plan(unit, case, search.durations_s, program)
        stage, protocol = search.stage, search.protocol_id
    else:
        plan = _program_plan(unit, workspace, case, inputs, programs)
        stage, protocol = "diagnostic", manifest.protocol_id
    _needs(unit, manifest, protocol)
    if measured is not None and protocol is not None and measured.metrics.protocol_id != protocol:
        raise CargaError(
            ErrorCode.INPUT_SCHEMA,
            "el protocolo de las métricas no es el de la corrida y su búsqueda",
            run_id,
        )
    timing: RunTiming | None = None
    if folder.has(f"outputs/{TIMING}"):
        _, timing_bytes = folder.read(f"outputs/{TIMING}")
        timing = _model(RunTiming.model_validate_json, timing_bytes, TIMING)
    row = _run_row(
        folder,
        inputs,
        inputs_record.sha256,
        timing,
        stage,
        protocol,
        plan,
        environment["entorno_id"],
    )
    unit.add("simulacion.corridas", row, manifest_record)
    if folder.has(f"outputs/{LOG}"):
        log_record, log_bytes = folder.read(f"outputs/{LOG}")
        for event in log_events(log_bytes.decode("utf-8", errors="replace")):
            unit.add("simulacion.eventos", {"run_id": run_id, **event}, log_record)
    if manifest.status == "succeeded":
        _outcomes(unit, folder, measured)
    return unit
