"""Pruebas de la auditoría de una simulación SUMO: configuración, rutas, demanda y adicionales."""

import gzip
import subprocess
import sys
from pathlib import Path

import pytest

from semaforo.caso.audit import audit_simulation
from semaforo.caso.audit_models import SimulationAudit
from semaforo.caso.errors import CasoError, ErrorCode

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"
ENTRY = "entry.sumocfg"
# a (2 carriles, el 1 solo bus) -> b -> c (prohíbe bus); b -> d (la conexión prohíbe autos);
# b -> e (solo bus); a -> f solo desde el carril de bus; b -> g llega al carril de bus de g.
NET = """<net version="1.20">
    <edge id=":j_0" function="internal"><lane id=":j_0_0" index="0"/></edge>
    <edge id="a"><lane id="a_0" index="0"/><lane id="a_1" index="1" allow="bus"/></edge>
    <edge id="b"><lane id="b_0" index="0"/></edge>
    <edge id="c"><lane id="c_0" index="0" disallow="bus"/></edge>
    <edge id="d"><lane id="d_0" index="0"/></edge>
    <edge id="e"><lane id="e_0" index="0" allow="bus"/></edge>
    <edge id="f"><lane id="f_0" index="0"/></edge>
    <edge id="g"><lane id="g_0" index="0" allow="bus"/><lane id="g_1" index="1"/></edge>
    <connection from="a" to="b" fromLane="0" toLane="0"/>
    <connection from="b" to="c" fromLane="0" toLane="0"/>
    <connection from="b" to="d" fromLane="0" toLane="0" disallow="passenger"/>
    <connection from="b" to="e" fromLane="0" toLane="0"/>
    <connection from="a" to="f" fromLane="1" toLane="0"/>
    <connection from="b" to="g" fromLane="0" toLane="0"/>
    <connection from=":j_0" to="b" fromLane="0" toLane="0"/>
</net>"""


def config(inputs: str, extra: str = "") -> str:
    return (
        f"<configuration><input>{inputs}</input>"
        f'<time><begin value="0"/><step-length value="1"/></time>{extra}</configuration>'
    )


def routes(*elements: str, root: str = "routes") -> str:
    return f"<{root}>{''.join(elements)}</{root}>"


def make_case(
    tmp_path: Path,
    route_text: str,
    *,
    additional: str | None = None,
    extra: str = "",
    inputs: str | None = None,
) -> Path:
    folder = tmp_path / "case"
    folder.mkdir()
    (folder / "net.xml").write_text(NET, encoding="utf-8")
    (folder / "routes.xml").write_text(route_text, encoding="utf-8")
    declared = '<net-file value="net.xml"/><route-files value="routes.xml"/>'
    if additional is not None:
        (folder / "extra.add.xml").write_text(additional, encoding="utf-8")
        declared += '<additional-files value="extra.add.xml"/>'
    (folder / ENTRY).write_text(config(inputs or declared, extra), encoding="utf-8")
    return folder


def codes(audit: SimulationAudit) -> list[tuple[str, str]]:
    return [(finding.code, finding.subject) for finding in audit.findings]


def test_audits_the_demo_fixture() -> None:
    audit = audit_simulation(DEMO, "demo.sumocfg")
    assert (audit.entry_config, audit.net_file) == ("demo.sumocfg", "demo.net.xml")
    assert (audit.route_files, audit.additional_files) == (["demo.rou.xml"], [])
    assert audit.network_checked is True
    assert (audit.config.begin_s, audit.config.end_s, audit.config.step_length_s) == (0, None, 1)
    assert audit.config.seed == "301"
    assert [(t.id, t.vclass) for t in audit.vehicle_types] == [("car", "passenger"), ("bus", "bus")]
    assert [(r.id, r.edge_count, r.first_edge, r.last_edge) for r in audit.routes] == [
        ("N_S", 2, "demo_N", "demo_S"),
        ("E_W", 2, "demo_E", "demo_W"),
    ]
    assert [(d.id, d.expected_vehicles) for d in audit.demand] == [
        ("N_S_car", 90),
        ("N_S_bus", 10),
        ("E_W_car", 50),
    ]
    assert audit.expected_vehicles_total == 150
    assert audit.expected_vehicles_by_class == {"bus": 10, "passenger": 140}
    assert [(e.edge, e.vclass, e.lanes, e.flow_veh_h) for e in audit.entry_loads] == [
        ("demo_E", "passenger", 1, 200),
        ("demo_N", "bus", 1, 40),
        ("demo_N", "passenger", 1, 360),
    ]
    assert codes(audit) == [("NO_END_TIME", "demo.sumocfg")]


def test_records_every_config_option() -> None:
    options = audit_simulation(DEMO, "demo.sumocfg").config.options
    assert options["random_number"] == {"seed": "301"}
    assert options["report"]["duration-log.statistics"] == "true"


# id: (atributos del flujo, tasa en veh/h, vehículos esperados). Los flujos de intervalo fijo
# cuentan como SUMO 1.27.1: techo(duración / intervalo), con el final excluido (medido con SUMO
# y fijado en tests/integration/test_audit_sumo.py). Los aleatorios dan la media.
FLOW_CASES: dict[str, tuple[str, float, float]] = {
    "per_hour": ('begin="0" end="1800" perHour="600"', 600, 300),
    "legacy": ('begin="0" end="1800" vehsPerHour="600"', 600, 300),
    "period": ('begin="0" end="100" period="10"', 360, 10),
    "number": ('begin="0" end="900" number="7"', 28, 7),
    "late_start": ('begin="6" end="3600" perHour="200"', 200, 200),
    "period_7": ('begin="0" end="100" period="7"', 3600 / 7, 15),
    "per_hour_700": ('begin="0" end="1800" perHour="700"', 700, 350),
    "float_error": ('begin="0" end="1.1" period="0.1"', 36000, 11),
    # SUMO redondea el intervalo al milisegundo: 3600/420 s pasa a 8571 ms y cabe un vehículo más.
    "per_hour_420": ('begin="0" end="3600" perHour="420"', 420, 421),
    "per_hour_13": ('begin="0" end="3600" perHour="13"', 13, 14),
    "per_hour_7": ('begin="0" end="3600" perHour="7"', 7, 7),
    "period_third": ('begin="0" end="10" period="0.3333"', 3600 / 0.3333, 31),
    # El final también se redondea al milisegundo: 10,0004 s es 10000 ms y 10,0006 s, 10001 ms.
    "end_rounded_down": ('begin="0" end="10.0004" period="1"', 3600, 10),
    "end_rounded_up": ('begin="0" end="10.0006" period="1"', 3600, 11),
    "ends_before_it_begins": ('begin="100" end="50" perHour="3600"', 3600, 0),
    "probability": ('begin="0" end="10" probability="0.25"', 900, 2.5),
    "poisson": ('begin="0" end="10" period="exp(0.25)"', 900, 2.5),
}


def test_rates_and_expected_vehicles_for_each_kind_of_flow(tmp_path: Path) -> None:
    flows = [f'<flow id="{name}" route="r" {attrs}/>' for name, (attrs, _, _) in FLOW_CASES.items()]
    audit = audit_simulation(
        make_case(tmp_path, routes('<route id="r" edges="a b"/>', *flows)), ENTRY
    )
    rates = {d.id: d.rate_veh_h for d in audit.demand}
    expected = {d.id: d.expected_vehicles for d in audit.demand}
    assert rates == pytest.approx({name: rate for name, (_, rate, _) in FLOW_CASES.items()})
    assert expected == pytest.approx({name: count for name, (_, _, count) in FLOW_CASES.items()})


def test_entry_loads_count_only_the_lanes_of_each_class(tmp_path: Path) -> None:
    text = routes(
        '<vType id="bus" vClass="bus"/>',
        '<route id="r" edges="a b"/>',
        '<route id="r_bus" edges="a f"/>',
        '<flow id="cars" route="r" begin="0" end="3600" perHour="100"/>',
        '<flow id="more_cars" route="r" begin="0" end="3600" perHour="50"/>',
        '<flow id="buses" type="bus" route="r_bus" begin="0" end="3600" perHour="10"/>',
    )
    loads = audit_simulation(make_case(tmp_path, text), ENTRY).entry_loads
    assert [(e.edge, e.vclass, e.lanes, e.flow_veh_h) for e in loads] == [
        ("a", "bus", 2, 10),
        ("a", "passenger", 1, 150),
    ]


def test_a_flow_without_end_has_no_expected_count(tmp_path: Path) -> None:
    text = routes('<route id="r" edges="a b"/>', '<flow id="open" route="r" perHour="100"/>')
    audit = audit_simulation(make_case(tmp_path, text), ENTRY)
    (item,) = audit.demand
    assert (item.begin_s, item.end_s, item.expected_vehicles) == (0, None, None)
    assert ("DEMAND_WITHOUT_END", "open") in codes(audit)


def test_vehicles_trips_embedded_routes_and_the_default_type(tmp_path: Path) -> None:
    text = routes(
        '<route id="r" edges="a b"/>',
        '<vehicle id="v1" depart="5" route="r"/>',
        '<vehicle id="v2" depart="0"><route edges="a b c"/></vehicle>',
        '<trip id="t1" depart="3" from="a" to="c"/>',
    )
    audit = audit_simulation(make_case(tmp_path, text), ENTRY)
    found = {d.id: (d.kind, d.route_id, d.from_edge, d.to_edge, d.type_id) for d in audit.demand}
    assert found == {
        "v1": ("vehicle", "r", "a", "b", "DEFAULT_VEHTYPE"),
        "v2": ("vehicle", None, "a", "c", "DEFAULT_VEHTYPE"),
        "t1": ("trip", None, "a", "c", "DEFAULT_VEHTYPE"),
    }
    assert audit.expected_vehicles_total == 3
    assert {d.vclass for d in audit.demand} == {"passenger"}
    assert all(code != "UNDEFINED_TYPE" for code, _ in codes(audit))


def test_behaviour_attributes_are_recorded(tmp_path: Path) -> None:
    text = routes(
        '<vType id="car" accel="2.6" decel="4.5" sigma="0.5" carFollowModel="Krauss"/>',
        '<route id="r" edges="a b"/>',
        '<flow id="f" type="car" route="r" begin="0" end="10" number="1" departLane="best"/>',
    )
    audit = audit_simulation(make_case(tmp_path, text), ENTRY)
    (vtype,) = audit.vehicle_types
    assert vtype.vclass == "passenger"
    assert vtype.attributes == {
        "accel": "2.6",
        "decel": "4.5",
        "sigma": "0.5",
        "carFollowModel": "Krauss",
    }
    assert audit.demand[0].attributes == {"departLane": "best"}


def test_undefined_and_unused_definitions_are_reported(tmp_path: Path) -> None:
    text = routes(
        '<vType id="spare"/>',
        '<route id="r" edges="a b"/>',
        '<route id="unused" edges="a b"/>',
        '<flow id="f1" route="missing" begin="0" end="10" number="1"/>',
        '<flow id="f2" type="ghost" route="r" begin="0" end="10" number="1"/>',
    )
    found = codes(audit_simulation(make_case(tmp_path, text), ENTRY))
    for expected in [
        ("UNDEFINED_ROUTE", "f1"),
        ("UNDEFINED_TYPE", "f2"),
        ("UNUSED_ROUTE", "unused"),
        ("UNUSED_TYPE", "spare"),
    ]:
        assert expected in found


def test_route_edges_are_checked_per_vehicle_class(tmp_path: Path) -> None:
    text = routes(
        '<vType id="bus" vClass="bus"/>',
        '<route id="ok" edges="a b c"/>',
        '<route id="gap" edges="a c"/>',
        '<route id="unknown" edges="a x"/>',
        '<route id="no_cars" edges="b d"/>',
        '<route id="bus_lane" edges="b e"/>',
        '<route id="from_bus_lane" edges="a f"/>',
        '<route id="to_bus_lane" edges="b g"/>',
        '<route id="internal" edges=":j_0 b"/>',
    )
    flows = [
        ("car_ok", "ok", None),
        ("bus_ok_until_c", "ok", "bus"),
        ("car_gap", "gap", None),
        ("car_unknown", "unknown", None),
        ("car_no_cars", "no_cars", None),
        ("bus_no_cars", "no_cars", "bus"),
        ("car_bus_lane", "bus_lane", None),
        ("bus_bus_lane", "bus_lane", "bus"),
        ("car_from_bus_lane", "from_bus_lane", None),
        ("bus_from_bus_lane", "from_bus_lane", "bus"),
        ("car_to_bus_lane", "to_bus_lane", None),
        ("bus_to_bus_lane", "to_bus_lane", "bus"),
        ("car_internal", "internal", None),
    ]
    text = text.replace(
        "</routes>",
        "".join(
            f'<flow id="{flow}" route="{route}" begin="0" end="10" number="1"'
            + (f' type="{kind}"/>' if kind else "/>")
            for flow, route, kind in flows
        )
        + "</routes>",
    )
    audit = audit_simulation(make_case(tmp_path, text), ENTRY)
    found = {(f.code, f.subject) for f in audit.findings if f.code.startswith("ROUTE_")}
    assert found == {
        ("ROUTE_EDGE_FORBIDDEN", "bus_ok_until_c"),
        ("ROUTE_DISCONNECTED", "car_gap"),
        ("ROUTE_UNKNOWN_EDGE", "car_unknown"),
        ("ROUTE_DISCONNECTED", "car_no_cars"),
        ("ROUTE_EDGE_FORBIDDEN", "car_bus_lane"),
        ("ROUTE_DISCONNECTED", "car_from_bus_lane"),
        ("ROUTE_DISCONNECTED", "car_to_bus_lane"),
        ("ROUTE_UNKNOWN_EDGE", "car_internal"),
    }


def test_trip_endpoints_must_exist_and_admit_the_class(tmp_path: Path) -> None:
    text = routes(
        '<vType id="bus" vClass="bus"/>',
        '<trip id="t_unknown" depart="0" from="a" to="x"/>',
        '<trip id="t_forbidden" type="bus" depart="0" from="a" to="c"/>',
    )
    found = {
        (f.code, f.subject) for f in audit_simulation(make_case(tmp_path, text), ENTRY).findings
    }
    assert ("ROUTE_UNKNOWN_EDGE", "t_unknown") in found
    assert ("ROUTE_EDGE_FORBIDDEN", "t_forbidden") in found


def test_demand_against_the_end_time(tmp_path: Path) -> None:
    text = routes(
        '<route id="r" edges="a b"/>',
        '<flow id="late" route="r" begin="150" end="300" number="5"/>',
        '<flow id="long" route="r" begin="0" end="200" number="5"/>',
        '<flow id="inside" route="r" begin="0" end="100" number="5"/>',
        '<flow id="at_end" route="r" begin="100" end="150" number="5"/>',
        '<vehicle id="v_late" depart="120" route="r"/>',
    )
    extra = "<time><end value='100'/></time>"
    audit = audit_simulation(make_case(tmp_path, text, extra=extra), ENTRY)
    assert audit.config.end_s == 100
    found = codes(audit)
    assert ("DEMAND_AFTER_END", "late") in found
    assert ("DEMAND_AFTER_END", "at_end") in found
    assert ("DEMAND_TRUNCATED_BY_END", "long") in found
    assert ("DEMAND_AFTER_END", "v_late") in found
    assert not any(subject == "inside" for _, subject in found)
    assert all(code != "NO_END_TIME" for code, _ in found)


def test_additional_files_with_signals_or_detectors_are_flagged(tmp_path: Path) -> None:
    additional = routes(
        '<tlLogic id="T" type="static" programID="nuevo" offset="0">'
        '<phase duration="30" state="G"/></tlLogic>',
        '<inductionLoop id="d1" lane="a_0" pos="5" period="60" file="d1.xml"/>',
        '<laneAreaDetector id="d2" lane="b_0" pos="0" length="5" file="C:\\salida\\d2.xml"/>',
        '<busStop id="s1" lane="a_0" startPos="0" endPos="10"/>',
        '<vType id="from_add" vClass="bus"/>',
        root="additional",
    )
    text = routes(
        '<route id="r" edges="a b"/>',
        '<flow id="f" type="from_add" route="r" begin="0" end="10" number="1"/>',
    )
    audit = audit_simulation(make_case(tmp_path, text, additional=additional), ENTRY)
    assert audit.additional_files == ["extra.add.xml"]
    found = codes(audit)
    assert ("ADDITIONAL_TLS_PROGRAM", "T") in found
    assert ("ADDITIONAL_DETECTOR", "d1") in found
    assert ("ADDITIONAL_DETECTOR", "d2") in found
    assert ("ABSOLUTE_FILE_REFERENCE", "d2") in found
    assert ("NOT_AUDITED", "busStop") in found
    assert ("UNDEFINED_TYPE", "f") not in found
    sources = {f.subject: f.source for f in audit.findings}
    assert sources["T"] == "extra.add.xml"


def test_unknown_route_elements_are_reported_not_ignored(tmp_path: Path) -> None:
    text = routes(
        '<routeDistribution id="rd">'
        '<route id="r1" edges="a b" probability="1"/></routeDistribution>',
        '<flow id="f" route="rd" begin="0" end="10" number="1"/>',
    )
    found = codes(audit_simulation(make_case(tmp_path, text), ENTRY))
    assert ("NOT_AUDITED", "routeDistribution") in found
    assert ("UNDEFINED_ROUTE", "f") not in found


def test_other_input_files_are_reported_as_not_audited(tmp_path: Path) -> None:
    folder = make_case(tmp_path, routes())
    (folder / "state.xml").write_text("<snapshot/>", encoding="utf-8")
    inputs = (
        '<net-file value="net.xml"/><route-files value="routes.xml"/>'
        '<load-state value="state.xml"/>'
    )
    (folder / ENTRY).write_text(config(inputs), encoding="utf-8")
    assert ("NOT_AUDITED", "load-state") in codes(audit_simulation(folder, ENTRY))


def unavailable(audit: SimulationAudit, reference: str) -> str:
    """Motivo del hallazgo INPUT_NOT_AVAILABLE de ``reference``."""
    (finding,) = [
        f for f in audit.findings if f.code == "INPUT_NOT_AVAILABLE" and f.subject == reference
    ]
    return finding.message


@pytest.mark.parametrize(
    ("kind", "reason"),
    [("missing", "no está en la carpeta"), ("outside", "fuera"), ("absolute", "absoluta")],
)
def test_unavailable_inputs_are_reported_with_their_reason(
    tmp_path: Path, kind: str, reason: str
) -> None:
    """Los archivos existen fuera de la carpeta: cada capa de defensa debe actuar por sí sola."""
    outside = tmp_path / "outside.rou.xml"
    outside.write_text(routes(), encoding="utf-8")
    reference = {
        "missing": "absent.rou.xml",
        "outside": "../outside.rou.xml",
        "absolute": str(outside),
    }[kind]
    inputs = f'<net-file value="net.xml"/><route-files value="routes.xml, {reference}"/>'
    audit = audit_simulation(make_case(tmp_path, routes(), inputs=inputs), ENTRY)
    assert reason in unavailable(audit, reference)
    assert audit.route_files == ["routes.xml"]


@pytest.mark.skipif(sys.platform != "win32", reason="las uniones solo existen en Windows")
def test_an_input_reached_through_a_junction_is_not_followed(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "r.rou.xml").write_text(routes(), encoding="utf-8")
    folder = make_case(tmp_path, routes())
    link = folder / "linked"
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(elsewhere)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    try:
        inputs = '<net-file value="net.xml"/><route-files value="linked/r.rou.xml"/>'
        (folder / ENTRY).write_text(config(inputs), encoding="utf-8")
        audit = audit_simulation(folder, ENTRY)
        assert "enlace" in unavailable(audit, "linked/r.rou.xml")
        assert audit.route_files == []
    finally:
        link.rmdir()


def test_without_a_network_the_routes_are_not_checked(tmp_path: Path) -> None:
    text = routes(
        '<route id="r" edges="x y"/>', '<flow id="f" route="r" begin="0" end="10" number="1"/>'
    )
    inputs = '<net-file value="absent.net.xml"/><route-files value="routes.xml"/>'
    audit = audit_simulation(make_case(tmp_path, text, inputs=inputs), ENTRY)
    assert audit.network_checked is False
    assert audit.net_file is None
    assert not any(code.startswith("ROUTE_") for code, _ in codes(audit))
    assert audit.entry_loads[0].lanes is None


def test_several_and_compressed_route_files(tmp_path: Path) -> None:
    folder = make_case(tmp_path, routes('<route id="r" edges="a b"/>'))
    second = routes('<flow id="f" route="r" begin="0" end="10" number="2"/>')
    (folder / "more.rou.xml.gz").write_bytes(gzip.compress(second.encode("utf-8")))
    inputs = '<net-file value="net.xml"/><route-files value="routes.xml,more.rou.xml.gz"/>'
    (folder / ENTRY).write_text(config(inputs), encoding="utf-8")
    audit = audit_simulation(folder, ENTRY)
    assert audit.route_files == ["routes.xml", "more.rou.xml.gz"]
    assert [(d.id, d.source) for d in audit.demand] == [("f", "more.rou.xml.gz")]
    assert audit.expected_vehicles_total == 2


def test_the_audit_is_deterministic_has_no_machine_paths_and_reads_only(tmp_path: Path) -> None:
    folder = tmp_path / "copy"
    folder.mkdir()
    for path in DEMO.iterdir():
        (folder / path.name).write_bytes(path.read_bytes())
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
    first = audit_simulation(folder, "demo.sumocfg")
    second = audit_simulation(folder, "demo.sumocfg")
    assert first.model_dump_json() == second.model_dump_json()
    assert SimulationAudit.model_validate_json(first.model_dump_json()) == first
    assert str(tmp_path) not in first.model_dump_json()
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()} == before


INVALID_ROUTES = {
    "truncated": "<routes><flow id='f'",
    "wrong-root": "<net/>",
    "doctype": '<?xml version="1.0"?><!DOCTYPE routes><routes/>',
    "entity": '<?xml version="1.0"?><!DOCTYPE routes [<!ENTITY x "y">]><routes>&x;</routes>',
    "begin-not-a-number": routes('<flow id="f" route="r" begin="x" end="10" number="1"/>'),
    "rate-not-a-number": routes('<flow id="f" route="r" begin="0" end="10" perHour="x"/>'),
    "flow-without-id": routes('<flow route="r" begin="0" end="10" number="1"/>'),
    "period-zero": routes('<flow id="f" route="r" begin="0" end="10" period="0"/>'),
}


@pytest.mark.parametrize("text", INVALID_ROUTES.values(), ids=INVALID_ROUTES.keys())
def test_rejects_invalid_or_dangerous_route_files(tmp_path: Path, text: str) -> None:
    with pytest.raises(CasoError) as raised:
        audit_simulation(make_case(tmp_path, text), ENTRY)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert str(tmp_path) not in str(raised.value)


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        ("absent.sumocfg", ErrorCode.INPUT_SCHEMA),
        ("../entry.sumocfg", ErrorCode.PATH_NOT_ALLOWED),
        ("C:\\entry.sumocfg", ErrorCode.PATH_NOT_ALLOWED),
        ("", ErrorCode.INPUT_SCHEMA),
    ],
)
def test_rejects_an_invalid_entry_config(tmp_path: Path, entry: str, code: ErrorCode) -> None:
    with pytest.raises(CasoError) as raised:
        audit_simulation(make_case(tmp_path, routes()), entry)
    assert raised.value.code is code


def test_rejects_a_folder_that_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        audit_simulation(tmp_path / "absent", ENTRY)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
