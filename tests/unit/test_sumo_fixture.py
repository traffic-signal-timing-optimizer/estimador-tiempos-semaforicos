"""Comprueba que el fixture SUMO mínimo es coherente con los fixtures contractuales.

La red de ``tests/fixtures/sumo/demo`` reproduce el caso sintético de ``case.json`` (semáforo
DEMO_TLS, movimientos N_S y E_W), el plan de ``response.json`` y los aforos de ``aforos.csv``.
No representa Frutales.
"""

import csv
import json
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from xml.etree import ElementTree as ET

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO = FIXTURES / "sumo" / "demo"
INVALID = FIXTURES / "sumo" / "invalid"
DEMO_FILES = [
    "demo.nod.xml",
    "demo.edg.xml",
    "demo.con.xml",
    "demo.tll.xml",
    "demo.net.xml",
    "demo.rou.xml",
    "demo.sumocfg",
]
SECONDS_PER_HOUR = 3600


def _json(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def _root(path: Path) -> ET.Element:
    # XML del propio repositorio, no una entrada externa.
    return ET.parse(path).getroot()  # noqa: S314


def _attr(element: ET.Element, name: str) -> str:
    value = element.get(name)
    assert value is not None, f"falta {name} en <{element.tag}>"
    return value


CASE = _json("case.json")


def test_demo_files_exist_and_have_no_outputs() -> None:
    assert sorted(path.name for path in DEMO.iterdir()) == sorted(DEMO_FILES)


def test_signal_program_matches_case_and_example_plan() -> None:
    tls_id = CASE["movements"][0]["tls_id"]
    logics = [e for e in _root(DEMO / "demo.net.xml").iter("tlLogic") if _attr(e, "id") == tls_id]
    assert len(logics) == 1
    assert _attr(logics[0], "type") == "static"
    phases = list(logics[0].iter("phase"))
    assert [_attr(p, "state") for p in phases] == [s["states"][0]["state"] for s in CASE["slots"]]
    plan = _json("response.json")["plan"]["slot_durations_s"]
    assert [float(_attr(p, "duration")) for p in phases] == [
        float(plan[s["id"]]) for s in CASE["slots"]
    ]


def test_connections_match_case_movements() -> None:
    regular = [
        c
        for c in _root(DEMO / "demo.net.xml").iter("connection")
        if not _attr(c, "from").startswith(":")
    ]
    assert len(regular) == len(CASE["movements"])
    for movement in CASE["movements"]:
        edge, lane_index = movement["incoming_lanes"][0].rsplit("_", 1)
        matches = [
            c for c in regular if _attr(c, "from") == edge and _attr(c, "fromLane") == lane_index
        ]
        assert len(matches) == 1, movement["id"]
        assert _attr(matches[0], "to") in movement["outgoing_edges"]
        assert _attr(matches[0], "tl") == movement["tls_id"]
        assert int(_attr(matches[0], "linkIndex")) in movement["link_indices"]


def test_flows_reproduce_example_counts() -> None:
    with (FIXTURES / "aforos.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {
        (r["movement_id"], r["vehicle_class"]): int(r["count"]) for r in rows if int(r["count"]) > 0
    }
    flows = list(_root(DEMO / "demo.rou.xml").iter("flow"))
    actual = {(_attr(f, "route"), _attr(f, "type")): int(_attr(f, "number")) for f in flows}
    assert actual == expected
    window = (
        datetime.fromisoformat(rows[0]["end"]) - datetime.fromisoformat(rows[0]["start"])
    ).total_seconds()
    assert all(float(_attr(f, "end")) - float(_attr(f, "begin")) == window for f in flows)
    normalization = _json("expected_normalization.json")
    for movement in ("N_S", "E_W"):
        vehicles = sum(count for (route, _), count in actual.items() if route == movement)
        assert vehicles * SECONDS_PER_HOUR / window == normalization[movement]["flow_vph"]


def test_config_uses_relative_inputs_and_outputs() -> None:
    config = _root(DEMO / "demo.sumocfg")
    values = {e.tag: _attr(e, "value") for e in config.iter() if e.get("value") is not None}
    assert values["net-file"] == "demo.net.xml"
    assert values["route-files"] == "demo.rou.xml"
    assert float(values["step-length"]) == CASE["tick_s"]
    assert "seed" in values
    for key in ("tripinfo-output", "statistic-output"):
        assert not PureWindowsPath(values[key]).is_absolute(), key


def test_truncated_net_is_not_well_formed() -> None:
    with pytest.raises(ET.ParseError):
        _root(INVALID / "truncated_net" / "demo.net.xml")


def test_missing_edge_route_references_unknown_edge() -> None:
    folder = INVALID / "missing_edge"
    network_edges = {_attr(e, "id") for e in _root(folder / "demo.net.xml").iter("edge")}
    route_edges = {
        edge
        for route in _root(folder / "demo.rou.xml").iter("route")
        for edge in _attr(route, "edges").split()
    }
    assert route_edges - network_edges == {"demo_X"}


def test_absolute_output_points_to_a_directory_that_does_not_exist() -> None:
    # Esta variante nunca se ejecuta con SUMO: su ruta absoluta apunta fuera del repositorio.
    output = next(_root(INVALID / "absolute_output" / "demo.sumocfg").iter("tripinfo-output"))
    path = _attr(output, "value")
    assert PureWindowsPath(path).is_absolute()
    assert not Path(path.rsplit("\\", 1)[0]).exists()
