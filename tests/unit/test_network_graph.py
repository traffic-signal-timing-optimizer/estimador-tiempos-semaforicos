"""Grafo de calles de la red (DEV06 F2): calles, tramos internos, carriles y conexiones."""

import gzip
from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.network_graph import Lane, read_network_graph

DEMO_NET = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo" / "demo.net.xml"


def test_the_demo_network_has_four_streets_and_two_internal_stretches() -> None:
    graph = read_network_graph(DEMO_NET)
    assert graph.edges == {"demo_E", "demo_N", "demo_S", "demo_W"}
    assert graph.internal_edges == {":C_0", ":C_1"}


def test_only_the_lanes_of_streets_are_kept() -> None:
    graph = read_network_graph(DEMO_NET)
    assert set(graph.lanes) == {"demo_E_0", "demo_N_0", "demo_S_0", "demo_W_0"}
    assert graph.lanes["demo_N_0"] == Lane("demo_N_0", "demo_N", 0, None, None)


def test_the_connections_between_streets_skip_the_internal_ones() -> None:
    assert read_network_graph(DEMO_NET).connections == {
        ("demo_N", "demo_S"),
        ("demo_E", "demo_W"),
    }


def patched(tmp_path: Path, old: str, new: str, *, compressed: bool = False) -> Path:
    text = DEMO_NET.read_text(encoding="utf-8")
    assert text.count(old) == 1
    data = text.replace(old, new).encode("utf-8")
    path = tmp_path / ("red.net.xml.gz" if compressed else "red.net.xml")
    path.write_bytes(gzip.compress(data) if compressed else data)
    return path


def test_the_lanes_of_a_street_come_from_right_to_left(tmp_path: Path) -> None:
    lane = '<lane id="demo_N_0" index="0"'
    path = patched(
        tmp_path,
        lane,
        '<lane id="demo_N_1" index="1" speed="13.89" length="92.80" shape="0,0 1,1"/>\n' + lane,
    )
    assert [lane.lane_id for lane in read_network_graph(path).lanes_of("demo_N")] == [
        "demo_N_0",
        "demo_N_1",
    ]


def test_a_street_without_lanes_or_unknown_has_none() -> None:
    assert read_network_graph(DEMO_NET).lanes_of("no_existe") == ()


def test_the_permissions_of_a_lane_are_kept(tmp_path: Path) -> None:
    path = patched(
        tmp_path, '<lane id="demo_N_0" index="0"', '<lane id="demo_N_0" index="0" allow="bus"'
    )
    lane = read_network_graph(path).lanes["demo_N_0"]
    assert (lane.allow, lane.disallow) == ("bus", None)
    assert lane.permits("bus")
    assert not lane.permits("passenger")


def test_a_lane_that_disallows_a_class_does_not_permit_it(tmp_path: Path) -> None:
    path = patched(
        tmp_path, '<lane id="demo_N_0" index="0"', '<lane id="demo_N_0" index="0" disallow="bus"'
    )
    lane = read_network_graph(path).lanes["demo_N_0"]
    assert not lane.permits("bus")
    assert lane.permits("passenger")


def test_a_compressed_network_is_read(tmp_path: Path) -> None:
    path = patched(tmp_path, 'id="demo_W"', 'id="demo_W"', compressed=True)
    assert read_network_graph(path).edges == read_network_graph(DEMO_NET).edges


def test_a_network_that_is_not_xml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "red.net.xml"
    path.write_text("<net><edge", encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        read_network_graph(path)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_a_file_that_is_not_a_network_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "red.net.xml"
    path.write_text("<routes/>", encoding="utf-8")
    with pytest.raises(CasoError, match="raíz"):
        read_network_graph(path)


def test_a_lane_without_index_is_rejected(tmp_path: Path) -> None:
    path = patched(tmp_path, '<lane id="demo_N_0" index="0"', '<lane id="demo_N_0"')
    with pytest.raises(CasoError, match="index"):
        read_network_graph(path)


def test_a_network_over_the_size_limit_is_rejected() -> None:
    with pytest.raises(CasoError, match="límite"):
        read_network_graph(DEMO_NET, max_bytes=100)
