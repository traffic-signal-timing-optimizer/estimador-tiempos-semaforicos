"""Pruebas del inventario de la red SUMO: conteos, semáforos y hallazgos de sus programas."""

import gzip
from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.inventory import read_network_inventory
from semaforo.caso.inventory_models import NetworkInventory

SUMO_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sumo"
DEMO_NET = SUMO_FIXTURES / "demo" / "demo.net.xml"
TLS = "T1"


def edge(name: str, lanes: int = 1, *, internal: bool = False) -> str:
    function = ' function="internal"' if internal else ""
    body = "".join(f'<lane id="{name}_{i}" index="{i}"/>' for i in range(lanes))
    return f'<edge id="{name}"{function}>{body}</edge>'


def junction(name: str, kind: str = "priority") -> str:
    return f'<junction id="{name}" type="{kind}"/>'


def connection(origin: str, link: int | None = None, tls: str | None = None) -> str:
    attributes = f'from="{origin}" to="z"'
    if tls is not None:
        attributes += f' tl="{tls}"'
    if link is not None:
        attributes += f' linkIndex="{link}"'
    return f"<connection {attributes}/>"


def phase(
    duration: str, state: str, *, min_dur: str | None = None, max_dur: str | None = None
) -> str:
    extra = (f' minDur="{min_dur}"' if min_dur else "") + (
        f' maxDur="{max_dur}"' if max_dur else ""
    )
    return f'<phase duration="{duration}" state="{state}"{extra}/>'


def logic(
    program: str, *phases: str, tls: str = TLS, kind: str = "static", params: str = ""
) -> str:
    return (
        f'<tlLogic id="{tls}" type="{kind}" programID="{program}" offset="0">'
        f"{params}{''.join(phases)}</tlLogic>"
    )


def net(*parts: str) -> str:
    return f'<net version="1.20">{"".join(parts)}</net>'


def links(count: int = 2, tls: str = TLS) -> list[str]:
    return [connection("a", index, tls) for index in range(count)]


def inventory_of(tmp_path: Path, xml: str) -> NetworkInventory:
    path = tmp_path / "net.xml"
    path.write_text(xml, encoding="utf-8")
    return read_network_inventory(path)


def test_counts_the_demo_fixture() -> None:
    counts = read_network_inventory(DEMO_NET).counts
    assert counts.junctions == 5
    assert counts.junction_types == {"dead_end": 4, "traffic_light": 1}
    assert (counts.edges_total, counts.edges_internal) == (6, 2)
    assert (counts.lanes_total, counts.lanes_internal) == (6, 2)
    assert (counts.connections_total, counts.connections_from_internal) == (4, 2)


def test_describes_the_demo_traffic_light() -> None:
    inventory = read_network_inventory(DEMO_NET)
    assert inventory.net_version == "1.20"
    assert inventory.findings == []
    (tls,) = inventory.traffic_lights
    assert (tls.id, tls.link_count, tls.connection_count) == ("DEMO_TLS", 2, 2)
    assert tls.active_program_id == "demo"
    (program,) = tls.programs
    assert (program.program_id, program.type, program.offset_s) == ("demo", "static", 0.0)
    assert [p.duration_s for p in program.phases] == [30, 3, 1, 22, 3, 1]
    assert [p.state for p in program.phases] == ["Gr", "yr", "rr", "rG", "ry", "rr"]
    assert [p.index for p in program.phases] == [0, 1, 2, 3, 4, 5]
    assert all(p.min_dur_s is None and p.max_dur_s is None for p in program.phases)


def test_a_compressed_net_gives_the_same_inventory(tmp_path: Path) -> None:
    compressed = tmp_path / "demo.net.xml.gz"
    compressed.write_bytes(gzip.compress(DEMO_NET.read_bytes()))
    assert read_network_inventory(compressed) == read_network_inventory(DEMO_NET)


def test_compression_is_detected_by_content_not_by_name(tmp_path: Path) -> None:
    disguised = tmp_path / "net.xml"
    disguised.write_bytes(gzip.compress(DEMO_NET.read_bytes()))
    plain = tmp_path / "net.gz"
    plain.write_bytes(DEMO_NET.read_bytes())
    expected = read_network_inventory(DEMO_NET)
    assert read_network_inventory(disguised) == expected
    assert read_network_inventory(plain) == expected


def test_separates_internal_from_regular_elements(tmp_path: Path) -> None:
    xml = net(
        edge("a", 2),
        edge("b"),
        edge(":j_0", 1, internal=True),
        edge(":j_1", 3, internal=True),
        junction("j"),
        junction("k", "traffic_light"),
        junction("m"),
        connection("a"),
        connection(":j_0"),
        connection(":j_1"),
    )
    counts = inventory_of(tmp_path, xml).counts
    assert (counts.edges_total, counts.edges_internal) == (4, 2)
    assert (counts.lanes_total, counts.lanes_internal) == (7, 4)
    assert (counts.connections_total, counts.connections_from_internal) == (3, 2)
    assert counts.junction_types == {"priority": 2, "traffic_light": 1}
    assert counts.junctions == 3


def test_phases_outside_their_limits_are_reported(tmp_path: Path) -> None:
    phases = [
        phase("9", "GG", min_dur="7", max_dur="50"),
        phase("6", "GG", min_dur="7", max_dur="50"),
        phase("7", "GG", min_dur="7", max_dur="50"),
        phase("60", "GG", min_dur="7", max_dur="50"),
        phase("3", "yy"),
        phase("50", "GG", min_dur="7", max_dur="50"),
    ]
    inventory = inventory_of(tmp_path, net(*links(), logic("0", *phases, kind="actuated")))
    found = [(f.code, f.tls_id, f.program_id, f.phase_index) for f in inventory.findings]
    assert found == [
        ("PHASE_DURATION_BELOW_MIN", TLS, "0", 1),
        ("PHASE_DURATION_ABOVE_MAX", TLS, "0", 3),
    ]
    assert inventory.traffic_lights[0].programs[0].type == "actuated"
    assert inventory.traffic_lights[0].programs[0].phases[0].min_dur_s == 7
    assert inventory.traffic_lights[0].programs[0].phases[0].max_dur_s == 50


def test_several_programs_are_listed_and_the_last_one_is_the_active_one(tmp_path: Path) -> None:
    first = logic("first", phase("10", "GG"))
    second = logic("second", phase("20", "GG"))
    inventory = inventory_of(tmp_path, net(*links(), first, second))
    (tls,) = inventory.traffic_lights
    assert [p.program_id for p in tls.programs] == ["first", "second"]
    assert tls.active_program_id == "second"
    assert [(f.code, f.tls_id) for f in inventory.findings] == [("MULTIPLE_PROGRAMS", TLS)]


def test_a_state_that_does_not_cover_every_link_is_reported(tmp_path: Path) -> None:
    inventory = inventory_of(tmp_path, net(*links(3), logic("0", phase("10", "Gr"))))
    assert [(f.code, f.phase_index) for f in inventory.findings] == [("STATE_LENGTH_MISMATCH", 0)]


def test_link_count_is_the_highest_link_index_plus_one(tmp_path: Path) -> None:
    connections = [connection("a", index, TLS) for index in (0, 0, 3)]
    (tls,) = inventory_of(
        tmp_path, net(*connections, logic("0", phase("10", "GGGG")))
    ).traffic_lights
    assert (tls.link_count, tls.connection_count) == (4, 3)


def test_a_controlled_connection_without_program_is_reported(tmp_path: Path) -> None:
    inventory = inventory_of(tmp_path, net(*links(), logic("0", phase("10", "GG"), tls="OTHER")))
    by_id = {t.id: t for t in inventory.traffic_lights}
    assert by_id[TLS].programs == []
    assert by_id[TLS].active_program_id is None
    assert by_id["OTHER"].link_count == 0
    codes = {(f.code, f.tls_id) for f in inventory.findings}
    assert ("TLS_WITHOUT_PROGRAM", TLS) in codes


def test_program_parameters_are_kept(tmp_path: Path) -> None:
    params = '<param key="detector-gap" value="3"/><param key="max-gap" value="5"/>'
    xml = net(*links(), logic("0", phase("10", "GG"), kind="actuated", params=params))
    program = inventory_of(tmp_path, xml).traffic_lights[0].programs[0]
    assert program.params == {"detector-gap": "3", "max-gap": "5"}


def test_the_inventory_is_deterministic_and_round_trips_through_json(tmp_path: Path) -> None:
    first = read_network_inventory(DEMO_NET)
    second = read_network_inventory(DEMO_NET)
    assert first.model_dump_json() == second.model_dump_json()
    assert NetworkInventory.model_validate_json(first.model_dump_json()) == first


def test_reading_does_not_modify_the_file(tmp_path: Path) -> None:
    path = tmp_path / "net.xml"
    path.write_bytes(DEMO_NET.read_bytes())
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    read_network_inventory(path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


BAD_TLS_LINK = f'<connection from="a" to="z" tl="{TLS}"/>'
INVALID_NETS = {
    "truncated": "<net><edge id='a'>",
    "empty": "",
    "wrong-root": "<otra/>",
    "entity": '<?xml version="1.0"?><!DOCTYPE net [<!ENTITY x "y">]><net version="&x;"/>',
    "doctype": '<?xml version="1.0"?><!DOCTYPE net><net/>',
    "duration-not-a-number": net(*links(), logic("0", phase("abc", "GG"))),
    "duration-nan": net(*links(), logic("0", phase("nan", "GG"))),
    "duration-missing": net(*links(), logic("0", '<phase state="GG"/>')),
    "min-dur-infinite": net(*links(), logic("0", phase("5", "GG", min_dur="inf"))),
    "state-missing": net(*links(), logic("0", '<phase duration="5"/>')),
    "link-index-missing": net(BAD_TLS_LINK, logic("0", phase("5", "GG"))),
    "link-index-not-an-integer": net(connection("a", None, TLS).replace("/>", ' linkIndex="x"/>')),
    "logic-without-id": net('<tlLogic type="static" programID="0" offset="0"/>'),
    "offset-not-a-number": net('<tlLogic id="T" type="static" programID="0" offset="x"/>'),
}


@pytest.mark.parametrize("xml", INVALID_NETS.values(), ids=INVALID_NETS.keys())
def test_rejects_invalid_or_dangerous_nets(tmp_path: Path, xml: str) -> None:
    path = tmp_path / "net.xml"
    path.write_text(xml, encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        read_network_inventory(path)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert str(tmp_path) not in str(raised.value)


def test_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        read_network_inventory(tmp_path / "absent.net.xml")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "absent.net.xml"


def test_rejects_a_truncated_or_corrupt_compressed_file(tmp_path: Path) -> None:
    data = gzip.compress(DEMO_NET.read_bytes())
    cases = {"truncated.gz": data[: len(data) // 2], "corrupt.gz": data[:10] + b"\x00" * 40}
    for name, content in cases.items():
        path = tmp_path / name
        path.write_bytes(content)
        with pytest.raises(CasoError) as raised:
            read_network_inventory(path)
        assert raised.value.code is ErrorCode.INPUT_SCHEMA, name


def test_rejects_a_net_over_the_size_limit(tmp_path: Path) -> None:
    path = tmp_path / "net.xml"
    path.write_bytes(DEMO_NET.read_bytes())
    with pytest.raises(CasoError) as raised:
        read_network_inventory(path, max_bytes=100)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_the_size_limit_is_inclusive(tmp_path: Path) -> None:
    path = tmp_path / "net.xml"
    path.write_bytes(b"<net/>" + b" " * 20)  # el relleno final es XML válido aunque se corte
    assert read_network_inventory(path, max_bytes=26).counts.junctions == 0
    with pytest.raises(CasoError):
        read_network_inventory(path, max_bytes=25)


def test_the_limit_applies_to_the_decompressed_size(tmp_path: Path) -> None:
    bomb = tmp_path / "bomb.net.xml.gz"
    bomb.write_bytes(gzip.compress(b"<net>" + b" " * 5_000_000 + b"</net>", 9))
    assert bomb.stat().st_size < 50_000
    with pytest.raises(CasoError) as raised:
        read_network_inventory(bomb, max_bytes=100_000)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_the_truncated_fixture_is_rejected() -> None:
    with pytest.raises(CasoError) as raised:
        read_network_inventory(SUMO_FIXTURES / "invalid" / "truncated_net" / "demo.net.xml")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
