"""Pruebas de la tabla de movimientos por carril y clase (QA23)."""

from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.movements import read_movements
from semaforo.caso.permissions import permits

DEMO_NET = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo" / "demo.net.xml"
NET = """<net version="1.20">
    <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0"/></edge>
    <edge id="a">
        <lane id="a_0" index="0" disallow="bus"/><lane id="a_1" index="1" allow="bus"/>
    </edge>
    <edge id="b"><lane id="b_0" index="0"/></edge>
    <edge id="c"><lane id="c_0" index="0" disallow="bus"/></edge>
    <connection from="a" to="b" fromLane="0" toLane="0" tl="T" linkIndex="1" dir="l"/>
    <connection from="a" to="b" fromLane="1" toLane="0" tl="T" linkIndex="0" dir="s"/>
    <connection from="a" to="c" fromLane="1" toLane="0" tl="T" linkIndex="2" dir="r"/>
    <connection from="b" to="c" fromLane="0" toLane="0"/>
    <connection from=":j_0" to="b" fromLane="0" toLane="0" tl="T" linkIndex="5"/>
</net>"""


@pytest.mark.parametrize(
    ("allow", "disallow", "vclass", "expected"),
    [
        (None, None, "bus", True),
        ("bus", None, "bus", True),
        ("bus", None, "passenger", False),
        ("all", None, "passenger", True),
        (None, "bus tram", "bus", False),
        (None, "bus", "passenger", True),
        (None, "all", "passenger", False),
    ],
)
def test_permits(allow: str | None, disallow: str | None, vclass: str, *, expected: bool) -> None:
    assert permits(allow, disallow, vclass) is expected


def test_reads_the_movements_of_the_demo_fixture() -> None:
    movements = read_movements(DEMO_NET, ["passenger", "bus"])
    assert [(m.id, m.link_index, m.from_edge, m.to_edge, m.direction) for m in movements] == [
        ("M01", 0, "demo_N", "demo_S", "recto"),
        ("M02", 1, "demo_E", "demo_W", "recto"),
    ]
    assert all(m.classes == ["passenger", "bus"] for m in movements)
    assert movements[0].tls_id == "DEMO_TLS"


def test_lanes_turns_and_classes_per_movement(tmp_path: Path) -> None:
    path = tmp_path / "net.xml"
    path.write_text(NET, encoding="utf-8")
    movements = read_movements(path, ["passenger", "bus"])
    found = [
        (m.id, m.link_index, m.from_lane, m.to_lane, m.direction, m.classes) for m in movements
    ]
    assert found == [
        ("M01", 0, 1, 0, "recto", ["bus"]),
        ("M02", 1, 0, 0, "izquierda", ["passenger"]),
        ("M03", 2, 1, 0, "derecha", []),
    ]
    # La conexión interna con semáforo no es de ningún movimiento: ninguna la tiene como vía.
    assert all(m.waiting_link_index is None for m in movements)


def test_the_waiting_point_signal_belongs_to_its_movement(tmp_path: Path) -> None:
    # Como escribe netconvert un giro con linkIndex2: la conexión del carril de entrada va por la
    # vía :j_0_0, y la conexión que sale de esa vía hacia el punto de espera tiene su propia señal.
    path = tmp_path / "net.xml"
    path.write_text(NET.replace('dir="l"', 'dir="l" via=":j_0_0"'), encoding="utf-8")
    movements = read_movements(path, ["passenger", "bus"])
    assert [(m.id, m.link_index, m.waiting_link_index) for m in movements] == [
        ("M01", 0, None),
        ("M02", 1, 5),
        ("M03", 2, None),
    ]


def test_an_unknown_turn_code_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "net.xml"
    path.write_text(NET.replace('dir="r"', 'dir="z"'), encoding="utf-8")
    assert read_movements(path, ["passenger"])[2].direction == "z"


def test_rejects_an_invalid_net(tmp_path: Path) -> None:
    path = tmp_path / "net.xml"
    path.write_text("<net><connection", encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        read_movements(path, ["passenger"])
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
