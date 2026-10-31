"""Rutas y tipos de vehículo de la demanda (DEV06 F2): estructura y reglas ROUTE y TYPE."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from semaforo.caso.errors import CasoError
from semaforo.caso.network_graph import NetworkGraph, read_network_graph
from semaforo.dominio.case import Case, CaseIssue, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import ScenarioInvalidError
from semaforo.simulacion.demand_inputs import (
    NUMERIC_ATTRIBUTES,
    DemandInputError,
    RouteTable,
    VehicleTypes,
    approach_edge,
    read_routes,
    read_scenario,
    read_vehicle_types,
    route_issues,
    type_issues,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_NET = FIXTURES / "sumo" / "demo" / "demo.net.xml"
ROUTES: dict[str, Any] = {"routes": {"N_S": ["demo_N", "demo_S"], "E_W": ["demo_E", "demo_W"]}}
TYPES: dict[str, Any] = {
    "types": {
        "car": {"vclass": "passenger", "attributes": {"length": 5.0}},
        "bus": {"vclass": "bus", "attributes": {"length": 12.0}, "gui_shape": "bus"},
    }
}
BOTH = {"N_S": frozenset({"car", "bus"}), "E_W": frozenset({"car"})}


def the_case(change: dict[str, Any] | None = None) -> Case:
    data = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
    data.update(change or {})
    return parse_case(data)


def routes(**changes: list[str]) -> RouteTable:
    data = copy.deepcopy(ROUTES)
    data["routes"].update(changes)
    return RouteTable.model_validate(data)


def types(data: dict[str, Any] | None = None) -> VehicleTypes:
    return VehicleTypes.model_validate(data or copy.deepcopy(TYPES))


def graph() -> NetworkGraph:
    return read_network_graph(DEMO_NET)


def patched_graph(tmp_path: Path, old: str, new: str) -> NetworkGraph:
    text = DEMO_NET.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path = tmp_path / "red.net.xml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return read_network_graph(path)


def check(
    table: RouteTable | None = None,
    *,
    classes: dict[str, frozenset[str]] | None = None,
    net: NetworkGraph | None = None,
    vehicle_types: VehicleTypes | None = None,
) -> list[CaseIssue]:
    return route_issues(
        table or routes(),
        the_case(),
        net or graph(),
        BOTH if classes is None else classes,
        vehicle_types or types(),
    )


def rules(issues: list[CaseIssue]) -> list[tuple[str, str | None]]:
    return [(issue.rule_id, issue.field) for issue in issues]


# --- estructura y lectura -------------------------------------------------------------------


def test_the_example_routes_and_types_are_valid() -> None:
    assert check() == []
    assert type_issues(types(), the_case()) == []


def test_routes_and_types_are_read_from_files(tmp_path: Path) -> None:
    (tmp_path / "rutas.json").write_text(json.dumps(ROUTES), encoding="utf-8")
    (tmp_path / "tipos.json").write_text(json.dumps(TYPES), encoding="utf-8")
    assert read_routes(tmp_path / "rutas.json") == routes()
    assert read_vehicle_types(tmp_path / "tipos.json") == types()


def test_the_scenario_is_read_and_checked_against_the_case(tmp_path: Path) -> None:
    scenario = json.loads((FIXTURES / "scenario.json").read_text(encoding="utf-8"))
    (tmp_path / "escenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    assert read_scenario(tmp_path / "escenario.json", the_case()).scenario_id == "SCENARIO_DEMO_001"
    scenario["case_id"] = "OTRO"
    (tmp_path / "escenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    with pytest.raises(ScenarioInvalidError):
        read_scenario(tmp_path / "escenario.json", the_case())


def test_a_broken_routes_file_is_a_reading_error(tmp_path: Path) -> None:
    (tmp_path / "rutas.json").write_text("{", encoding="utf-8")
    with pytest.raises(CasoError, match="rutas"):
        read_routes(tmp_path / "rutas.json")


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"routes": {"N_S": []}}, "routes.N_S"),
        ({"routes": {"N_S": "demo_N demo_S"}}, "routes.N_S"),
        ({"routes": {}, "extra": 1}, "extra"),
        ({"schema_version": "2.0.0", "routes": {}}, "schema_version"),
        ({"routes": {"N_S": ["demo_N", " demo_S"]}}, "routes.N_S[1]"),
    ],
)
def test_a_malformed_route_table_is_rejected(
    tmp_path: Path, data: dict[str, Any], field: str
) -> None:
    (tmp_path / "rutas.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DemandInputError) as raised:
        read_routes(tmp_path / "rutas.json")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == field
    assert raised.value.message.startswith("las rutas no son válidas en ")


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"vclass": 3}, "types.car.vclass"),
        ({"attributes": {"length": "5"}}, "types.car.attributes.length"),
        ({"lat_alignment": "middle"}, "types.car.lat_alignment"),
        ({"gui_shape": "bus; rm"}, "types.car.gui_shape"),
        ({"color": "red"}, "types.car.color"),
        ({"speedFactor": 1.1}, "types.car.speedFactor"),
    ],
)
def test_a_malformed_vehicle_type_is_rejected(
    tmp_path: Path, change: dict[str, Any], field: str
) -> None:
    data = copy.deepcopy(TYPES)
    data["types"]["car"].update(change)
    (tmp_path / "tipos.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DemandInputError) as raised:
        read_vehicle_types(tmp_path / "tipos.json")
    assert raised.value.field == field
    assert raised.value.message.startswith("los tipos de vehículo no son válidos en ")


def test_a_number_that_is_not_finite_is_rejected_in_a_type() -> None:
    data = copy.deepcopy(TYPES)
    data["types"]["car"]["attributes"]["length"] = float("inf")
    with pytest.raises(ValueError, match="finite"):
        VehicleTypes.model_validate(data)


def test_the_admitted_numeric_attributes_are_those_of_f0_and_of_the_sublane_model() -> None:
    assert NUMERIC_ATTRIBUTES == (
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


def test_the_optional_type_attributes_are_accepted() -> None:
    vtype = types(
        {
            "types": {
                "car": {
                    "vclass": "motorcycle",
                    "attributes": dict.fromkeys(NUMERIC_ATTRIBUTES, 1.5),
                    "lat_alignment": "arbitrary",
                    "gui_shape": "passenger/van",
                    "color": "255,0,10",
                },
                "bus": {"vclass": "bus"},
            }
        }
    )
    assert type_issues(vtype, the_case()) == []


# --- TYPE-01 a TYPE-03 ----------------------------------------------------------------------


def test_every_class_of_the_case_needs_a_type() -> None:
    data = copy.deepcopy(TYPES)
    del data["types"]["bus"]
    issues = type_issues(types(data), the_case())
    assert rules(issues) == [("TYPE-01", "types")]
    assert "«bus»" in issues[0].message


def test_a_type_for_a_class_the_case_does_not_have_is_rejected() -> None:
    data = copy.deepcopy(TYPES)
    data["types"]["tram"] = {"vclass": "passenger"}
    issues = type_issues(types(data), the_case())
    assert rules(issues) == [("TYPE-01", "types.tram")]


@pytest.mark.parametrize("vclass", ["rail", "pedestrian", "ship", "Passenger", "auto"])
def test_a_class_that_is_not_a_street_vehicle_is_rejected(vclass: str) -> None:
    data = copy.deepcopy(TYPES)
    data["types"]["car"]["vclass"] = vclass
    issues = type_issues(types(data), the_case())
    assert rules(issues) == [("TYPE-02", "types.car.vclass")]
    assert f"«{vclass}»" in issues[0].message


def test_an_attribute_outside_the_list_is_rejected() -> None:
    data = copy.deepcopy(TYPES)
    data["types"]["car"]["attributes"]["sigma"] = 0.5
    issues = type_issues(types(data), the_case())
    assert rules(issues) == [("TYPE-03", "types.car.attributes.sigma")]
    assert "length" in issues[0].message


@pytest.mark.parametrize("value", [0, -2.5])
def test_an_attribute_that_is_not_positive_is_rejected(value: float) -> None:
    data = copy.deepcopy(TYPES)
    data["types"]["bus"]["attributes"]["length"] = value
    assert rules(type_issues(types(data), the_case())) == [
        ("TYPE-03", "types.bus.attributes.length")
    ]


def test_a_color_component_above_255_is_rejected() -> None:
    data = copy.deepcopy(TYPES)
    data["types"]["car"]["color"] = "10,256,0"
    assert rules(type_issues(types(data), the_case())) == [("TYPE-03", "types.car.color")]
    data["types"]["car"]["color"] = "255,255,255"
    assert type_issues(types(data), the_case()) == []


# --- ROUTE-01 a ROUTE-05 --------------------------------------------------------------------


def test_a_movement_with_vehicles_needs_a_route() -> None:
    table = RouteTable.model_validate({"routes": {"N_S": ["demo_N", "demo_S"]}})
    issues = check(table)
    assert rules(issues) == [("ROUTE-01", "routes")]
    assert "«E_W»" in issues[0].message


def test_a_movement_without_vehicles_needs_no_route() -> None:
    table = RouteTable.model_validate({"routes": {"N_S": ["demo_N", "demo_S"]}})
    assert check(table, classes={"N_S": frozenset({"car"}), "E_W": frozenset()}) == []
    assert check(table, classes={"N_S": frozenset({"car"})}) == []


def test_a_route_for_a_movement_the_case_does_not_have_is_rejected() -> None:
    issues = check(routes(X_Y=["demo_N", "demo_S"]))
    assert rules(issues) == [("ROUTE-01", "routes.X_Y")]


def test_a_street_that_does_not_exist_is_rejected_with_its_position() -> None:
    issues = check(routes(N_S=["demo_N", "demo_Z"]))
    assert rules(issues) == [("ROUTE-02", "routes.N_S[1]")]
    assert "«demo_Z» no existe" in issues[0].message


def test_an_internal_stretch_is_not_a_street() -> None:
    issues = check(routes(N_S=["demo_N", ":C_0", "demo_S"]))
    assert rules(issues) == [("ROUTE-02", "routes.N_S[1]")]
    assert "tramo interno" in issues[0].message


def test_an_unknown_street_skips_the_rules_that_depend_on_it() -> None:
    assert {issue.rule_id for issue in check(routes(N_S=["demo_Z", "demo_Y"]))} == {"ROUTE-02"}


def test_streets_that_are_not_connected_are_rejected() -> None:
    issues = check(routes(N_S=["demo_N", "demo_S", "demo_W"]))
    assert rules(issues) == [("ROUTE-03", "routes.N_S[2]")]
    assert "«demo_S» no está conectada con «demo_W»" in issues[0].message


def test_a_route_that_does_not_cross_from_the_entry_to_an_exit_is_rejected() -> None:
    issues = check(routes(N_S=["demo_E", "demo_W"]))
    assert rules(issues) == [("ROUTE-04", "routes.N_S")]
    assert "«demo_N»" in issues[0].message
    assert "demo_S" in issues[0].message


def test_entry_lanes_that_are_not_on_one_street_of_the_network_are_reported() -> None:
    case = the_case()
    data = case.model_dump(mode="json")
    data["movements"][0]["incoming_lanes"] = ["demo_N_0", "demo_E_0"]
    issues = route_issues(routes(), parse_case(data), graph(), BOTH, types())
    assert rules(issues) == [("ROUTE-04", "routes.N_S")]
    assert "no están todos en la red ni en una misma calle" in issues[0].message
    assert "None" not in issues[0].message


def test_a_route_with_only_the_entry_street_does_not_cross() -> None:
    assert rules(check(routes(N_S=["demo_N"]))) == [("ROUTE-04", "routes.N_S")]


UPSTREAM = (
    '<edge id="demo_NN" from="X" to="N"><lane id="demo_NN_0" index="0" speed="1" '
    'length="9" shape="0,0 1,1"/></edge>\n'
    '<connection from="demo_NN" to="demo_N" fromLane="0" toLane="0" dir="s" state="M"/>\n'
    "</net>"
)
ENTRY_LANE = '<lane id="demo_N_0" index="0"'
# Calle de entrada con dos carriles: el del movimiento (demo_N_0) solo admite autos.
TWO_ENTRY_LANES = (
    '<lane id="demo_N_1" index="1" speed="1" length="9" shape="0,0 1,1"/>\n'
    + ENTRY_LANE
    + ' allow="passenger"'
)


def test_a_route_that_starts_before_the_entry_street_is_accepted(tmp_path: Path) -> None:
    net = patched_graph(tmp_path, "</net>", UPSTREAM)
    assert check(routes(N_S=["demo_NN", "demo_N", "demo_S"]), net=net) == []


def test_a_class_that_cannot_use_a_street_of_the_route_is_rejected(tmp_path: Path) -> None:
    net = patched_graph(
        tmp_path, '<lane id="demo_S_0" index="0"', '<lane id="demo_S_0" index="0" disallow="bus"'
    )
    issues = check(net=net)
    assert rules(issues) == [("ROUTE-05", "routes.N_S")]
    assert "«bus» (bus)" in issues[0].message
    assert "demo_S" in issues[0].message


def test_a_class_that_cannot_use_the_entry_lane_is_rejected(tmp_path: Path) -> None:
    net = patched_graph(tmp_path, ENTRY_LANE, TWO_ENTRY_LANES)
    issues = check(net=net)
    assert rules(issues) == [("ROUTE-05", "routes.N_S")]
    assert "demo_N_0" in issues[0].message
    assert "demo_N," not in issues[0].message


def test_the_entry_lane_is_not_checked_when_the_route_starts_before_it(tmp_path: Path) -> None:
    # La ruta sale en demo_NN: SUMO elige el carril, y el bus puede usar demo_N_1.
    path = tmp_path / "red.net.xml"
    text = DEMO_NET.read_text(encoding="utf-8")
    path.write_text(
        text.replace(ENTRY_LANE, TWO_ENTRY_LANES).replace("</net>", UPSTREAM), encoding="utf-8"
    )
    net = read_network_graph(path)
    assert check(routes(N_S=["demo_NN", "demo_N", "demo_S"]), net=net) == []
    assert rules(check(net=net)) == [("ROUTE-05", "routes.N_S")]


def test_only_classes_with_vehicles_are_checked(tmp_path: Path) -> None:
    net = patched_graph(
        tmp_path, '<lane id="demo_S_0" index="0"', '<lane id="demo_S_0" index="0" disallow="bus"'
    )
    assert check(net=net, classes={"N_S": frozenset({"car"}), "E_W": frozenset({"car"})}) == []


def test_a_class_without_a_type_is_left_to_the_type_rules() -> None:
    data = copy.deepcopy(TYPES)
    del data["types"]["bus"]
    assert check(vehicle_types=types(data)) == []


def test_the_entry_street_is_the_street_of_the_entry_lanes() -> None:
    net = graph()
    assert approach_edge(["demo_N_0"], net) == "demo_N"
    assert approach_edge(["demo_N_0", "demo_E_0"], net) is None
    assert approach_edge(["demo_N_9"], net) is None
    assert approach_edge(["demo_N_0", "demo_N_9"], net) is None


def test_problems_of_several_movements_are_all_reported() -> None:
    issues = check(routes(N_S=["demo_N", "demo_Z"], E_W=["demo_N", "demo_S"]))
    assert rules(issues) == [("ROUTE-02", "routes.N_S[1]"), ("ROUTE-04", "routes.E_W")]
