"""Auditoría de una simulación SUMO: configuración, tipos, rutas, demanda y hallazgos (ADR09, F4).

Registra lo que la simulación declara (HU04: demanda, semilla y opciones de la corrida). No
ejecuta SUMO ni calibra nada. Las rutas de archivo son relativas a la carpeta auditada.
"""

from typing import Literal

from pydantic import Field

from semaforo.dominio.base_model import FrozenModel

AuditCode = Literal[
    "INPUT_NOT_AVAILABLE",
    "NO_END_TIME",
    "UNDEFINED_ROUTE",
    "UNDEFINED_TYPE",
    "UNUSED_ROUTE",
    "UNUSED_TYPE",
    "ROUTE_UNKNOWN_EDGE",
    "ROUTE_EDGE_FORBIDDEN",
    "ROUTE_DISCONNECTED",
    "DEMAND_AFTER_END",
    "DEMAND_TRUNCATED_BY_END",
    "DEMAND_WITHOUT_END",
    "ADDITIONAL_TLS_PROGRAM",
    "ADDITIONAL_DETECTOR",
    "ABSOLUTE_FILE_REFERENCE",
    "NOT_AUDITED",
]
DemandKind = Literal["flow", "vehicle", "trip"]


class ConfigSummary(FrozenModel):
    """Tiempos y semilla del .sumocfg, y todas sus opciones tal como están escritas.

    ``end_s`` es None si el .sumocfg no fija un final: SUMO sigue hasta que no queda ningún
    vehículo. Un tiempo escrito en un formato que no es un número queda en None y su texto se
    conserva en ``options``.
    """

    begin_s: float | None
    end_s: float | None
    step_length_s: float | None
    seed: str | None
    options: dict[str, dict[str, str]]


class VehicleTypeInfo(FrozenModel):
    """Un ``vType``. ``attributes`` son los parámetros declarados (sin ``id`` ni ``vClass``)."""

    id: str
    source: str
    vclass: str
    attributes: dict[str, str]


class RouteInfo(FrozenModel):
    """Una ruta con nombre."""

    id: str
    source: str
    edge_count: int = Field(ge=0)
    first_edge: str | None
    last_edge: str | None


class DemandItem(FrozenModel):
    """Un flujo, vehículo o viaje.

    ``rate_veh_h`` es la tasa declarada en vehículos por hora (None en vehículos y viajes
    sueltos). ``expected_vehicles`` es la cantidad que declara el archivo: en los flujos de
    intervalo fijo, la que SUMO 1.27.1 carga; en los aleatorios, la media. SUMO puede insertar
    menos si la red se satura o la simulación termina antes. ``attributes`` son los demás
    atributos declarados, por ejemplo ``departLane``.
    """

    id: str
    source: str
    kind: DemandKind
    route_id: str | None
    from_edge: str | None
    to_edge: str | None
    type_id: str
    vclass: str
    begin_s: float | None
    end_s: float | None
    rate_veh_h: float | None
    expected_vehicles: float | None
    attributes: dict[str, str]


class EntryLoad(FrozenModel):
    """Tasa declarada de una clase de vehículo que entra por una arista.

    Suma los flujos de esa clase que empiezan en la arista. ``lanes`` son los carriles de la
    arista que admiten la clase (un carril exclusivo de bus no cuenta para los autos); es None si
    la arista no está en la red o no se pudo leer la red.
    """

    edge: str
    vclass: str
    lanes: int | None
    flow_veh_h: float


class AuditFinding(FrozenModel):
    """Una observación sobre la simulación. No afirma que sea un error: lo revisa el Product Owner.

    ``subject`` es lo observado (un id, una opción o una etiqueta XML) y ``source`` el archivo,
    relativo a la carpeta auditada.
    """

    code: AuditCode
    subject: str
    source: str | None
    message: str


class SimulationAudit(FrozenModel):
    """Auditoría completa de una simulación."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    entry_config: str
    net_file: str | None
    route_files: list[str]
    additional_files: list[str]
    network_checked: bool
    config: ConfigSummary
    vehicle_types: list[VehicleTypeInfo]
    routes: list[RouteInfo]
    demand: list[DemandItem]
    expected_vehicles_total: float
    expected_vehicles_by_class: dict[str, float]
    entry_loads: list[EntryLoad]
    findings: list[AuditFinding]
