"""Rutas y tipos de vehículo de la demanda, y su revisión contra el caso y la red (DEV06 F2).

Decisiones D3 y D10 de ``2026-10-31-dev06-f0-decisiones``, con el ajuste de F2:

- **Rutas** (``rutas.json``): ``{"schema_version": "1.0.0", "routes": {movimiento: [calles]}}``.
  No se inventan. Cada movimiento con vehículos necesita la suya (ROUTE-01); las calles existen y no
  son tramos internos del cruce (ROUTE-02); cada calle está conectada con la siguiente (ROUTE-03);
  la ruta pasa de la calle de entrada del movimiento a una de sus calles de salida, una a
  continuación de la otra (ROUTE-04); y cada clase que circula por el movimiento tiene permiso en
  cada calle de la ruta y en el carril de salida, si sale en la calle de entrada (ROUTE-05).
- **Tipos** (``tipos.json``): ``{"schema_version": "1.0.0", "types": {clase: tipo}}``. Cada clase
  del caso tiene un tipo y no hay tipos de clases que el caso no tiene (TYPE-01); la clase de SUMO
  es de vehículo de calle (TYPE-02); los atributos numéricos son de una lista y positivos
  (TYPE-03). Además del largo, el ancho, la separación, la aceleración, la deceleración y la
  velocidad máxima de F0, se admiten los del modelo de subcarriles que usa la simulación del
  equipo para las motos (separación lateral, velocidad lateral, cambio de subcarril y alineación
  lateral) y, para la vista de SUMO, la forma y el color.
"""

from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from semaforo.caso.json_input import read_json
from semaforo.caso.network_graph import NetworkGraph
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.case import Case, CaseIssue, Identifier, issues_of
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import Scenario, accept_scenario

__all__ = [
    "NUMERIC_ATTRIBUTES",
    "ROAD_VCLASSES",
    "DemandInputError",
    "RouteTable",
    "VehicleType",
    "VehicleTypes",
    "approach_edge",
    "read_routes",
    "read_scenario",
    "read_vehicle_types",
    "route_issues",
    "type_issues",
]

# Atributos numéricos de <vType> que se admiten, con su nombre en SUMO.
NUMERIC_ATTRIBUTES = (
    "length",
    "width",
    "minGap",
    "accel",
    "decel",
    "maxSpeed",
    "minGapLat",
    "maxSpeedLat",
    "lcSublane",
)
# Clases de vehículo de SUMO que circulan por calles (sin trenes, barcos ni peatones).
ROAD_VCLASSES = frozenset(
    {
        "passenger",
        "private",
        "taxi",
        "bus",
        "coach",
        "delivery",
        "truck",
        "trailer",
        "motorcycle",
        "moped",
        "bicycle",
        "evehicle",
        "emergency",
        "authority",
        "army",
        "vip",
        "custom1",
        "custom2",
    }
)

MAX_COLOR = 255

Edges = Annotated[list[Identifier], Field(min_length=1)]


class DemandInputError(DomainError):
    """Las rutas, los tipos o el escenario no sirven para la demanda. Lleva los problemas."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        field: str | None = None,
        issues: tuple[CaseIssue, ...] = (),
    ) -> None:
        super().__init__(code, message, field)
        self.issues = issues


class VehicleType(FrozenModel):
    """Tipo de vehículo de SUMO para una clase del caso."""

    vclass: str
    attributes: dict[str, float] = Field(default_factory=dict[str, float])
    lat_alignment: Literal["left", "right", "center", "compact", "nice", "arbitrary"] | None = None
    gui_shape: str | None = Field(default=None, pattern=r"^[a-z]+(/[a-z]+)?$")
    color: str | None = Field(default=None, pattern=r"^\d{1,3},\d{1,3},\d{1,3}$")


class VehicleTypes(FrozenModel):
    """Tipos de vehículo por clase del caso (``tipos.json``)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    types: dict[Identifier, VehicleType]


class RouteTable(FrozenModel):
    """Ruta de cada movimiento: la lista de calles, en orden (``rutas.json``)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    routes: dict[Identifier, Edges]


def _parsed[T: FrozenModel](model: type[T], data: object, what: str) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        issues = tuple(issues_of(error))
        first = issues[0]
        where = "" if first.field is None else f" en {first.field}"
        raise DemandInputError(
            ErrorCode.INPUT_SCHEMA,
            f"{what}{where}: {first.message}",
            first.field,
            issues,
        ) from None


def read_routes(path: Path) -> RouteTable:
    """Rutas de ``path``. Raises: CasoError o DemandInputError (INPUT_SCHEMA)."""
    return _parsed(RouteTable, read_json(path, "rutas"), "las rutas no son válidas")


def read_vehicle_types(path: Path) -> VehicleTypes:
    """Tipos de vehículo de ``path``. Raises: CasoError o DemandInputError (INPUT_SCHEMA)."""
    return _parsed(VehicleTypes, read_json(path, "tipos"), "los tipos de vehículo no son válidos")


def read_scenario(path: Path, case: Case) -> Scenario:
    """Escenario de ``path``, comprobado contra ``case``.

    Raises:
        CasoError: si el archivo no se puede leer como JSON.
        ScenarioInvalidError: si no cumple el contrato o no encaja con el caso.
    """
    return accept_scenario(read_json(path, "escenario"), case)


def _n(value: float) -> str:
    return f"{value:g}"


def type_issues(types: VehicleTypes, case: Case) -> list[CaseIssue]:
    """TYPE-01 a TYPE-03: un tipo por clase del caso, clase de SUMO válida y atributos válidos."""
    issues: list[CaseIssue] = [
        CaseIssue("TYPE-01", "types", f"falta el tipo de la clase «{name}»")
        for name in case.vehicle_classes
        if name not in types.types
    ]
    for name, vtype in types.types.items():
        field = f"types.{name}"
        if name not in case.vehicle_classes:
            issues.append(CaseIssue("TYPE-01", field, f"el caso no tiene la clase «{name}»"))
        if vtype.vclass not in ROAD_VCLASSES:
            issues.append(
                CaseIssue(
                    "TYPE-02",
                    f"{field}.vclass",
                    f"«{vtype.vclass}» no es una clase de SUMO de vehículo de calle",
                )
            )
        for attribute, value in vtype.attributes.items():
            if attribute not in NUMERIC_ATTRIBUTES:
                issues.append(
                    CaseIssue(
                        "TYPE-03",
                        f"{field}.attributes.{attribute}",
                        f"atributo no admitido; se admiten: {', '.join(NUMERIC_ATTRIBUTES)}",
                    )
                )
            elif value <= 0:
                issues.append(
                    CaseIssue(
                        "TYPE-03",
                        f"{field}.attributes.{attribute}",
                        f"debe ser mayor que 0 y es {_n(value)}",
                    )
                )
        if vtype.color is not None and any(
            int(part) > MAX_COLOR for part in vtype.color.split(",")
        ):
            issues.append(
                CaseIssue("TYPE-03", f"{field}.color", "cada componente del color va de 0 a 255")
            )
    return issues


def approach_edge(case_lanes: list[str], graph: NetworkGraph) -> str | None:
    """Calle de entrada de un movimiento: la de sus carriles, si todos existen y es una sola."""
    if any(lane not in graph.lanes for lane in case_lanes):
        return None
    edges = {graph.lanes[lane].edge_id for lane in case_lanes}
    return next(iter(edges)) if len(edges) == 1 else None


def route_issues(  # noqa: PLR0912 - una pasada por movimiento con sus cinco reglas
    routes: RouteTable,
    case: Case,
    graph: NetworkGraph,
    classes_by_movement: Mapping[str, frozenset[str]],
    types: VehicleTypes,
) -> list[CaseIssue]:
    """ROUTE-01 a ROUTE-05 para los movimientos con vehículos (``classes_by_movement``).

    ``classes_by_movement`` dice qué clases tienen al menos un vehículo en cada movimiento.
    """
    issues: list[CaseIssue] = []
    movements = {movement.id: movement for movement in case.movements}
    issues.extend(
        CaseIssue(
            "ROUTE-01", f"routes.{movement_id}", f"el caso no tiene el movimiento «{movement_id}»"
        )
        for movement_id in routes.routes
        if movement_id not in movements
    )
    for movement in case.movements:
        classes = classes_by_movement.get(movement.id, frozenset())
        if not classes:
            continue
        field = f"routes.{movement.id}"
        edges = routes.routes.get(movement.id)
        if edges is None:
            issues.append(
                CaseIssue("ROUTE-01", "routes", f"falta la ruta del movimiento «{movement.id}»")
            )
            continue
        unknown = False
        for position, edge in enumerate(edges):
            if edge in graph.internal_edges:
                message = f"«{edge}» es un tramo interno del cruce, no una calle"
            elif edge not in graph.edges:
                message = f"la calle «{edge}» no existe en la red"
            else:
                continue
            unknown = True
            issues.append(CaseIssue("ROUTE-02", f"{field}[{position}]", message))
        if unknown:
            continue
        for position, (before, after) in enumerate(pairwise(edges)):
            if (before, after) not in graph.connections:
                issues.append(
                    CaseIssue(
                        "ROUTE-03",
                        f"{field}[{position + 1}]",
                        f"la calle «{before}» no está conectada con «{after}»",
                    )
                )
        entry = approach_edge(movement.incoming_lanes, graph)
        steps = set(pairwise(edges))
        if entry is None:
            issues.append(
                CaseIssue(
                    "ROUTE-04",
                    field,
                    "los carriles de entrada del movimiento no están todos en la red ni en una "
                    f"misma calle ({', '.join(movement.incoming_lanes)})",
                )
            )
        elif not any((entry, exit_) in steps for exit_ in movement.outgoing_edges):
            issues.append(
                CaseIssue(
                    "ROUTE-04",
                    field,
                    f"la ruta no pasa de la calle de entrada del movimiento «{entry}» a una de sus "
                    f"calles de salida ({', '.join(movement.outgoing_edges)})",
                )
            )
        for name in sorted(classes):
            vtype = types.types.get(name)
            if vtype is None:
                continue
            closed = [
                edge
                for edge in edges
                if not any(lane.permits(vtype.vclass) for lane in graph.lanes_of(edge))
            ]
            if edges[0] == entry:
                closed += [
                    lane
                    for lane in movement.incoming_lanes
                    if lane in graph.lanes and not graph.lanes[lane].permits(vtype.vclass)
                ]
            if closed:
                issues.append(
                    CaseIssue(
                        "ROUTE-05",
                        field,
                        f"la clase «{name}» ({vtype.vclass}) no tiene permiso en: "
                        f"{', '.join(closed)}",
                    )
                )
    return issues
