"""Pruebas del mapa de la red: qué enlace del semáforo controla cada movimiento (DEV03, F1)."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.network_map import NetworkMap, build_network_map
from semaforo.dominio.case import Case, parse_case

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_NET = FIXTURES / "sumo" / "demo" / "demo.net.xml"
DEMO_CASE = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
# Un giro con punto de espera: el enlace 0 entra al cruce y el 1 es la señal de espera.
WAITING_NET = """<net version="1.20">
    <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0"/></edge>
    <edge id="a"><lane id="a_0" index="0"/></edge>
    <edge id="b"><lane id="b_0" index="0"/></edge>
    <connection from="a" to="b" fromLane="0" toLane="0" tl="T" linkIndex="0" via=":j_0_0" dir="l"/>
    <connection from=":j_0" to="b" fromLane="0" toLane="0" tl="T" linkIndex="1"/>
    <tlLogic id="T" type="static" programID="0" offset="0">
        <phase duration="10" state="Gr"/>
    </tlLogic>
</net>"""
ONE_MOVEMENT = {
    "id": "G",
    "approach_id": "a",
    "incoming_lanes": ["a_0"],
    "outgoing_edges": ["b"],
    "tls_id": "T",
    "link_indices": [0],
    "flow_domain_vph": {"min": 0, "max": 100},
}


def case_with(movements: list[dict[str, Any]], classes: list[str] | None = None) -> Case:
    """Caso del fixture de demostración con otros movimientos (y clases, si se indican)."""
    data = copy.deepcopy(DEMO_CASE)
    data["movements"] = movements
    if classes is not None:
        data["vehicle_classes"] = classes
    return parse_case(data)


def demo_movements() -> list[dict[str, Any]]:
    return copy.deepcopy(DEMO_CASE["movements"])


def write_net(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "red.net.xml"
    path.write_text(body, encoding="utf-8")
    return path


def rules_and_fields(network_map: NetworkMap) -> list[tuple[str, str | None]]:
    return [(issue.rule_id, issue.field) for issue in network_map.issues]


def test_the_demo_fixture_maps_without_issues() -> None:
    network_map = build_network_map(DEMO_NET, case_with(demo_movements()))
    assert network_map.is_complete
    assert network_map.tls_id == "DEMO_TLS"
    assert network_map.link_count == 2
    assert [(m.movement_id, m.link_indices) for m in network_map.movements] == [
        ("N_S", (0,)),
        ("E_W", (1,)),
    ]
    assert network_map.movements[0].lanes == ("demo_N_0",)
    assert network_map.movements[0].edges == ("demo_S",)


def test_a_waiting_point_belongs_to_the_movement_that_enters_through_it(tmp_path: Path) -> None:
    network_map = build_network_map(
        write_net(tmp_path, WAITING_NET), case_with([ONE_MOVEMENT], ["passenger"])
    )
    assert network_map.is_complete
    assert network_map.movements[0].waiting_link_indices == (1,)


@pytest.mark.parametrize(
    ("body", "description"),
    [
        ('<net version="1.20"></net>', "sin semáforos"),
        (
            DEMO_NET.read_text(encoding="utf-8").replace(
                "</net>",
                '<tlLogic id="OTRO" type="static" programID="0" offset="0">'
                '<phase duration="5" state="rr"/></tlLogic></net>',
            ),
            "con dos semáforos",
        ),
    ],
)
def test_a_network_without_exactly_one_traffic_light_is_rejected(
    tmp_path: Path, body: str, description: str
) -> None:
    with pytest.raises(CasoError) as raised:
        build_network_map(write_net(tmp_path, body), case_with(demo_movements()))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA, description


def test_a_declared_link_without_connection_is_reported() -> None:
    movements = demo_movements()
    movements[0]["link_indices"] = [0, 5]
    network_map = build_network_map(DEMO_NET, case_with(movements))
    assert ("MAP-02", "movements[0].link_indices[1]") in rules_and_fields(network_map)


def test_a_connection_to_an_undeclared_street_is_reported() -> None:
    movements = demo_movements()
    movements[0]["outgoing_edges"] = ["demo_W"]
    network_map = build_network_map(DEMO_NET, case_with(movements))
    assert ("MAP-02", "movements[0].outgoing_edges") in rules_and_fields(network_map)


def test_a_declared_lane_that_no_connection_uses_is_reported() -> None:
    movements = demo_movements()
    movements[0]["incoming_lanes"] = ["demo_S_0"]
    network_map = build_network_map(DEMO_NET, case_with(movements))
    fields = rules_and_fields(network_map)
    assert ("MAP-02", "movements[0].incoming_lanes") in fields
    assert ("MAP-02", "movements[0].incoming_lanes[0]") in fields


def test_a_link_that_no_movement_claims_is_reported() -> None:
    network_map = build_network_map(DEMO_NET, case_with(demo_movements()[:1]))
    [issue] = network_map.issues
    assert (issue.rule_id, issue.field) == ("MAP-01", None)
    assert "el enlace 1" in issue.message


def test_a_link_claimed_by_two_movements_is_reported() -> None:
    twin = copy.deepcopy(demo_movements()[0])
    twin["id"] = "N_S_BIS"
    network_map = build_network_map(DEMO_NET, case_with([*demo_movements(), twin]))
    [issue] = network_map.issues
    assert (issue.rule_id, issue.field) == ("MAP-01", "movements[2]")
    assert "ya pertenece al movimiento 'N_S'" in issue.message


def test_a_movement_declared_on_another_traffic_light_is_reported() -> None:
    movements = demo_movements()
    movements[0]["tls_id"] = "OTRO"
    network_map = build_network_map(DEMO_NET, case_with(movements))
    assert ("MAP-01", "movements[0].tls_id") in rules_and_fields(network_map)
