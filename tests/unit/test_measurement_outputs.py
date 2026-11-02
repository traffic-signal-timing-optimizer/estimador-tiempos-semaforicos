"""Salidas de medición de las corridas preparadas (DEV19 F1, ADR11), sin SUMO."""

import csv
import hashlib
import io
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.caso.errors import CasoError
from semaforo.caso.network_graph import read_network_graph
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion import prepare
from semaforo.simulacion.prepare import (
    MANIFEST_FILE,
    ZONE_FILE,
    InputsManifest,
    build_inputs,
    publish_inputs,
)
from semaforo.simulacion.reconcile import reconcile
from semaforo.simulacion.run_inputs import verify_inputs, zone_of
from semaforo.simulacion.runner import (
    FCD,
    FCD_ATTRIBUTES,
    RunLimits,
    SimulacionError,
    run_simulation,
    summarize_outputs,
    sumo_arguments,
)
from semaforo.simulacion.tripinfo import Trip, read_trips
from semaforo.trazabilidad.store import RunSpec

LIMIT = 1024 * 1024
DEMO_ZONE = b"edge:demo_N\nedge:demo_E\n"


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)


@pytest.fixture
def editable(folder: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "copia"
    shutil.copytree(folder, copy)
    for item in copy.iterdir():
        item.chmod(0o666)
    return copy


def change_manifest(folder: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = folder / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def write_zone(folder: Path, data: bytes) -> None:
    """Cambia la zona y pone su huella nueva en el manifiesto (solo la huella)."""
    (folder / ZONE_FILE).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    change_manifest(folder, lambda manifest: manifest["files"].update({ZONE_FILE: digest}))


# --- la carpeta de entradas declara la zona ------------------------------------------------


def test_the_zone_lists_the_entry_streets_of_the_case_in_order(tmp_path: Path) -> None:
    built = build_inputs(request_for(tmp_path), MOMENT)
    assert built.files[ZONE_FILE] == DEMO_ZONE
    assert built.manifest.measurement_edges == ["demo_N", "demo_E"]
    assert built.manifest.schema_version == "1.1.0"
    assert built.manifest.files[ZONE_FILE] == hashlib.sha256(DEMO_ZONE).hexdigest()


def test_the_zone_uses_the_street_of_the_lanes_not_the_declared_approach(tmp_path: Path) -> None:
    """En el ejemplo el acceso se llama «N», pero la calle de sus carriles es «demo_N»."""
    built = build_inputs(request_for(tmp_path), MOMENT)
    case = request_for(tmp_path).case
    assert [movement.approach_id for movement in case.movements] == ["N", "E"]
    assert "N" not in built.manifest.measurement_edges


def test_a_street_shared_by_two_movements_appears_once(tmp_path: Path) -> None:
    def share(case: dict[str, Any]) -> None:
        case["movements"][1]["incoming_lanes"] = ["demo_N_0"]

    lanes = prepare.measurement_edges(
        request_for(tmp_path, case_change=share).case,
        read_network_graph(tmp_path / "caso" / "demo.net.xml"),
    )
    assert lanes == ["demo_N"]


def test_a_lane_that_is_not_in_the_network_is_refused(tmp_path: Path) -> None:
    def ghost(case: dict[str, Any]) -> None:
        case["movements"][0]["incoming_lanes"] = ["fantasma_0"]

    with pytest.raises(DomainError, match="no está en la red") as raised:
        prepare.measurement_edges(
            request_for(tmp_path, case_change=ghost).case,
            read_network_graph(tmp_path / "caso" / "demo.net.xml"),
        )
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_the_zone_file_is_one_selection_line_per_street() -> None:
    assert prepare.zone_file_bytes(["a#1", "b"]) == b"edge:a#1\nedge:b\n"
    assert prepare.zone_file_bytes([]) == b""


def test_a_published_folder_with_its_zone_passes(folder: Path) -> None:
    manifest = verify_inputs(folder)
    assert manifest.measurement_edges == ["demo_N", "demo_E"]
    assert zone_of(manifest) == ZONE_FILE


def test_a_zone_that_disagrees_with_the_manifest_is_refused(editable: Path) -> None:
    write_zone(editable, b"edge:demo_N\n")
    with pytest.raises(SimulacionError, match="zona de medición no son") as raised:
        verify_inputs(editable)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_manifest_with_other_streets_is_refused(editable: Path) -> None:
    change_manifest(editable, lambda manifest: manifest.update(measurement_edges=["demo_S"]))
    with pytest.raises(SimulacionError, match="zona de medición no son"):
        verify_inputs(editable)


def test_a_manifest_that_forgets_the_zone_while_the_file_is_there_is_refused(
    editable: Path,
) -> None:
    change_manifest(editable, lambda manifest: manifest.update(measurement_edges=[]))
    with pytest.raises(SimulacionError, match="no coinciden en la zona") as raised:
        verify_inputs(editable)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_manifest_with_streets_but_without_the_file_is_refused(editable: Path) -> None:
    (editable / ZONE_FILE).unlink()

    def forget(manifest: dict[str, Any]) -> None:
        del manifest["files"][ZONE_FILE]

    change_manifest(editable, forget)
    with pytest.raises(SimulacionError, match="no coinciden en la zona"):
        verify_inputs(editable)


def test_an_old_folder_without_zone_still_passes_and_runs_without_measurement(
    editable: Path,
) -> None:
    """Una carpeta 1.0.0 de DEV06 no tiene zona: se ejecuta igual, sin FCD (ADR11)."""
    (editable / ZONE_FILE).unlink()

    def as_old(manifest: dict[str, Any]) -> None:
        del manifest["files"][ZONE_FILE]
        del manifest["measurement_edges"]
        manifest["schema_version"] = "1.0.0"
        manifest["required_outputs"] = manifest["required_outputs"][:3]

    change_manifest(editable, as_old)
    manifest = verify_inputs(editable)
    assert manifest.measurement_edges == []
    assert zone_of(manifest) is None


def test_an_old_manifest_without_the_new_field_is_still_valid(folder: Path) -> None:
    data = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
    del data["measurement_edges"]
    assert InputsManifest.model_validate(data).measurement_edges == []


# --- el corredor pide las salidas nuevas ---------------------------------------------------


def test_without_zone_the_command_is_the_same_as_before() -> None:
    assert sumo_arguments("caso.sumocfg", 60) == [
        "-c",
        "inputs/caso.sumocfg",
        "--end",
        "60",
        "--tripinfo-output",
        "outputs/tripinfo.xml",
        "--tripinfo-output.write-unfinished",
        "true",
        "--statistic-output",
        "outputs/statistics.xml",
        "--duration-log.statistics",
        "true",
        "--no-step-log",
        "true",
        "--log",
        "outputs/sumo.log",
    ]


def test_with_zone_the_command_asks_for_undeparted_trips_and_the_zone_fcd() -> None:
    plain = sumo_arguments("caso.sumocfg", 60)
    measured = sumo_arguments("caso.sumocfg", 60, zone_file="zona_fcd.txt")
    assert measured[: len(plain)] == plain
    assert measured[len(plain) :] == [
        "--tripinfo-output.write-undeparted",
        "true",
        "--fcd-output",
        "outputs/fcd.xml",
        "--fcd-output.filter-edges.input-file",
        "inputs/zona_fcd.txt",
        "--fcd-output.attributes",
        "id,lane,speed",
    ]
    assert FCD == "fcd.xml"
    assert FCD_ATTRIBUTES == "id,lane,speed"


def test_gui_options_are_still_neutralized_after_the_measurement() -> None:
    arguments = sumo_arguments(
        "caso.sumocfg", 60, gui_options=["gui-settings-file"], zone_file="z.txt"
    )
    assert arguments[-2:] == ["--gui-settings-file", ""]


def spec() -> RunSpec:
    return RunSpec(
        kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", scenario_id=None, seed=1
    )


@pytest.mark.parametrize("zone", ["../fuera.txt", "C:/zona.txt", "/zona.txt", ""])
def test_a_zone_outside_the_inputs_is_refused_before_running(
    folder: Path, tmp_path: Path, zone: str
) -> None:
    with pytest.raises(SimulacionError) as raised:
        run_simulation(
            folder, "escenario.sumocfg", tmp_path / "runs", spec(), zone_file=zone, sumo=Path("x")
        )
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert raised.value.field == "zone_file"
    assert not (tmp_path / "runs").exists() or not any((tmp_path / "runs").iterdir())


def test_a_zone_file_that_is_not_in_the_inputs_is_refused_before_running(
    folder: Path, tmp_path: Path
) -> None:
    with pytest.raises(SimulacionError, match="zona de medición") as raised:
        run_simulation(
            folder,
            "escenario.sumocfg",
            tmp_path / "runs",
            spec(),
            zone_file="otra.txt",
            sumo=Path("x"),
            limits=RunLimits(),
        )
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


# --- la coherencia de las salidas cuenta aparte los que no entraron -----------------------

STATISTICS = """<statistics>
    <vehicles loaded="{loaded}" inserted="{inserted}" running="{running}" waiting="{waiting}"/>
    <teleports total="0" jam="0" yield="0" wrongLane="0"/>
</statistics>
"""


def write_outputs(  # noqa: PLR0913 - cada conteo cambia una salida
    folder: Path, trips: list[str], *, inserted: int, running: int, waiting: int, fcd: bool = True
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    loaded = inserted + waiting
    (folder / "statistics.xml").write_text(
        STATISTICS.format(loaded=loaded, inserted=inserted, running=running, waiting=waiting),
        encoding="utf-8",
    )
    (folder / "tripinfo.xml").write_text(
        "<tripinfos>" + "".join(trips) + "</tripinfos>", encoding="utf-8"
    )
    if fcd:
        (folder / FCD).write_text("<fcd-export/>", encoding="utf-8")
    return folder


FINISHED = '<tripinfo id="a" depart="1.00" arrival="9.00"/>'
RUNNING = '<tripinfo id="b" depart="2.00" arrival="-1.00"/>'
WAITING = '<tripinfo id="c" depart="-1" arrival="-1.00" departDelay="30.00"/>'


def test_a_measured_run_counts_the_waiting_vehicles_apart(tmp_path: Path) -> None:
    folder = write_outputs(tmp_path, [FINISHED, RUNNING, WAITING], inserted=2, running=1, waiting=1)
    summary = summarize_outputs(folder, None, measured=True)
    assert (summary.trips_finished, summary.trips_unfinished) == (1, 1)
    assert (summary.vehicles_inserted, summary.vehicles_waiting) == (2, 1)


def test_a_measured_run_without_the_record_of_a_waiting_vehicle_is_invalid(
    tmp_path: Path,
) -> None:
    folder = write_outputs(tmp_path, [FINISHED, RUNNING], inserted=2, running=1, waiting=1)
    with pytest.raises(SimulacionError, match="0 viajes que no entraron y 1") as raised:
        summarize_outputs(folder, None, measured=True)
    assert raised.value.code is ErrorCode.OUTPUT_INVALID


def test_records_of_vehicles_that_never_entered_are_invalid_without_measurement(
    tmp_path: Path,
) -> None:
    folder = write_outputs(tmp_path, [FINISHED, RUNNING, WAITING], inserted=2, running=1, waiting=1)
    with pytest.raises(SimulacionError, match="1 viajes que no entraron y 1"):
        summarize_outputs(folder, None)


def test_a_run_without_measurement_is_summarized_as_before(tmp_path: Path) -> None:
    folder = write_outputs(tmp_path, [FINISHED, RUNNING], inserted=2, running=1, waiting=3)
    summary = summarize_outputs(folder, None)
    assert (summary.trips_finished, summary.trips_unfinished, summary.vehicles_waiting) == (
        1,
        1,
        3,
    )


def test_a_measured_run_without_fcd_is_invalid(tmp_path: Path) -> None:
    folder = write_outputs(tmp_path, [FINISHED], inserted=1, running=0, waiting=0, fcd=False)
    with pytest.raises(SimulacionError, match=r"falta fcd\.xml") as raised:
        summarize_outputs(folder, None, measured=True)
    assert raised.value.code is ErrorCode.OUTPUT_INVALID
    assert summarize_outputs(folder, None).trips_finished == 1


def test_a_waiting_record_is_not_taken_for_an_inserted_vehicle(tmp_path: Path) -> None:
    folder = write_outputs(tmp_path, [FINISHED, WAITING], inserted=2, running=0, waiting=1)
    with pytest.raises(SimulacionError, match="hay 1 viajes y 2 vehículos insertados"):
        summarize_outputs(folder, None, measured=True)


def test_a_waiting_record_is_not_taken_for_a_running_vehicle(tmp_path: Path) -> None:
    folder = write_outputs(tmp_path, [FINISHED, WAITING], inserted=1, running=1, waiting=1)
    with pytest.raises(SimulacionError, match="0 viajes sin terminar y 1"):
        summarize_outputs(folder, None, measured=True)


# --- el tripinfo trae los tiempos de cada viaje --------------------------------------------


def write_trips(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "tripinfo.xml"
    path.write_text(f"<tripinfos>{body}</tripinfos>", encoding="utf-8")
    return path


def test_the_reader_keeps_the_times_of_each_trip(tmp_path: Path) -> None:
    body = (
        '<tripinfo id="a" depart="6.00" departDelay="0.50" arrival="62.00" '
        'waitingTime="11.00" waitingCount="1" timeLoss="21.59"/>'
    )
    assert read_trips(write_trips(tmp_path, body), LIMIT) == {
        "a": Trip(6.0, 62.0, time_loss=21.59, depart_delay=0.5, waiting_time=11.0, waiting_count=1)
    }


def test_missing_times_stay_unknown_and_are_not_zero(tmp_path: Path) -> None:
    trip = read_trips(write_trips(tmp_path, '<tripinfo id="a" depart="1" arrival="2"/>'), LIMIT)
    assert trip["a"] == Trip(1.0, 2.0)
    assert trip["a"].time_loss is None
    assert trip["a"].depart_delay is None


@pytest.mark.parametrize("attribute", ["timeLoss", "departDelay", "waitingTime", "waitingCount"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "abc", ""])
def test_a_time_that_is_not_a_finite_number_is_refused(
    tmp_path: Path, attribute: str, value: str
) -> None:
    body = f'<tripinfo id="a" depart="1" arrival="2" {attribute}="{value}"/>'
    with pytest.raises(CasoError, match=attribute) as raised:
        read_trips(write_trips(tmp_path, body), LIMIT)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


@pytest.mark.parametrize(
    ("depart", "started"), [(None, True), (0.0, True), (12.0, True), (-1.0, False), (-0.5, False)]
)
def test_a_trip_started_unless_its_departure_is_negative(
    depart: float | None, started: bool
) -> None:
    assert Trip(depart, -1.0).started is started


# --- la conciliación no confunde a un no iniciado con un inconcluso ------------------------


def cohort_ids(folder: Path) -> list[tuple[str, float]]:
    text = (folder / "cohorte.csv").read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))[1:]
    return [(row[0][2:-1], float(row[5])) for row in rows]


def test_a_vehicle_recorded_as_never_departed_is_not_inserted(folder: Path, tmp_path: Path) -> None:
    vehicles = cohort_ids(folder)
    waiting_id = vehicles[-1][0]
    trips = [
        f'<tripinfo id="{vid}" depart="{at:.2f}" arrival="{at + 30:.2f}"/>'
        for vid, at in vehicles[:-1]
    ]
    trips.append(f'<tripinfo id="{waiting_id}" depart="-1" arrival="-1.00" departDelay="9.00"/>')
    result = reconcile(folder, write_trips(tmp_path, "".join(trips)))
    outcome = next(v for v in result.outcomes if v.vehicle_id == waiting_id)
    assert (outcome.status, outcome.inserted_s, outcome.arrival_s) == ("not_inserted", None, None)
    assert result.unfinished == 0
    assert result.finished + result.not_inserted == result.requested


def test_a_running_vehicle_is_still_unfinished(folder: Path, tmp_path: Path) -> None:
    vehicles = cohort_ids(folder)
    running_id, at = vehicles[-1]
    trips = [
        f'<tripinfo id="{vid}" depart="{t:.2f}" arrival="{t + 30:.2f}"/>'
        for vid, t in vehicles[:-1]
    ]
    trips.append(f'<tripinfo id="{running_id}" depart="{at:.2f}" arrival="-1.00"/>')
    result = reconcile(folder, write_trips(tmp_path, "".join(trips)))
    outcome = next(v for v in result.outcomes if v.vehicle_id == running_id)
    assert (outcome.status, outcome.inserted_s) == ("unfinished", at)
