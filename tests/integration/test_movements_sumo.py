"""La señal del punto de espera (``linkIndex2``) queda en su movimiento (QA23 y QA24).

Genera con ``netconvert`` un cruce sintético con un giro a la izquierda que entra con su enlace y
espera dentro del cruce hasta su propia señal, como la flecha de Javier Prado. Fija el formato de
SUMO 1.27.1 que lee la tabla de movimientos. Se salta si SUMO no está instalado (``SUMO_HOME``).
"""

import subprocess
from pathlib import Path

import pytest

from semaforo.caso.movements import read_movements

pytestmark = pytest.mark.sumo

NODES = """<nodes>
    <node id="W" x="-100" y="0"/><node id="E" x="100" y="0"/><node id="N" x="0" y="100"/>
    <node id="C" x="0" y="0" type="traffic_light" tl="T"/>
</nodes>"""
EDGES = """<edges>
    <edge id="in_W" from="W" to="C" numLanes="1" speed="13.89"/>
    <edge id="in_E" from="E" to="C" numLanes="1" speed="13.89"/>
    <edge id="out_E" from="C" to="E" numLanes="1" speed="13.89"/>
    <edge id="out_W" from="C" to="W" numLanes="1" speed="13.89"/>
    <edge id="out_N" from="C" to="N" numLanes="1" speed="13.89"/>
</edges>"""
CONNECTIONS = """<connections>
    <connection from="in_W" to="out_E" fromLane="0" toLane="0"/>
    <connection from="in_W" to="out_N" fromLane="0" toLane="0"/>
    <connection from="in_E" to="out_W" fromLane="0" toLane="0"/>
</connections>"""
# Enlaces: 0 recto desde el oeste, 1 entrada del giro, 2 recto desde el este, 3 su punto de espera.
PROGRAM = """<tlLogics>
    <tlLogic id="T" type="static" programID="0" offset="0">
        <phase duration="30" state="GgGr"/>
        <phase duration="3" state="Ggyr"/>
        <phase duration="15" state="GGrG"/>
        <phase duration="3" state="yyry"/>
    </tlLogic>
    <connection from="in_W" to="out_E" fromLane="0" toLane="0" tl="T" linkIndex="0"/>
    <connection from="in_W" to="out_N" fromLane="0" toLane="0" tl="T" linkIndex="1" linkIndex2="3"/>
    <connection from="in_E" to="out_W" fromLane="0" toLane="0" tl="T" linkIndex="2"/>
</tlLogics>"""


def test_the_waiting_point_signal_of_a_netconvert_net(tmp_path: Path, sumo_binary: Path) -> None:
    files = {"c.nod.xml": NODES, "c.edg.xml": EDGES, "c.con.xml": CONNECTIONS, "c.tll.xml": PROGRAM}
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    netconvert = sumo_binary.with_name(sumo_binary.name.replace("sumo", "netconvert"))
    result = subprocess.run(  # noqa: S603
        [
            str(netconvert),
            *("-n", "c.nod.xml", "-e", "c.edg.xml", "-x", "c.con.xml", "-i", "c.tll.xml"),
            *("--no-turnarounds", "true", "-o", "c.net.xml"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    movements = read_movements(tmp_path / "c.net.xml", ["passenger"])
    found = [(m.from_edge, m.to_edge, m.link_index, m.waiting_link_index) for m in movements]
    assert found == [
        ("in_W", "out_E", 0, None),
        ("in_W", "out_N", 1, 3),
        ("in_E", "out_W", 2, None),
    ]
