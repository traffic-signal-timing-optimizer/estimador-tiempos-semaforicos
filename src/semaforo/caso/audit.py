"""Auditoría estática de una simulación SUMO: rutas, demanda, comportamiento y adicionales.

Lee el .sumocfg y los archivos de su sección ``<input>`` (red, rutas y adicionales) sin ejecutar
SUMO. Comprueba que las rutas existan y sean viables para la clase de cada vehículo, resume la
demanda declarada y avisa de lo que pueda cambiar la simulación sin estar en las rutas: programas
semafóricos y detectores en archivos adicionales. Lo que no interpreta lo reporta como
``NOT_AUDITED``, nunca lo omite en silencio. Todos los archivos se leen con ``xml_input``.
"""

import itertools
import math
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree.ElementTree import Element

from semaforo.caso.audit_models import (
    AuditCode,
    AuditFinding,
    ConfigSummary,
    DemandItem,
    DemandKind,
    EntryLoad,
    RouteInfo,
    SimulationAudit,
    VehicleTypeInfo,
)
from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.sumo_config import (
    INPUT,
    ConfigReferences,
    is_absolute_like,
    read_config_options,
    read_config_references,
)
from semaforo.caso.xml_input import invalid, optional_number, parse_root, required, to_number

# Límites provisionales, pendientes del piloto (igual que la red en F3).
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024

NET_FILE = "net-file"
ROUTE_FILES = "route-files"
ADDITIONAL_FILES = "additional-files"
AUDITED_OPTIONS = (NET_FILE, ROUTE_FILES, ADDITIONAL_FILES)
ROUTE_ROOTS = frozenset({"routes", "additional"})
DEFAULT_TYPE = "DEFAULT_VEHTYPE"
DEFAULT_CLASS = "passenger"
DEMAND_KINDS: dict[str, DemandKind] = {"flow": "flow", "vehicle": "vehicle", "trip": "trip"}
TLS_TAGS = frozenset({"tlLogic", "WAUT"})
DETECTOR_TAGS = frozenset(
    {
        "inductionLoop",
        "e1Detector",
        "instantInductionLoop",
        "laneAreaDetector",
        "e2Detector",
        "entryExitDetector",
        "e3Detector",
    }
)
RATE_ATTRIBUTES = ("perHour", "vehsPerHour", "period", "probability", "number")
NOT_DEMAND_ATTRIBUTES = frozenset(
    {"id", "route", "type", "begin", "end", "depart", "from", "to", *RATE_ATTRIBUTES}
)
DEPART_KEYWORDS = frozenset({"triggered", "containerTriggered", "now", "split", "begin"})
EXPONENTIAL_PERIOD = re.compile(r"^exp\((.+)\)$")
SECONDS_PER_HOUR = 3600.0
COUNT_DECIMALS = 9


def audit_simulation(
    folder: Path, entry_config: str, max_bytes: int = MAX_INPUT_BYTES
) -> SimulationAudit:
    """Audita la simulación de ``folder`` cuyo .sumocfg de entrada es ``entry_config``.

    Args:
        folder: carpeta de la simulación, normalmente la copia inmutable de F2. Solo se lee.
        entry_config: ruta del .sumocfg, relativa a ``folder``.
        max_bytes: tamaño máximo descomprimido de cada archivo de red, rutas o adicionales.

    Raises:
        CasoError: INPUT_SCHEMA si la carpeta o el .sumocfg no existen o un archivo no es XML
            válido y seguro, o trae valores no válidos; PATH_NOT_ALLOWED si el .sumocfg está
            fuera de la carpeta.
    """
    root = _checked_folder(folder)
    entry = _checked_entry(root, entry_config)
    config_path = root / entry
    findings = _Findings()
    inputs = _inputs(root, entry, read_config_references(config_path, MAX_CONFIG_BYTES), findings)
    config = _config_summary(read_config_options(config_path, MAX_CONFIG_BYTES))
    if config.end_s is None:
        findings.add(
            "NO_END_TIME",
            entry,
            entry,
            "el .sumocfg no fija end: SUMO sigue hasta que no queda ningún vehículo",
        )
    net_file = next(iter(inputs[NET_FILE]), None)
    network = None if net_file is None else _Network.read(root / net_file, max_bytes)
    catalog = _Catalog()
    for relative in [*inputs[ADDITIONAL_FILES], *inputs[ROUTE_FILES]]:
        catalog.read(
            relative, parse_root(root / relative, max_bytes, ROUTE_ROOTS, "rutas"), findings
        )
    auditor = _Auditor(catalog, network, config, findings)
    demand = [auditor.demand_item(element, source) for element, source in catalog.demand]
    catalog.report_unused(findings)
    by_class: dict[str, float] = defaultdict(float)
    for item in demand:
        if item.expected_vehicles is not None:
            by_class[item.vclass] += item.expected_vehicles
    return SimulationAudit(
        entry_config=entry,
        net_file=net_file,
        route_files=inputs[ROUTE_FILES],
        additional_files=inputs[ADDITIONAL_FILES],
        network_checked=network is not None,
        config=config,
        vehicle_types=list(catalog.types.values()),
        routes=[info for info, _ in catalog.routes.values()],
        demand=demand,
        expected_vehicles_total=sum(by_class.values()),
        expected_vehicles_by_class=dict(sorted(by_class.items())),
        entry_loads=_entry_loads(demand, network),
        findings=findings.items,
    )


@dataclass
class _Findings:
    items: list[AuditFinding] = field(default_factory=list[AuditFinding])

    def add(self, code: AuditCode, subject: str, source: str | None, message: str) -> None:
        finding = AuditFinding(code=code, subject=subject, source=source, message=message)
        if finding not in self.items:
            self.items.append(finding)


def _checked_folder(folder: Path) -> Path:
    if not folder.is_dir():
        raise invalid("la carpeta de la simulación no existe o no es una carpeta", "folder")
    return folder.resolve()


def _checked_entry(root: Path, entry_config: str) -> str:
    text = entry_config.strip().replace("\\", "/")
    if not text:
        raise invalid("falta el .sumocfg de entrada", "entry_config")
    if is_absolute_like(text) or ".." in text.split("/"):
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED,
            "el .sumocfg debe estar dentro de la carpeta",
            "entry_config",
        )
    relative = posixpath.normpath(text)
    if not (root / relative).is_file():
        raise invalid(f"no existe {text!r} en la carpeta", "entry_config")
    return relative


def _inputs(
    root: Path, entry: str, references: ConfigReferences, findings: _Findings
) -> dict[str, list[str]]:
    """Archivos de ``<input>`` disponibles en la carpeta, por opción y sin repetir."""
    inputs: dict[str, list[str]] = {option: [] for option in AUDITED_OPTIONS}
    config_dir = posixpath.dirname(entry)
    for reference in (ref for ref in references.files if ref.section == INPUT):
        if reference.option not in inputs:
            findings.add(
                "NOT_AUDITED",
                reference.option,
                entry,
                "archivo de entrada que la auditoría no interpreta",
            )
            continue
        relative, reason = _available(root, config_dir, reference.path)
        if relative is None:
            findings.add("INPUT_NOT_AVAILABLE", reference.path, entry, reason)
        elif relative not in inputs[reference.option]:
            inputs[reference.option].append(relative)
    return inputs


def _available(root: Path, config_dir: str, reference: str) -> tuple[str | None, str]:
    if is_absolute_like(reference):
        return None, "ruta absoluta: no se sigue"
    relative = posixpath.normpath(posixpath.join(config_dir, reference.replace("\\", "/")))
    if relative == ".." or relative.startswith("../"):
        return None, "fuera de la carpeta: no se sigue"
    path = root / relative
    if not path.is_file():
        return None, "no está en la carpeta"
    if not path.resolve().is_relative_to(root):
        return None, "sale de la carpeta por un enlace o una unión: no se sigue"
    return relative, ""


def _lenient_number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _config_summary(options: dict[str, dict[str, str]]) -> ConfigSummary:
    time = options.get("time", {})
    return ConfigSummary(
        begin_s=_lenient_number(time.get("begin")),
        end_s=_lenient_number(time.get("end")),
        step_length_s=_lenient_number(time.get("step-length")),
        seed=options.get("random_number", {}).get("seed"),
        options=options,
    )


def _permits(allow: str | None, disallow: str | None, vclass: str) -> bool:
    if allow is not None:
        allowed = allow.split()
        return "all" in allowed or vclass in allowed
    if disallow is not None:
        forbidden = disallow.split()
        return "all" not in forbidden and vclass not in forbidden
    return True


@dataclass(frozen=True)
class _Network:
    """Lo que la auditoría necesita de la red: carriles con permisos y conexiones."""

    lanes: dict[str, list[tuple[str, str | None, str | None]]]
    connections: dict[tuple[str, str], list[tuple[str, str, str | None, str | None]]]

    @classmethod
    def read(cls, path: Path, max_bytes: int) -> "_Network":
        root = parse_root(path, max_bytes, frozenset({"net"}), "red")
        lanes: dict[str, list[tuple[str, str | None, str | None]]] = {}
        for edge in root.findall("edge"):
            if edge.get("function") != "internal":
                lanes[required(edge, "id")] = [
                    (required(lane, "index"), lane.get("allow"), lane.get("disallow"))
                    for lane in edge.findall("lane")
                ]
        connections: dict[tuple[str, str], list[tuple[str, str, str | None, str | None]]] = (
            defaultdict(list)
        )
        for connection in root.findall("connection"):
            origin, target = required(connection, "from"), required(connection, "to")
            if origin in lanes and target in lanes:
                connections[(origin, target)].append(
                    (
                        required(connection, "fromLane"),
                        required(connection, "toLane"),
                        connection.get("allow"),
                        connection.get("disallow"),
                    )
                )
        return cls(lanes=lanes, connections=dict(connections))

    def _lane_permits(self, edge: str, index: str, vclass: str) -> bool:
        return any(
            _permits(allow, disallow, vclass)
            for lane, allow, disallow in self.lanes[edge]
            if lane == index
        )

    def lanes_for(self, edge: str, vclass: str) -> int:
        """Carriles de ``edge`` que admiten ``vclass``."""
        return sum(_permits(allow, disallow, vclass) for _, allow, disallow in self.lanes[edge])

    def edge_permits(self, edge: str, vclass: str) -> bool:
        return self.lanes_for(edge, vclass) > 0

    def connected(self, origin: str, target: str, vclass: str) -> bool:
        return any(
            self._lane_permits(origin, from_lane, vclass)
            and self._lane_permits(target, to_lane, vclass)
            and _permits(allow, disallow, vclass)
            for from_lane, to_lane, allow, disallow in self.connections.get((origin, target), [])
        )


@dataclass
class _Catalog:
    """Definiciones y demanda de todos los archivos de rutas y adicionales."""

    types: dict[str, VehicleTypeInfo] = field(default_factory=dict[str, VehicleTypeInfo])
    routes: dict[str, tuple[RouteInfo, list[str]]] = field(
        default_factory=dict[str, tuple[RouteInfo, list[str]]]
    )
    distributed_types: set[str] = field(default_factory=set[str])
    distributed_routes: set[str] = field(default_factory=set[str])
    demand: list[tuple[Element, str]] = field(default_factory=list[tuple[Element, str]])
    used_types: set[str] = field(default_factory=set[str])
    used_routes: set[str] = field(default_factory=set[str])

    def read(self, source: str, root: Element, findings: _Findings) -> None:
        for element in root:
            self._read_element(source, element, findings)
        for element in root.iter():
            reference = element.get("file")
            if reference is not None and is_absolute_like(reference):
                findings.add(
                    "ABSOLUTE_FILE_REFERENCE",
                    element.get("id", element.tag),
                    source,
                    "ruta absoluta: SUMO escribiría fuera de la carpeta de la corrida",
                )

    def _read_element(self, source: str, element: Element, findings: _Findings) -> None:
        tag = element.tag
        if tag == "vType":
            type_id = required(element, "id")
            self.types[type_id] = VehicleTypeInfo(
                id=type_id,
                source=source,
                vclass=element.get("vClass", DEFAULT_CLASS),
                attributes={k: v for k, v in element.attrib.items() if k not in ("id", "vClass")},
            )
        elif tag == "route":
            route_id = required(element, "id")
            edges = required(element, "edges").split()
            info = RouteInfo(
                id=route_id,
                source=source,
                edge_count=len(edges),
                first_edge=edges[0] if edges else None,
                last_edge=edges[-1] if edges else None,
            )
            self.routes[route_id] = (info, edges)
        elif tag in DEMAND_KINDS:
            self.demand.append((element, source))
        elif tag in ("routeDistribution", "vTypeDistribution"):
            target = (
                self.distributed_routes if tag == "routeDistribution" else self.distributed_types
            )
            target.add(required(element, "id"))
            findings.add("NOT_AUDITED", tag, source, "distribución: no se audita su contenido")
        elif tag in TLS_TAGS:
            findings.add(
                "ADDITIONAL_TLS_PROGRAM",
                element.get("id", tag),
                source,
                "programa semafórico fuera de la red: puede reemplazar el del inventario",
            )
        elif tag in DETECTOR_TAGS:
            findings.add("ADDITIONAL_DETECTOR", element.get("id", tag), source, f"detector <{tag}>")
        else:
            findings.add(
                "NOT_AUDITED", tag, source, f"elemento <{tag}> que la auditoría no interpreta"
            )

    def report_unused(self, findings: _Findings) -> None:
        for route_id, (info, _) in self.routes.items():
            if route_id not in self.used_routes:
                findings.add("UNUSED_ROUTE", route_id, info.source, "ruta que ningún vehículo usa")
        for type_id, info in self.types.items():
            if type_id not in self.used_types:
                findings.add("UNUSED_TYPE", type_id, info.source, "tipo que ningún vehículo usa")


def _depart(element: Element) -> float | None:
    text = required(element, "depart")
    return None if text in DEPART_KEYWORDS else to_number(element, "depart", text)


def _flow_rate(
    element: Element, begin: float, end: float | None
) -> tuple[float | None, float | None]:
    """(tasa en veh/h, vehículos declarados) de un flujo.

    En los flujos de intervalo fijo la cantidad es la que emite SUMO 1.27.1; en los aleatorios
    (``probability`` y ``period="exp(…)"``), la media.
    """
    duration = None if end is None else end - begin
    for name in RATE_ATTRIBUTES:
        text = element.get(name)
        if text is None:
            continue
        if name == "number":
            count = to_number(element, name, text)
            rate = count * SECONDS_PER_HOUR / duration if duration else None
            return rate, count
        exponential = EXPONENTIAL_PERIOD.match(text) if name == "period" else None
        random = name == "probability" or exponential is not None
        if exponential is not None:
            per_second = to_number(element, name, exponential.group(1))
        elif name == "period":
            period = to_number(element, name, text)
            if period <= 0:
                raise invalid(f"period debe ser positivo en <{element.tag}>", "flow.period")
            per_second = 1 / period
        elif name == "probability":
            per_second = to_number(element, name, text)
        else:
            per_second = to_number(element, name, text) / SECONDS_PER_HOUR
        if duration is None:
            expected = None
        elif random:
            expected = per_second * duration
        else:
            expected = _fixed_interval_count(duration, per_second)
        return per_second * SECONDS_PER_HOUR, expected
    return None, None


def _fixed_interval_count(duration: float, per_second: float) -> float:
    """Vehículos de un flujo de intervalo fijo: techo(duración / intervalo), final excluido.

    Es la regla medida con SUMO 1.27.1 (``tests/integration/test_audit_sumo.py``). El redondeo
    previo a 9 decimales evita que un error de coma flotante (7,000000000000001) sume uno más.
    """
    if duration <= 0:
        return 0.0
    return float(math.ceil(round(duration * per_second, COUNT_DECIMALS)))


@dataclass(frozen=True)
class _Auditor:
    """Revisa cada elemento de demanda contra el catálogo, la red y la configuración."""

    catalog: _Catalog
    network: _Network | None
    config: ConfigSummary
    findings: _Findings

    def demand_item(self, element: Element, source: str) -> DemandItem:
        item_id = required(element, "id")
        kind = DEMAND_KINDS[element.tag]
        type_id, vclass = self._vehicle_type(element, item_id, source)
        route_id = element.get("route")
        edges = self._route_edges(element, route_id, item_id, source)
        from_edge = edges[0] if edges else element.get("from")
        to_edge = edges[-1] if edges else element.get("to")
        begin: float | None
        if kind == "flow":
            flow_begin = optional_number(element, "begin")
            begin = 0.0 if flow_begin is None else flow_begin
            end = optional_number(element, "end")
            rate, expected = _flow_rate(element, begin, end)
            if end is None:
                self.findings.add("DEMAND_WITHOUT_END", item_id, source, "el flujo no declara end")
        else:
            begin, end, rate, expected = _depart(element), None, None, 1.0
        self._check_times(item_id, source, begin, end)
        if edges is not None:
            self._check_route(item_id, source, edges, vclass)
        else:
            endpoints = [edge for edge in (from_edge, to_edge) if edge is not None]
            self._check_edges(item_id, source, endpoints, vclass)
        return DemandItem(
            id=item_id,
            source=source,
            kind=kind,
            route_id=route_id,
            from_edge=from_edge,
            to_edge=to_edge,
            type_id=type_id,
            vclass=vclass,
            begin_s=begin,
            end_s=end,
            rate_veh_h=rate,
            expected_vehicles=expected,
            attributes={k: v for k, v in element.attrib.items() if k not in NOT_DEMAND_ATTRIBUTES},
        )

    def _vehicle_type(self, element: Element, item_id: str, source: str) -> tuple[str, str]:
        catalog = self.catalog
        type_id = element.get("type", DEFAULT_TYPE)
        catalog.used_types.add(type_id)
        known = (
            type_id == DEFAULT_TYPE
            or type_id in catalog.types
            or type_id in catalog.distributed_types
        )
        if not known:
            self.findings.add(
                "UNDEFINED_TYPE", item_id, source, f"usa el tipo {type_id!r}, que no está definido"
            )
        vclass = catalog.types[type_id].vclass if type_id in catalog.types else DEFAULT_CLASS
        return type_id, vclass

    def _route_edges(
        self, element: Element, route_id: str | None, item_id: str, source: str
    ) -> list[str] | None:
        """Aristas de la ruta con nombre o de la ruta incluida; None si no hay ruta."""
        catalog = self.catalog
        if route_id is not None:
            catalog.used_routes.add(route_id)
            if route_id in catalog.routes:
                return catalog.routes[route_id][1]
            if route_id not in catalog.distributed_routes:
                self.findings.add(
                    "UNDEFINED_ROUTE",
                    item_id,
                    source,
                    f"usa la ruta {route_id!r}, que no está definida",
                )
            return None
        embedded = element.find("route")
        return None if embedded is None else required(embedded, "edges").split()

    def _check_times(
        self, item_id: str, source: str, begin: float | None, end: float | None
    ) -> None:
        final = self.config.end_s
        if final is None or begin is None:
            return
        if begin >= final:
            self.findings.add(
                "DEMAND_AFTER_END", item_id, source, "empieza cuando la simulación ya terminó"
            )
        elif end is not None and end > final:
            self.findings.add(
                "DEMAND_TRUNCATED_BY_END",
                item_id,
                source,
                "la simulación termina antes que el flujo",
            )

    def _check_edges(self, item_id: str, source: str, edges: list[str], vclass: str) -> set[str]:
        """Aristas que existen y admiten la clase; reporta las que no."""
        network = self.network
        if network is None:
            return set()
        unknown = [edge for edge in edges if edge not in network.lanes]
        if unknown:
            self.findings.add(
                "ROUTE_UNKNOWN_EDGE", item_id, source, f"aristas que no están en la red: {unknown}"
            )
        forbidden = [
            edge
            for edge in edges
            if edge in network.lanes and not network.edge_permits(edge, vclass)
        ]
        if forbidden:
            self.findings.add(
                "ROUTE_EDGE_FORBIDDEN",
                item_id,
                source,
                f"aristas sin ningún carril para {vclass}: {forbidden}",
            )
        return set(edges) - set(unknown) - set(forbidden)

    def _check_route(self, item_id: str, source: str, edges: list[str], vclass: str) -> None:
        """Como ``_check_edges`` y, además, conexión para la clase entre aristas consecutivas."""
        network = self.network
        usable = self._check_edges(item_id, source, edges, vclass)
        if network is None:
            return
        gaps = [
            (a, b)
            for a, b in itertools.pairwise(edges)
            if a in usable and b in usable and not network.connected(a, b, vclass)
        ]
        if gaps:
            self.findings.add(
                "ROUTE_DISCONNECTED", item_id, source, f"sin conexión para {vclass} entre {gaps}"
            )


def _entry_loads(demand: list[DemandItem], network: _Network | None) -> list[EntryLoad]:
    loads: dict[tuple[str, str], float] = defaultdict(float)
    for item in demand:
        if item.rate_veh_h is not None and item.from_edge is not None:
            loads[(item.from_edge, item.vclass)] += item.rate_veh_h
    return [
        EntryLoad(
            edge=edge,
            vclass=vclass,
            lanes=network.lanes_for(edge, vclass)
            if network is not None and edge in network.lanes
            else None,
            flow_veh_h=rate,
        )
        for (edge, vclass), rate in sorted(loads.items())
    ]
