"""Entradas de SUMO de una corrida aislada (DEV06 F2): archivos, manifiesto y rechazos."""

import csv
import gzip
import hashlib
import io
import json
import stat
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

import pytest
from defusedxml.ElementTree import fromstring

from semaforo.caso.errors import CasoError
from semaforo.caso.network_map import build_network_map
from semaforo.dominio.case import Case, canonical_sha256, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import ScenarioInvalidError, parse_scenario
from semaforo.simulacion import prepare
from semaforo.simulacion.cohort import CohortError
from semaforo.simulacion.compiler import compile_program, publish_program
from semaforo.simulacion.demand_inputs import DemandInputError, RouteTable, VehicleTypes
from semaforo.simulacion.prepare import (
    ALLOWED_BOUNDARY_POLICIES,
    CONFIG_FILE,
    REQUIRED_OUTPUTS,
    PreparationRequest,
    build_inputs,
    publish_inputs,
)
from semaforo.trazabilidad.ids import content_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_NET = FIXTURES / "sumo" / "demo" / "demo.net.xml"
DURATIONS = {"s1": 30.0, "s2": 3.0, "s3": 1.0, "s4": 22.0, "s5": 3.0, "s6": 1.0}
MOMENT = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
ROUTES: dict[str, Any] = {"routes": {"N_S": ["demo_N", "demo_S"], "E_W": ["demo_E", "demo_W"]}}
TYPES: dict[str, Any] = {
    "types": {
        "car": {"vclass": "passenger", "attributes": {"length": 5.0, "accel": 2.6}},
        "bus": {"vclass": "bus", "attributes": {"length": 12.0}, "gui_shape": "bus"},
    }
}
UPSTREAM = (
    '<edge id="demo_NN" from="X" to="N"><lane id="demo_NN_0" index="0" speed="1" '
    'length="9" shape="0,0 1,1"/></edge>\n'
    '<connection from="demo_NN" to="demo_N" fromLane="0" toLane="0" dir="s" state="M"/>\n'
    "</net>"
)
SECOND_ENTRY_LANE = (
    '<lane id="demo_N_1" index="1" speed="13.89" length="92.80" shape="0,0 1,1"/>\n'
    '        <lane id="demo_N_0" index="0"'
)

Change = Callable[[dict[str, Any]], None]


def json_of(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def request_for(  # noqa: PLR0913 - cada argumento cambia una pieza del ejemplo
    tmp_path: Path,
    *,
    net: Callable[[str], str] | None = None,
    case_change: Change | None = None,
    scenario_change: Change | None = None,
    routes: dict[str, Any] | None = None,
    compressed: bool = False,
    **options: Any,  # noqa: ANN401 - campos de PreparationRequest
) -> PreparationRequest:
    """El ejemplo de dos movimientos sobre la red de demostración, con los cambios pedidos."""
    case_dir = tmp_path / "caso"
    case_dir.mkdir(exist_ok=True)
    text = DEMO_NET.read_text(encoding="utf-8")
    data = (net(text) if net else text).encode("utf-8")
    name = "demo.net.xml.gz" if compressed else "demo.net.xml"
    (case_dir / name).write_bytes(gzip.compress(data, mtime=0) if compressed else data)
    case_data = json_of("case.json")
    case_data["network"] = {
        "artifact_id": "red",
        "path": name,
        "sha256": hashlib.sha256((case_dir / name).read_bytes()).hexdigest(),
    }
    if case_change:
        case_change(case_data)
    case = parse_case(case_data)
    original = parse_case({**json_of("case.json"), "network": case_data["network"]})
    program = compile_program(original, build_network_map(case_dir / name, original), DURATIONS)
    programs = tmp_path / "programas"
    folder = programs / case.case_id
    existing = sorted(folder.iterdir()) if folder.exists() else []
    program_dir = existing[0] if existing else publish_program(programs, case, program, MOMENT)
    scenario_data = json_of("scenario.json")
    scenario_data["warmup_s"] = 60
    if scenario_change:
        scenario_change(scenario_data)
    return PreparationRequest(
        case=case,
        case_dir=case_dir,
        scenario=parse_scenario(scenario_data),
        routes=RouteTable.model_validate(routes or ROUTES),
        vehicle_types=VehicleTypes.model_validate(TYPES),
        program_dir=program_dir,
        **options,
    )


@pytest.fixture
def built(tmp_path: Path) -> prepare.PreparedInputs:
    return build_inputs(request_for(tmp_path), MOMENT)


def xml(prepared: prepare.PreparedInputs, name: str) -> Element:
    return fromstring(prepared.files[name])


def cohort_rows(prepared: prepare.PreparedInputs) -> list[list[str]]:
    data = prepared.files["cohorte.csv"]
    assert data.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter=";"))


def failure(request: PreparationRequest) -> DemandInputError:
    with pytest.raises(DemandInputError) as raised:
        build_inputs(request, MOMENT)
    return raised.value


# --- archivos -------------------------------------------------------------------------------


def test_the_folder_has_exactly_the_six_files(built: prepare.PreparedInputs) -> None:
    assert sorted(built.files) == [
        "cohorte.csv",
        "demanda.rou.xml",
        "escenario.sumocfg",
        "manifiesto.json",
        "programa.tll.xml",
        "red.net.xml",
    ]


def test_the_network_is_copied_byte_for_byte(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    prepared = build_inputs(request, MOMENT)
    assert prepared.files["red.net.xml"] == (request.case_dir / "demo.net.xml").read_bytes()


def test_a_compressed_network_keeps_its_compression(tmp_path: Path) -> None:
    request = request_for(tmp_path, compressed=True)
    prepared = build_inputs(request, MOMENT)
    assert "red.net.xml" not in prepared.files
    assert prepared.files["red.net.xml.gz"] == (request.case_dir / "demo.net.xml.gz").read_bytes()
    assert value(xml(prepared, CONFIG_FILE), "input/net-file") == "red.net.xml.gz"


def test_the_program_is_copied_as_published(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    prepared = build_inputs(request, MOMENT)
    assert (
        prepared.files["programa.tll.xml"]
        == (request.program_dir / "programa.tll.xml").read_bytes()
    )


def value(root: Element, path: str) -> str | None:
    found = root.find(path)
    assert found is not None, path
    return found.get("value")


def test_the_configuration_points_to_the_copied_files(built: prepare.PreparedInputs) -> None:
    config = xml(built, CONFIG_FILE)
    assert config.tag == "configuration"
    assert value(config, "input/net-file") == "red.net.xml"
    assert value(config, "input/route-files") == "demanda.rou.xml"
    assert value(config, "input/additional-files") == "programa.tll.xml"


def test_the_configuration_has_the_times_the_tick_and_the_seed(
    built: prepare.PreparedInputs,
) -> None:
    config = xml(built, CONFIG_FILE)
    # 60 s de calentamiento + 900 s de medición + 900 s de drenaje
    assert (value(config, "time/begin"), value(config, "time/end")) == ("0", "1860")
    assert value(config, "time/step-length") == "1"
    assert value(config, "random_number/seed") == "100"
    assert config.find("processing") is None
    assert config.find("output") is None


def test_the_configuration_declares_no_outputs_nor_absolute_paths(
    built: prepare.PreparedInputs,
) -> None:
    text = built.files[CONFIG_FILE].decode("utf-8")
    assert "output" not in text
    assert ":/" not in text
    assert "\\" not in text


def test_the_allowed_sumo_options_are_written(tmp_path: Path) -> None:
    request = request_for(
        tmp_path, sumo_options={"lateral-resolution": 0.8, "collision.check-junctions": True}
    )
    config = xml(build_inputs(request, MOMENT), CONFIG_FILE)
    assert value(config, "processing/lateral-resolution") == "0.8"
    assert value(config, "processing/collision.check-junctions") == "true"
    request = request_for(tmp_path, sumo_options={"collision.check-junctions": False})
    config = xml(build_inputs(request, MOMENT), CONFIG_FILE)
    assert value(config, "processing/collision.check-junctions") == "false"


def test_another_sumo_seed_is_written_and_recorded(tmp_path: Path) -> None:
    prepared = build_inputs(request_for(tmp_path, sumo_seed=7), MOMENT)
    assert value(xml(prepared, CONFIG_FILE), "random_number/seed") == "7"
    assert prepared.manifest.seeds.model_dump() == {"demand_seed": 100, "sumo_seed": 7}


def test_a_seed_of_zero_is_used_and_not_replaced_by_the_demand_seed(tmp_path: Path) -> None:
    prepared = build_inputs(request_for(tmp_path, sumo_seed=0), MOMENT)
    assert prepared.manifest.seeds.sumo_seed == 0


def test_the_sumo_seed_defaults_to_the_demand_seed(built: prepare.PreparedInputs) -> None:
    assert built.manifest.seeds.model_dump() == {"demand_seed": 100, "sumo_seed": 100}


# --- demanda --------------------------------------------------------------------------------


def test_the_demand_has_the_types_and_routes_in_use(built: prepare.PreparedInputs) -> None:
    demand = xml(built, "demanda.rou.xml")
    assert demand.tag == "routes"
    assert [vtype.attrib for vtype in demand.findall("vType")] == [
        {"id": "bus", "vClass": "bus", "length": "12", "guiShape": "bus"},
        {"id": "car", "vClass": "passenger", "length": "5", "accel": "2.6"},
    ]
    assert [route.attrib for route in demand.findall("route")] == [
        {"id": "ruta_E_W", "edges": "demo_E demo_W"},
        {"id": "ruta_N_S", "edges": "demo_N demo_S"},
    ]


def test_the_demand_has_every_vehicle_of_the_list_in_order(built: prepare.PreparedInputs) -> None:
    vehicles = xml(built, "demanda.rou.xml").findall("vehicle")
    assert [v.get("id") for v in vehicles] == [v.vehicle_id for v in built.cohort.vehicles]
    assert len(vehicles) == 160  # 150 de cohorte y 10 del calentamiento de 60 s
    departs = [float(v.get("depart") or "nan") for v in vehicles]
    assert departs == sorted(departs)


def test_each_vehicle_carries_its_type_route_hour_lane_and_speed(
    built: prepare.PreparedInputs,
) -> None:
    first = xml(built, "demanda.rou.xml").findall("vehicle")[0]
    vehicle = built.cohort.vehicles[0]
    assert first.attrib == {
        "id": vehicle.vehicle_id,
        "type": vehicle.vehicle_class,
        "route": f"ruta_{vehicle.movement_id}",
        "depart": f"{vehicle.depart_s:g}",
        "departLane": "0",
        "departSpeed": "max",
    }


def test_the_sublane_and_view_attributes_of_a_type_are_written(tmp_path: Path) -> None:
    moto = {
        "vclass": "motorcycle",
        "attributes": {"length": 2.2, "minGapLat": 0.3, "maxSpeedLat": 1.5, "lcSublane": 2.0},
        "lat_alignment": "arbitrary",
        "gui_shape": "motorcycle",
        "color": "230,120,30",
    }
    request = replace(
        request_for(tmp_path),
        vehicle_types=VehicleTypes.model_validate({"types": {**TYPES["types"], "car": moto}}),
    )
    demand = xml(build_inputs(request, MOMENT), "demanda.rou.xml")
    assert demand.findall("vType")[1].attrib == {
        "id": "car",
        "vClass": "motorcycle",
        "length": "2.2",
        "minGapLat": "0.3",
        "maxSpeedLat": "1.5",
        "lcSublane": "2",
        "latAlignment": "arbitrary",
        "guiShape": "motorcycle",
        "color": "230,120,30",
    }


def test_a_type_of_a_class_without_vehicles_is_not_written(tmp_path: Path) -> None:
    def no_bus(data: dict[str, Any]) -> None:
        data["request"]["demand"][0]["composition"] = {"car": 1.0}

    prepared = build_inputs(request_for(tmp_path, scenario_change=no_bus), MOMENT)
    demand = xml(prepared, "demanda.rou.xml")
    assert [vtype.get("id") for vtype in demand.findall("vType")] == ["car"]


def test_a_movement_without_vehicles_has_no_route(tmp_path: Path) -> None:
    def no_east(data: dict[str, Any]) -> None:
        data["request"]["demand"][1].update(flow_vph=0, composition=None)

    prepared = build_inputs(
        request_for(
            tmp_path, scenario_change=no_east, routes={"routes": {"N_S": ["demo_N", "demo_S"]}}
        ),
        MOMENT,
    )
    demand = xml(prepared, "demanda.rou.xml")
    assert [route.get("id") for route in demand.findall("route")] == ["ruta_N_S"]
    assert prepared.manifest.depart_lanes == {"N_S": "0"}


def test_hours_with_decimals_are_written_as_given(tmp_path: Path) -> None:
    def tenth(data: dict[str, Any]) -> None:
        data["tick_s"] = 0.5

    prepared = build_inputs(request_for(tmp_path, case_change=tenth), MOMENT)
    departs = [v.get("depart") or "" for v in xml(prepared, "demanda.rou.xml").findall("vehicle")]
    assert any(depart.endswith(".5") for depart in departs)
    assert not any(depart.endswith(".0") for depart in departs)
    assert value(xml(prepared, CONFIG_FILE), "time/step-length") == "0.5"


def test_a_route_that_starts_before_the_entry_street_lets_sumo_choose_the_lane(
    tmp_path: Path,
) -> None:
    routes = {"routes": {"N_S": ["demo_NN", "demo_N", "demo_S"], "E_W": ["demo_E", "demo_W"]}}
    request = request_for(
        tmp_path, net=lambda text: text.replace("</net>", UPSTREAM), routes=routes
    )
    prepared = build_inputs(request, MOMENT)
    lanes = {
        v.get("route"): v.get("departLane")
        for v in xml(prepared, "demanda.rou.xml").findall("vehicle")
    }
    assert lanes == {"ruta_N_S": "best", "ruta_E_W": "0"}
    assert prepared.manifest.depart_lanes == {"E_W": "0", "N_S": "best"}


def test_several_entry_lanes_are_used_in_turn(tmp_path: Path) -> None:
    def two_lanes(data: dict[str, Any]) -> None:
        data["movements"][0]["incoming_lanes"] = ["demo_N_1", "demo_N_0"]

    request = request_for(
        tmp_path,
        net=lambda text: text.replace('<lane id="demo_N_0" index="0"', SECOND_ENTRY_LANE, 1),
        case_change=two_lanes,
    )
    prepared = build_inputs(request, MOMENT)
    north = [
        v.get("departLane")
        for v in xml(prepared, "demanda.rou.xml").findall("vehicle")
        if v.get("route") == "ruta_N_S"
    ]
    assert north[:4] == ["1", "0", "1", "0"]
    assert north.count("1") - north.count("0") in (0, 1)
    assert prepared.manifest.depart_lanes["N_S"] == "1 0"


def test_a_demand_over_the_size_limit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prepare, "MAX_DEMAND_BYTES", 1000)
    error = failure(request_for(tmp_path))
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "máximo es 1000" in error.message


# --- cohorte.csv ----------------------------------------------------------------------------


def test_the_cohort_sheet_uses_the_team_format(built: prepare.PreparedInputs) -> None:
    data = built.files["cohorte.csv"]
    assert data.startswith(b"\xef\xbb\xbf")
    assert data.count(b"\r\n") == 161
    assert b"\n" not in data.replace(b"\r\n", b"")
    rows = cohort_rows(built)
    assert rows[0] == [
        "vehicle_id",
        "movement_id",
        "vehicle_class",
        "vtype",
        "route_id",
        "depart_s",
        "depart_lane",
        "en_cohorte",
        "sha256_fila",
    ]
    assert len(rows) == 161


def test_each_row_describes_its_vehicle(built: prepare.PreparedInputs) -> None:
    rows = cohort_rows(built)[1:]
    for row, vehicle in zip(rows, built.cohort.vehicles, strict=True):
        assert row[:8] == [
            f'="{vehicle.vehicle_id}"',
            f'="{vehicle.movement_id}"',
            f'="{vehicle.vehicle_class}"',
            f'="{vehicle.vehicle_class}"',
            f'="ruta_{vehicle.movement_id}"',
            f"{vehicle.depart_s:g}",
            "0",
            "sí" if vehicle.in_cohort else "no",
        ]
    assert sum(row[7] == "sí" for row in rows) == 150
    assert sum(row[7] == "no" for row in rows) == 10


def test_the_row_hash_covers_the_attributes_of_the_vehicle(built: prepare.PreparedInputs) -> None:
    row = cohort_rows(built)[1]
    vehicle = built.cohort.vehicles[0]
    vtype = TYPES["types"][vehicle.vehicle_class]
    attributes = {
        "vehicle_id": vehicle.vehicle_id,
        "movement_id": vehicle.movement_id,
        "vehicle_class": vehicle.vehicle_class,
        "type": {
            "id": vehicle.vehicle_class,
            "vClass": vtype["vclass"],
            **{name: f"{number:g}" for name, number in vtype["attributes"].items()},
            **({"guiShape": vtype["gui_shape"]} if "gui_shape" in vtype else {}),
        },
        "route": ROUTES["routes"][vehicle.movement_id],
        "depart_s": vehicle.depart_s,
        "depart_lane": "0",
        "in_cohort": vehicle.in_cohort,
    }
    text = json.dumps(attributes, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert row[8] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_row_hashes_are_all_different(built: prepare.PreparedInputs) -> None:
    hashes = [row[8] for row in cohort_rows(built)[1:]]
    assert len(set(hashes)) == len(hashes)


# --- manifiesto -----------------------------------------------------------------------------


def test_the_manifest_has_the_hash_of_every_other_file(built: prepare.PreparedInputs) -> None:
    files = built.manifest.files
    assert sorted(files) == sorted(name for name in built.files if name != "manifiesto.json")
    for name, digest in files.items():
        assert digest == hashlib.sha256(built.files[name]).hexdigest(), name


def test_the_written_manifest_is_the_one_returned(built: prepare.PreparedInputs) -> None:
    written = json.loads(built.files["manifiesto.json"])
    assert written == built.manifest.model_dump(mode="json")


def test_the_manifest_identifies_the_case_scenario_network_and_program(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    manifest = build_inputs(request, MOMENT).manifest
    assert (manifest.case_id, manifest.case_version) == ("SYNTHETIC_DEMO", "1.0.0")
    assert manifest.case_sha256 == canonical_sha256(request.case)
    assert manifest.scenario_id == "SCENARIO_DEMO_001"
    scenario_text = json.dumps(
        request.scenario.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert manifest.scenario_sha256 == hashlib.sha256(scenario_text.encode()).hexdigest()
    assert request.case.network is not None
    assert manifest.network.model_dump() == {
        "file": "red.net.xml",
        "sha256": request.case.network.sha256,
    }
    program_manifest = (request.program_dir / "manifiesto.json").read_bytes()
    assert manifest.program.source_manifest_sha256 == hashlib.sha256(program_manifest).hexdigest()
    assert (manifest.program.program_id, manifest.program.tls_id) == ("derived", "DEMO_TLS")
    assert manifest.boundary_policy_id == "DEMO_EMPTY_START_FIXED_ROUTES"
    assert manifest.entry_config == "escenario.sumocfg"


def test_the_manifest_has_the_hash_of_routes_types_and_each_route(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    manifest = build_inputs(request, MOMENT).manifest

    def canonical(data: object) -> str:
        text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode()).hexdigest()

    assert manifest.routes_sha256 == canonical(request.routes.model_dump(mode="json"))
    assert manifest.vehicle_types_sha256 == canonical(request.vehicle_types.model_dump(mode="json"))
    assert manifest.route_sha256 == {
        "E_W": hashlib.sha256(b"demo_E demo_W").hexdigest(),
        "N_S": hashlib.sha256(b"demo_N demo_S").hexdigest(),
    }


def test_the_manifest_has_the_times_and_the_cohort_window(built: prepare.PreparedInputs) -> None:
    assert built.manifest.times.model_dump() == {
        "step_length_s": 1.0,
        "begin_s": 0.0,
        "warmup_s": 60.0,
        "measure_s": 900.0,
        "drain_max_s": 900.0,
        "end_s": 1860.0,
        "cohort_start_s": 60.0,
        "cohort_end_s": 960.0,
    }


def test_the_manifest_counts_the_vehicles(built: prepare.PreparedInputs) -> None:
    vehicles = built.manifest.vehicles
    assert (vehicles.total, vehicles.cohort, vehicles.warmup) == (160, 150, 10)
    assert [count.model_dump() for count in vehicles.counts] == [
        {"movement_id": "N_S", "vehicle_class": "bus", "warmup": 1, "measured": 10},
        {"movement_id": "N_S", "vehicle_class": "car", "warmup": 6, "measured": 90},
        {"movement_id": "E_W", "vehicle_class": "bus", "warmup": 0, "measured": 0},
        {"movement_id": "E_W", "vehicle_class": "car", "warmup": 3, "measured": 50},
    ]


def test_the_manifest_lists_the_required_outputs_options_and_limits(tmp_path: Path) -> None:
    manifest = build_inputs(
        request_for(tmp_path, sumo_options={"lateral-resolution": 0.8}), MOMENT
    ).manifest
    assert manifest.required_outputs == list(REQUIRED_OUTPUTS)
    assert manifest.required_outputs == [
        "tripinfo-output",
        "tripinfo-output.write-unfinished",
        "statistic-output",
    ]
    assert manifest.sumo_options == {"lateral-resolution": 0.8}
    assert len(manifest.limitations) == 3
    assert any("departSpeed=max" in text for text in manifest.limitations)


def test_the_creation_time_is_written_in_utc(tmp_path: Path) -> None:
    lima = datetime(2026, 10, 31, 2, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    prepared = build_inputs(request_for(tmp_path), lima)
    assert prepared.manifest.created_at == "2026-10-31T07:00:00+00:00"
    assert prepared.folder_key.startswith("20261031T070000Z_")


def test_the_folder_name_has_the_hash_of_the_files(built: prepare.PreparedInputs) -> None:
    expected = content_id(built.manifest.files.items())[:8]
    assert built.folder_key == f"20261031T120000Z_{expected}"


def test_the_same_request_gives_the_same_files(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    assert build_inputs(request, MOMENT).files == build_inputs(request, MOMENT).files


def test_another_signal_program_keeps_exactly_the_same_vehicles(tmp_path: Path) -> None:
    # Protocolo: la demanda materializada se reutiliza entre alternativas de semáforo.
    request = request_for(tmp_path)
    case = request.case
    other = compile_program(
        case,
        build_network_map(request.case_dir / "demo.net.xml", case),
        {**DURATIONS, "s1": 40.0, "s4": 30.0},
        program_id="alternativa",
    )
    other_dir = publish_program(tmp_path / "otros", case, other, MOMENT)
    first = build_inputs(request, MOMENT).files
    second = build_inputs(replace(request, program_dir=other_dir), MOMENT).files
    assert first["programa.tll.xml"] != second["programa.tll.xml"]
    for name in ("demanda.rou.xml", "cohorte.csv", "red.net.xml", "escenario.sumocfg"):
        assert first[name] == second[name], name


def test_another_moment_changes_only_the_manifest(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    first = build_inputs(request, MOMENT).files
    second = build_inputs(request, MOMENT + timedelta(hours=1)).files
    assert [name for name in first if first[name] != second[name]] == ["manifiesto.json"]


# --- publicación ----------------------------------------------------------------------------


def test_the_folder_is_published_read_only_under_the_scenario(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    folder = publish_inputs(tmp_path / "entradas", request, MOMENT)
    prepared = build_inputs(request, MOMENT)
    assert folder == tmp_path / "entradas" / "SCENARIO_DEMO_001" / prepared.folder_key
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == prepared.files
    assert all(not path.stat().st_mode & stat.S_IWRITE for path in folder.iterdir())


def test_a_published_folder_is_never_overwritten(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    publish_inputs(tmp_path / "entradas", request, MOMENT)
    with pytest.raises(DemandInputError) as raised:
        publish_inputs(tmp_path / "entradas", request, MOMENT)
    assert raised.value.code is ErrorCode.RUN_EXISTS


@pytest.mark.parametrize("scenario_id", ["../fuera", "a/b", ".oculto", "con espacio"])
def test_a_scenario_id_that_is_not_a_safe_folder_name_is_refused(
    tmp_path: Path, scenario_id: str
) -> None:
    def rename(data: dict[str, Any]) -> None:
        data["scenario_id"] = scenario_id

    request = request_for(tmp_path, scenario_change=rename)
    with pytest.raises(DemandInputError) as raised:
        publish_inputs(tmp_path / "entradas", request, MOMENT)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (tmp_path / "entradas").exists()


def test_the_case_files_are_not_changed(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    before = {
        p.name: p.read_bytes()
        for p in [*request.case_dir.iterdir(), *request.program_dir.iterdir()]
    }
    publish_inputs(tmp_path / "entradas", request, MOMENT)
    after = {
        p.name: p.read_bytes()
        for p in [*request.case_dir.iterdir(), *request.program_dir.iterdir()]
    }
    assert after == before


# --- rechazos -------------------------------------------------------------------------------


def test_both_admitted_boundary_policies_are_accepted(tmp_path: Path) -> None:
    assert ALLOWED_BOUNDARY_POLICIES == {"DEMO_EMPTY_START_FIXED_ROUTES", "sin-semaforos-vecinos"}

    def policy(data: dict[str, Any]) -> None:
        data["boundary_policy_id"] = "sin-semaforos-vecinos"

    request = request_for(tmp_path, case_change=policy, scenario_change=policy)
    assert build_inputs(request, MOMENT).manifest.boundary_policy_id == "sin-semaforos-vecinos"


def test_another_boundary_policy_is_refused(tmp_path: Path) -> None:
    def policy(data: dict[str, Any]) -> None:
        data["boundary_policy_id"] = "CON_VECINOS"

    error = failure(request_for(tmp_path, case_change=policy, scenario_change=policy))
    assert (error.code, error.field) == (ErrorCode.INPUT_SCHEMA, "boundary_policy_id")
    assert "«CON_VECINOS»" in error.message


@pytest.mark.parametrize(
    ("options", "field"),
    [
        ({"end": 10}, "sumo_options.end"),
        ({"tripinfo-output": 1}, "sumo_options.tripinfo-output"),
        ({"lateral-resolution": 0}, "sumo_options.lateral-resolution"),
        ({"lateral-resolution": -1}, "sumo_options.lateral-resolution"),
        ({"lateral-resolution": True}, "sumo_options.lateral-resolution"),
        ({"lateral-resolution": float("nan")}, "sumo_options.lateral-resolution"),
        ({"lateral-resolution": float("inf")}, "sumo_options.lateral-resolution"),
        ({"collision.check-junctions": 1}, "sumo_options.collision.check-junctions"),
    ],
)
def test_sumo_options_outside_the_list_or_with_a_bad_value_are_refused(
    tmp_path: Path, options: dict[str, Any], field: str
) -> None:
    error = failure(request_for(tmp_path, sumo_options=options))
    assert (error.code, error.field) == (ErrorCode.INPUT_SCHEMA, field)


@pytest.mark.parametrize("seed", [-1, 2**31])
def test_a_sumo_seed_out_of_range_is_refused(tmp_path: Path, seed: int) -> None:
    error = failure(request_for(tmp_path, sumo_seed=seed))
    assert error.field == "sumo_seed"


def test_the_largest_sumo_seed_is_accepted(tmp_path: Path) -> None:
    prepared = build_inputs(request_for(tmp_path, sumo_seed=2**31 - 1), MOMENT)
    assert value(xml(prepared, CONFIG_FILE), "random_number/seed") == "2147483647"


def test_a_scenario_that_does_not_fit_the_case_is_refused(tmp_path: Path) -> None:
    def other(data: dict[str, Any]) -> None:
        data["case_id"] = "OTRO"

    with pytest.raises(ScenarioInvalidError):
        build_inputs(request_for(tmp_path, scenario_change=other), MOMENT)


def test_too_many_vehicles_are_refused(tmp_path: Path) -> None:
    with pytest.raises(CohortError):
        build_inputs(request_for(tmp_path, max_vehicles=159), MOMENT)


def test_route_and_type_problems_are_reported_together(tmp_path: Path) -> None:
    request = request_for(tmp_path, routes={"routes": {"N_S": ["demo_N", "demo_Z"]}})
    request = replace(
        request,
        vehicle_types=VehicleTypes.model_validate({"types": {"car": {"vclass": "rail"}}}),
    )
    error = failure(request)
    assert [issue.rule_id for issue in error.issues] == [
        "TYPE-01",
        "TYPE-02",
        "ROUTE-02",
        "ROUTE-01",
    ]
    assert error.message.startswith("no se pueden preparar las entradas: TYPE-01 en types: ")
    assert error.message.endswith("(y 3 más)")


def test_a_case_without_network_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    request = replace(request, case=parse_case(json_of("case.json")))
    error = failure(request)
    assert (error.code, error.field) == (ErrorCode.INPUT_SCHEMA, "network")


def test_a_network_that_changed_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    path = request.case_dir / "demo.net.xml"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(CasoError) as raised:
        build_inputs(request, MOMENT)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_network_that_changes_after_being_checked_is_not_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # La copia se compara otra vez con la huella del caso: si el archivo cambió entre la
    # verificación y la lectura, no se publica una red distinta de la declarada.
    request = request_for(tmp_path)
    other = tmp_path / "otra.net.xml"
    other.write_bytes((request.case_dir / "demo.net.xml").read_bytes() + b"\n")

    def changed(_artifact: object, _folder: Path) -> Path:
        return other

    monkeypatch.setattr(prepare, "verified_network_path", changed)
    with pytest.raises(CasoError) as raised:
        build_inputs(request, MOMENT)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_network_that_cannot_be_read_is_a_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = request_for(tmp_path)

    def folder(_artifact: object, _folder: Path) -> Path:
        return tmp_path  # una carpeta no se puede abrir como archivo

    monkeypatch.setattr(prepare, "verified_network_path", folder)
    with pytest.raises(CasoError) as raised:
        build_inputs(request, MOMENT)
    assert (raised.value.code, raised.value.field) == (ErrorCode.INPUT_SCHEMA, "network")
    assert "no se pudo leer la red" in raised.value.message


def test_a_missing_network_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    (request.case_dir / "demo.net.xml").unlink()
    with pytest.raises(CasoError) as raised:
        build_inputs(request, MOMENT)
    assert raised.value.code is ErrorCode.DEPENDENCY_MISSING


def test_a_network_over_the_size_limit_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prepare, "MAX_NET_BYTES", 100)
    with pytest.raises(CasoError, match="límite de 100 bytes"):
        build_inputs(request_for(tmp_path), MOMENT)


def program_files(request: PreparationRequest) -> tuple[Path, Path]:
    copy = request.program_dir.parent / "copia"
    copy.mkdir()
    for path in request.program_dir.iterdir():
        (copy / path.name).write_bytes(path.read_bytes())
    return copy / "manifiesto.json", copy / "programa.tll.xml"


def test_a_program_of_another_case_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    manifest_path, _ = program_files(request)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["case_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    error = failure(replace(request, program_dir=manifest_path.parent))
    assert (error.code, error.field) == (ErrorCode.HASH_MISMATCH, "program_dir")
    assert "otro caso" in error.message


def test_a_program_of_another_network_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    manifest_path, _ = program_files(request)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["network_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    error = failure(replace(request, program_dir=manifest_path.parent))
    assert error.code is ErrorCode.HASH_MISMATCH
    assert "otra red" in error.message


def test_a_program_file_that_changed_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    _, program_path = program_files(request)
    program_path.write_bytes(program_path.read_bytes().replace(b'duration="30"', b'duration="31"'))
    error = failure(replace(request, program_dir=program_path.parent))
    assert error.code is ErrorCode.HASH_MISMATCH
    assert "programa.tll.xml" in error.message


def test_a_program_with_a_broken_manifest_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    manifest_path, _ = program_files(request)
    manifest_path.write_text("{}", encoding="utf-8")
    error = failure(replace(request, program_dir=manifest_path.parent))
    assert (error.code, error.field) == (ErrorCode.INPUT_SCHEMA, "program_dir")


def test_a_missing_program_folder_is_refused(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    error = failure(replace(request, program_dir=tmp_path / "no_existe"))
    assert (error.code, error.field) == (ErrorCode.INPUT_SCHEMA, "program_dir")


def test_nothing_is_published_when_something_fails(tmp_path: Path) -> None:
    request = request_for(tmp_path, sumo_seed=-1)
    with pytest.raises(DemandInputError):
        publish_inputs(tmp_path / "entradas", request, MOMENT)
    assert not (tmp_path / "entradas").exists()


def test_the_case_used_is_valid_for_the_tests() -> None:
    case: Case = parse_case(json_of("case.json"))
    assert case.boundary_policy_id in ALLOWED_BOUNDARY_POLICIES
