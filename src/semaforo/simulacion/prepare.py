"""Entradas de SUMO de una corrida aislada (DEV06 F2, HU04; decisiones D1 a D4 y D10 a D19).

Junta el caso, su red, el escenario, las rutas, los tipos de vehículo y el programa derivado de
DEV03 en una carpeta autosuficiente, lista para ``run_simulation``::

    <root>/<scenario_id>/<AAAAMMDDTHHMMSSZ>_<huella-corta>/
        escenario.sumocfg    configuración de SUMO (entrada de la corrida)
        red.net.xml[.gz]     copia de la red del caso, verificada por su huella
        demanda.rou.xml      tipos, rutas y vehículos uno por uno, ordenados por salida
        programa.tll.xml     programa derivado, copiado tal cual
        cohorte.csv          un vehículo por fila, con su huella (formato de planilla del equipo)
        manifiesto.json      huellas, semillas, tiempos, conteos y salidas requeridas

La carpeta se publica de una vez y nunca se sobrescribe. No ejecuta SUMO (D2): las salidas
``tripinfo`` (con vehículos inconclusos) y ``statistics`` las fija el corredor por línea de
comandos y el manifiesto las declara como requeridas. El fin de la simulación está en la
configuración y en el manifiesto; quien ejecute debe tomarlo de ahí.

Ajustes de F2 frente a F0: se admiten dos políticas de frontera equivalentes en esta etapa (red
vacía al inicio y rutas fijas), la del ejemplo sintético y la del caso real; el carril de salida
es el del movimiento solo si la ruta empieza en su calle de entrada, y si no, SUMO elige el mejor
(``best``); con varios carriles de entrada se reparten en orden.
"""

import csv
import io
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from pydantic import ValidationError

from semaforo.caso.case_network import verified_network_path
from semaforo.caso.errors import CasoError
from semaforo.caso.movements import MAX_NET_BYTES
from semaforo.caso.network_graph import NetworkGraph, read_network_graph
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case, CaseIssue, canonical_sha256
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import Scenario
from semaforo.simulacion.cohort import MAX_VEHICLES, Cohort, generate_cohort
from semaforo.simulacion.compiler import ProgramManifest
from semaforo.simulacion.demand_inputs import (
    NUMERIC_ATTRIBUTES,
    DemandInputError,
    RouteTable,
    VehicleType,
    VehicleTypes,
    approach_edge,
    route_issues,
    type_issues,
)
from semaforo.trazabilidad.fs import publish_files, read_at_most
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.ids import content_id
from semaforo.trazabilidad.store import utc_now

__all__ = [
    "ALLOWED_BOUNDARY_POLICIES",
    "CONFIG_FILE",
    "MAX_DEMAND_BYTES",
    "REQUIRED_OUTPUTS",
    "SUMO_OPTIONS",
    "InputsManifest",
    "PreparationRequest",
    "PreparedInputs",
    "build_inputs",
    "publish_inputs",
]

CONFIG_FILE = "escenario.sumocfg"
DEMAND_FILE = "demanda.rou.xml"
PROGRAM_FILE = "programa.tll.xml"
COHORT_FILE = "cohorte.csv"
MANIFEST_FILE = "manifiesto.json"
PROGRAM_MANIFEST_FILE = "manifiesto.json"
NETWORK_FILE = "red.net.xml"
GZIP_MAGIC = b"\x1f\x8b"
MAX_DEMAND_BYTES = 64 * 1024 * 1024
MAX_SUMO_SEED = 2**31 - 1
SHORT_HASH_CHARS = 8
SAFE_FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Los vehículos entran a la red a la mayor velocidad segura, como en la simulación del equipo.
DEPART_SPEED = "max"
XML_HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n'
CSV_DELIMITER = ";"
# Red vacía al inicio y rutas fijas, sin recalcularlas (D11, ajustada en F2).
ALLOWED_BOUNDARY_POLICIES = frozenset({"DEMO_EMPTY_START_FIXED_ROUTES", "sin-semaforos-vecinos"})
# Opciones de SUMO admitidas (D14) y el tipo de su valor.
SUMO_OPTIONS: Mapping[str, type] = {"lateral-resolution": float, "collision.check-junctions": bool}
REQUIRED_OUTPUTS = ("tripinfo-output", "tripinfo-output.write-unfinished", "statistic-output")
LIMITATIONS = (
    "El carril de salida es la intención del vehículo: SUMO puede cambiarlo antes del cruce, "
    "así que el carril con que cruza la línea de parada no está garantizado (D4).",
    "Los vehículos entran a la mayor velocidad segura (departSpeed=max), como en la simulación "
    "del equipo; con red vacía al inicio no traen la cola de calles anteriores.",
    "Un solo tipo de vehículo por clase del caso: no se representan subtipos (por ejemplo, "
    "camiones ligeros y medianos).",
)
COHORT_HEADER = [
    "vehicle_id",
    "movement_id",
    "vehicle_class",
    "vtype",
    "route_id",
    "depart_s",
    "depart_lane",
    "en_cohorte",
    "sha256_fila",
]


@dataclass(frozen=True)
class PreparationRequest:
    """Todo lo que hace falta para preparar una corrida.

    ``case_dir`` es la carpeta del caso, donde está su red. ``program_dir`` es la carpeta
    publicada del programa derivado (``publish_program``). ``sumo_seed`` es None para usar la
    semilla de la demanda (D12).
    """

    case: Case
    case_dir: Path
    scenario: Scenario
    routes: RouteTable
    vehicle_types: VehicleTypes
    program_dir: Path
    sumo_seed: int | None = None
    sumo_options: Mapping[str, float | bool] = field(default_factory=dict[str, float | bool])
    max_vehicles: int = MAX_VEHICLES


class FileRecord(FrozenModel):
    """Un archivo de entrada y su huella."""

    file: str
    sha256: str


class ProgramRecord(FrozenModel):
    """El programa derivado copiado y de dónde viene."""

    file: str
    sha256: str
    program_id: str
    tls_id: str
    source_manifest_sha256: str


class Seeds(FrozenModel):
    demand_seed: int
    sumo_seed: int


class Times(FrozenModel):
    """Tiempos de la corrida, en segundos desde el inicio. La cohorte sale en [inicio, fin)."""

    step_length_s: float
    begin_s: float
    warmup_s: float
    measure_s: float
    drain_max_s: float
    end_s: float
    cohort_start_s: float
    cohort_end_s: float


class CountRecord(FrozenModel):
    movement_id: str
    vehicle_class: str
    warmup: int
    measured: int


class Vehicles(FrozenModel):
    total: int
    cohort: int
    warmup: int
    counts: list[CountRecord]


class InputsManifest(FrozenModel):
    """Manifiesto de las entradas de una corrida (D18)."""

    schema_version: str = "1.0.0"
    created_at: str
    scenario_id: str
    scenario_sha256: str
    case_id: str
    case_version: str
    case_sha256: str
    boundary_policy_id: str
    entry_config: str
    network: FileRecord
    program: ProgramRecord
    routes_sha256: str
    vehicle_types_sha256: str
    route_sha256: dict[str, str]
    depart_lanes: dict[str, str]
    seeds: Seeds
    times: Times
    vehicles: Vehicles
    required_outputs: list[str]
    sumo_options: dict[str, float | bool]
    limitations: list[str]
    files: dict[str, str]


@dataclass(frozen=True)
class PreparedInputs:
    """Entradas listas para publicar: los archivos, su manifiesto y la cohorte."""

    folder_key: str
    files: dict[str, bytes]
    manifest: InputsManifest
    cohort: Cohort


def _error(code: ErrorCode, message: str, field_name: str | None = None) -> DemandInputError:
    return DemandInputError(code, message, field_name)


def _invalid(issues: list[CaseIssue]) -> DemandInputError:
    first = issues[0]
    extra = f" (y {len(issues) - 1} más)" if len(issues) > 1 else ""
    where = "" if first.field is None else f" en {first.field}"
    return DemandInputError(
        ErrorCode.INPUT_SCHEMA,
        f"no se pueden preparar las entradas: {first.rule_id}{where}: {first.message}{extra}",
        first.field,
        tuple(issues),
    )


def build_inputs(request: PreparationRequest, created_at: datetime) -> PreparedInputs:
    """Arma los archivos de la corrida sin escribir nada.

    Raises:
        ScenarioInvalidError: si el escenario no encaja con el caso.
        CohortError: si la cohorte tiene nombres inseguros o demasiados vehículos.
        DemandInputError: INPUT_SCHEMA si la política de frontera, las opciones, la semilla, las
            rutas o los tipos no sirven, o la demanda supera su tamaño máximo; HASH_MISMATCH si
            el programa derivado no corresponde al caso o su archivo no tiene su huella.
        CasoError: si la red no está en la carpeta del caso, falta o no tiene su huella.
    """
    case, scenario = request.case, request.scenario
    _check_policy(scenario)
    options = _checked_options(request.sumo_options)
    sumo_seed = scenario.demand_seed if request.sumo_seed is None else request.sumo_seed
    if not 0 <= sumo_seed <= MAX_SUMO_SEED:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"la semilla de SUMO debe estar entre 0 y {MAX_SUMO_SEED}",
            "sumo_seed",
        )
    cohort = generate_cohort(scenario, case, request.max_vehicles)
    network_name, network_bytes, graph = _network(case, request.case_dir)
    classes: dict[str, set[str]] = {}
    for vehicle in cohort.vehicles:
        classes.setdefault(vehicle.movement_id, set()).add(vehicle.vehicle_class)
    issues = type_issues(request.vehicle_types, case)
    issues += route_issues(
        request.routes,
        case,
        graph,
        {movement: frozenset(names) for movement, names in classes.items()},
        request.vehicle_types,
    )
    if issues:
        raise _invalid(issues)
    program_bytes, program = _program(request.program_dir, case)
    lanes = _depart_lanes(case, request.routes, graph, set(classes))
    demand, assigned = _demand_xml(cohort, request.routes, request.vehicle_types, lanes)
    if len(demand) > MAX_DEMAND_BYTES:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"la demanda ocupa {len(demand)} bytes y el máximo es {MAX_DEMAND_BYTES}",
            "scenario",
        )
    times = _times(case, scenario)
    files = {
        CONFIG_FILE: _config_xml(network_name, times, sumo_seed, options),
        network_name: network_bytes,
        DEMAND_FILE: demand,
        PROGRAM_FILE: program_bytes,
        COHORT_FILE: _cohort_csv(cohort, request.routes, request.vehicle_types, assigned),
    }
    hashes = {name: sha256_bytes(data) for name, data in files.items()}
    moment = created_at.astimezone(UTC)
    manifest = InputsManifest(
        created_at=moment.isoformat(),
        scenario_id=scenario.scenario_id,
        scenario_sha256=_canonical_sha256(scenario.model_dump(mode="json")),
        case_id=case.case_id,
        case_version=case.case_version,
        case_sha256=canonical_sha256(case),
        boundary_policy_id=scenario.boundary_policy_id,
        entry_config=CONFIG_FILE,
        network=FileRecord(file=network_name, sha256=hashes[network_name]),
        program=program,
        routes_sha256=_canonical_sha256(request.routes.model_dump(mode="json")),
        vehicle_types_sha256=_canonical_sha256(request.vehicle_types.model_dump(mode="json")),
        route_sha256={
            movement: sha256_bytes(" ".join(request.routes.routes[movement]).encode("utf-8"))
            for movement in sorted(classes)
        },
        depart_lanes={movement: lanes[movement].label for movement in sorted(classes)},
        seeds=Seeds(demand_seed=scenario.demand_seed, sumo_seed=sumo_seed),
        times=times,
        vehicles=Vehicles(
            total=len(cohort.vehicles),
            cohort=len(cohort.measured),
            warmup=len(cohort.vehicles) - len(cohort.measured),
            counts=[
                CountRecord(
                    movement_id=count.movement_id,
                    vehicle_class=count.vehicle_class,
                    warmup=count.warmup,
                    measured=count.measured,
                )
                for count in cohort.counts
            ],
        ),
        required_outputs=list(REQUIRED_OUTPUTS),
        sumo_options=dict(options),
        limitations=list(LIMITATIONS),
        files=hashes,
    )
    short = content_id(hashes.items())[:SHORT_HASH_CHARS]
    files[MANIFEST_FILE] = (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
    return PreparedInputs(f"{moment:%Y%m%dT%H%M%SZ}_{short}", files, manifest, cohort)


def publish_inputs(root: Path, request: PreparationRequest, now: datetime | None = None) -> Path:
    """Publica las entradas en ``root/<scenario_id>/<fecha>_<huella>/`` y devuelve esa carpeta.

    Raises:
        DemandInputError: PATH_NOT_ALLOWED si el ID del escenario no sirve como nombre de
            carpeta; RUN_EXISTS si la carpeta ya existe. Además, los errores de ``build_inputs``.
    """
    scenario_id = request.scenario.scenario_id
    if SAFE_FOLDER_NAME.fullmatch(scenario_id) is None:
        raise _error(
            ErrorCode.PATH_NOT_ALLOWED,
            "el ID del escenario solo puede llevar letras, números, punto, guion y guion bajo "
            "para usarse como nombre de carpeta",
            "scenario_id",
        )
    prepared = build_inputs(request, utc_now() if now is None else now)
    final = root / scenario_id / prepared.folder_key
    try:
        publish_files(final, prepared.files)
    except FileExistsError as error:
        raise _error(
            ErrorCode.RUN_EXISTS, "ya existe una carpeta con esas entradas", "root"
        ) from error
    return final


def _check_policy(scenario: Scenario) -> None:
    if scenario.boundary_policy_id not in ALLOWED_BOUNDARY_POLICIES:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"la política de frontera «{scenario.boundary_policy_id}» no está admitida; "
            f"se admiten: {', '.join(sorted(ALLOWED_BOUNDARY_POLICIES))}",
            "boundary_policy_id",
        )


def _checked_options(options: Mapping[str, float | bool]) -> dict[str, float | bool]:
    checked: dict[str, float | bool] = {}
    for name, value in options.items():
        kind = SUMO_OPTIONS.get(name)
        if kind is None:
            raise _error(
                ErrorCode.INPUT_SCHEMA,
                f"la opción de SUMO «{name}» no está admitida; "
                f"se admiten: {', '.join(sorted(SUMO_OPTIONS))}",
                f"sumo_options.{name}",
            )
        if kind is bool:
            if not isinstance(value, bool):
                raise _error(
                    ErrorCode.INPUT_SCHEMA, "debe ser verdadero o falso", f"sumo_options.{name}"
                )
        elif isinstance(value, bool) or not value > 0 or value == float("inf"):
            raise _error(
                ErrorCode.INPUT_SCHEMA, "debe ser un número mayor que 0", f"sumo_options.{name}"
            )
        checked[name] = value
    return checked


def _network(case: Case, case_dir: Path) -> tuple[str, bytes, NetworkGraph]:
    """Nombre de la copia, contenido verificado y grafo de la red del caso."""
    if case.network is None:
        raise _error(ErrorCode.INPUT_SCHEMA, "el caso no declara su red", "network")
    path = verified_network_path(case.network, case_dir)
    try:
        with path.open("rb") as handle:
            data = read_at_most(handle, MAX_NET_BYTES + 1)
    except OSError as error:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA, f"no se pudo leer la red ({type(error).__name__})", "network"
        ) from error
    if len(data) > MAX_NET_BYTES:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA, f"la red supera el límite de {MAX_NET_BYTES} bytes", "network"
        )
    if sha256_bytes(data) != case.network.sha256:
        raise CasoError(
            ErrorCode.HASH_MISMATCH,
            "la huella SHA-256 de la red no coincide con la declarada",
            "network",
        )
    name = f"{NETWORK_FILE}.gz" if data.startswith(GZIP_MAGIC) else NETWORK_FILE
    return name, data, read_network_graph(path)


def _program(folder: Path, case: Case) -> tuple[bytes, ProgramRecord]:
    """Programa derivado publicado, comprobado contra el caso y la red."""
    try:
        manifest_bytes = (folder / PROGRAM_MANIFEST_FILE).read_bytes()
        program_bytes = (folder / PROGRAM_FILE).read_bytes()
    except OSError as error:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            f"no se puede leer el programa derivado ({type(error).__name__})",
            "program_dir",
        ) from error
    try:
        manifest = ProgramManifest.model_validate_json(manifest_bytes)
    except ValidationError:
        raise _error(
            ErrorCode.INPUT_SCHEMA,
            "el manifiesto del programa derivado no es válido",
            "program_dir",
        ) from None
    network_sha = None if case.network is None else case.network.sha256
    checks = (
        (manifest.case_sha256 == canonical_sha256(case), "es de otro caso o de otra versión"),
        (manifest.network_sha256 == network_sha, "es de otra red"),
        (
            manifest.files.get(PROGRAM_FILE) == sha256_bytes(program_bytes),
            f"su archivo {PROGRAM_FILE} no tiene la huella de su manifiesto",
        ),
    )
    for passed, reason in checks:
        if not passed:
            raise _error(ErrorCode.HASH_MISMATCH, f"el programa derivado {reason}", "program_dir")
    record = ProgramRecord(
        file=PROGRAM_FILE,
        sha256=sha256_bytes(program_bytes),
        program_id=manifest.program_id,
        tls_id=manifest.tls_id,
        source_manifest_sha256=sha256_bytes(manifest_bytes),
    )
    return program_bytes, record


@dataclass(frozen=True)
class _Lanes:
    """Carriles de salida de un movimiento: índices en orden, o ninguno para ``best``."""

    indices: tuple[int, ...]

    @property
    def label(self) -> str:
        return " ".join(str(index) for index in self.indices) or "best"


def _depart_lanes(
    case: Case, routes: RouteTable, graph: NetworkGraph, used: set[str]
) -> dict[str, _Lanes]:
    """Carril de salida de cada movimiento con vehículos (D4, ajustado en F2)."""
    lanes: dict[str, _Lanes] = {}
    for movement in case.movements:
        if movement.id not in used:
            continue
        entry = approach_edge(movement.incoming_lanes, graph)
        if routes.routes[movement.id][0] == entry:
            indices = tuple(graph.lanes[lane].index for lane in movement.incoming_lanes)
            lanes[movement.id] = _Lanes(indices)
        else:
            lanes[movement.id] = _Lanes(())
    return lanes


def _number(value: float) -> str:
    """Número como lo escribe SUMO: ``82`` y no ``82.0``."""
    return str(int(value)) if value == int(value) else repr(value)


def _route_id(movement_id: str) -> str:
    return f"ruta_{movement_id}"


def _vtype_attributes(name: str, vtype: VehicleType) -> dict[str, str]:
    attributes = {"id": name, "vClass": vtype.vclass}
    attributes.update(
        {
            attribute: _number(vtype.attributes[attribute])
            for attribute in NUMERIC_ATTRIBUTES
            if attribute in vtype.attributes
        }
    )
    if vtype.lat_alignment is not None:
        attributes["latAlignment"] = vtype.lat_alignment
    if vtype.gui_shape is not None:
        attributes["guiShape"] = vtype.gui_shape
    if vtype.color is not None:
        attributes["color"] = vtype.color
    return attributes


def _demand_xml(
    cohort: Cohort, routes: RouteTable, types: VehicleTypes, lanes: Mapping[str, _Lanes]
) -> tuple[bytes, dict[str, str]]:
    """Archivo de demanda y el carril de salida asignado a cada vehículo."""
    root = Element("routes")
    used_classes = sorted({vehicle.vehicle_class for vehicle in cohort.vehicles})
    for name in used_classes:
        SubElement(root, "vType", _vtype_attributes(name, types.types[name]))
    for movement_id in sorted(lanes):
        SubElement(
            root, "route", id=_route_id(movement_id), edges=" ".join(routes.routes[movement_id])
        )
    served: dict[str, int] = {}
    assigned: dict[str, str] = {}
    for vehicle in cohort.vehicles:
        options = lanes[vehicle.movement_id].indices
        position = served.get(vehicle.movement_id, 0)
        served[vehicle.movement_id] = position + 1
        lane = str(options[position % len(options)]) if options else "best"
        assigned[vehicle.vehicle_id] = lane
        SubElement(
            root,
            "vehicle",
            id=vehicle.vehicle_id,
            type=vehicle.vehicle_class,
            route=_route_id(vehicle.movement_id),
            depart=_number(vehicle.depart_s),
            departLane=lane,
            departSpeed=DEPART_SPEED,
        )
    indent(root, space="    ")
    return (XML_HEADER + tostring(root, encoding="unicode") + "\n").encode("utf-8"), assigned


def _times(case: Case, scenario: Scenario) -> Times:
    end = scenario.warmup_s + scenario.measure_s + scenario.drain_max_s
    return Times(
        step_length_s=case.tick_s,
        begin_s=0.0,
        warmup_s=scenario.warmup_s,
        measure_s=scenario.measure_s,
        drain_max_s=scenario.drain_max_s,
        end_s=end,
        cohort_start_s=scenario.warmup_s,
        cohort_end_s=scenario.warmup_s + scenario.measure_s,
    )


def _config_xml(
    network_name: str, times: Times, seed: int, options: Mapping[str, float | bool]
) -> bytes:
    root = Element("configuration")
    inputs = SubElement(root, "input")
    SubElement(inputs, "net-file", value=network_name)
    SubElement(inputs, "route-files", value=DEMAND_FILE)
    SubElement(inputs, "additional-files", value=PROGRAM_FILE)
    time = SubElement(root, "time")
    SubElement(time, "begin", value=_number(times.begin_s))
    SubElement(time, "end", value=_number(times.end_s))
    SubElement(time, "step-length", value=_number(times.step_length_s))
    if options:
        processing = SubElement(root, "processing")
        for name in sorted(options):
            value = options[name]
            text = ("true" if value else "false") if isinstance(value, bool) else _number(value)
            SubElement(processing, name, value=text)
    random = SubElement(root, "random_number")
    SubElement(random, "seed", value=str(seed))
    report = SubElement(root, "report")
    SubElement(report, "no-step-log", value="true")
    SubElement(report, "duration-log.statistics", value="true")
    indent(root, space="    ")
    return (XML_HEADER + tostring(root, encoding="unicode") + "\n").encode("utf-8")


def _canonical_sha256(data: object) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(text.encode("utf-8"))


def _text(value: str) -> str:
    """Identificador para Excel: entre ``="..."`` para que no se convierta en número."""
    return '="' + value.replace('"', '""') + '"'


def _cohort_csv(
    cohort: Cohort, routes: RouteTable, types: VehicleTypes, assigned: Mapping[str, str]
) -> bytes:
    """Planilla de la cohorte: un vehículo por fila con la huella de sus atributos (D19)."""
    rows: list[list[str]] = [COHORT_HEADER]
    for vehicle in cohort.vehicles:
        attributes = {
            "vehicle_id": vehicle.vehicle_id,
            "movement_id": vehicle.movement_id,
            "vehicle_class": vehicle.vehicle_class,
            "type": _vtype_attributes(vehicle.vehicle_class, types.types[vehicle.vehicle_class]),
            "route": routes.routes[vehicle.movement_id],
            "depart_s": vehicle.depart_s,
            "depart_lane": assigned[vehicle.vehicle_id],
            "in_cohort": vehicle.in_cohort,
        }
        rows.append(
            [
                _text(vehicle.vehicle_id),
                _text(vehicle.movement_id),
                _text(vehicle.vehicle_class),
                _text(vehicle.vehicle_class),
                _text(_route_id(vehicle.movement_id)),
                _number(vehicle.depart_s),
                assigned[vehicle.vehicle_id],
                "sí" if vehicle.in_cohort else "no",
                _canonical_sha256(attributes),
            ]
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")
