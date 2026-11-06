"""Corridas preparadas con las salidas de medición, con SUMO real (DEV19 F1, ADR11)."""

import gzip
import json
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.simulacion.prepare import MANIFEST_FILE, ZONE_FILE, publish_inputs
from semaforo.simulacion.reconcile import reconcile
from semaforo.simulacion.run_inputs import run_inputs
from semaforo.simulacion.runner import SimulationResult
from semaforo.simulacion.tripinfo import read_trips
from semaforo.trazabilidad.fs import remove_tree

pytestmark = pytest.mark.sumo

LIMIT = 64 * 1024 * 1024
ZONE_LANES = {"demo_N_0", "demo_E_0"}


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


def saturate(scenario: dict[str, Any]) -> None:
    """Demanda en el máximo del dominio y sin drenaje: quedan vehículos sin entrar."""
    scenario["request"]["demand"][0]["flow_vph"] = 1200
    scenario["drain_max_s"] = 0


def outputs(runs: Path, result: SimulationResult) -> Path:
    return runs / result.manifest.run_id / "outputs"


def fcd_text(runs: Path, result: SimulationResult) -> str:
    """La FCD de la corrida, descomprimida: se publica como ``fcd.xml.gz`` (DEV31 F2)."""
    with gzip.open(outputs(runs, result) / "fcd.xml.gz", "rt", encoding="utf-8") as stream:
        return stream.read()


def test_a_prepared_run_writes_the_fcd_of_the_zone_one_step_per_tick(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    result = run_inputs(folder, runs, sumo=sumo_binary)
    assert (result.manifest.status, result.manifest.error) == ("succeeded", None)
    published = {artifact.path for artifact in result.manifest.outputs}
    assert "outputs/fcd.xml.gz" in published
    assert "outputs/fcd.xml" not in published
    assert not (outputs(runs, result) / "fcd.xml").exists()
    assert not (outputs(runs, result) / "fcd.xml.gz.part").exists()
    text = fcd_text(runs, result)
    steps = [float(value) for value in re.findall(r'<timestep time="([^"]+)"', text)]
    end_s = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))["times"]["end_s"]
    assert steps == [float(second) for second in range(int(end_s))]
    lanes = set(re.findall(r'lane="([^"]*)"', text))
    assert lanes & ZONE_LANES == ZONE_LANES
    assert all(lane in ZONE_LANES or lane.startswith(":") for lane in lanes)
    assert set(re.findall(r'<vehicle id="[^"]+" speed="[^"]+" lane="[^"]+"/>', text))


def test_a_saturated_run_records_the_vehicles_that_never_entered(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder = publish_inputs(
        tmp_path / "entradas", request_for(tmp_path, scenario_change=saturate), MOMENT
    )
    result = run_inputs(folder, runs, sumo=sumo_binary)
    summary = result.summary
    assert summary is not None
    assert summary.vehicles_waiting > 0
    trips = read_trips(outputs(runs, result) / "tripinfo.xml", LIMIT)
    waiting = [trip for trip in trips.values() if not trip.started]
    assert len(waiting) == summary.vehicles_waiting
    assert len(trips) == summary.vehicles_loaded
    assert all(trip.depart_delay is not None and trip.depart_delay > 0 for trip in waiting)
    reconciliation = reconcile(
        runs / result.manifest.run_id / "inputs", outputs(runs, result) / "tripinfo.xml"
    )
    states = [outcome.status for outcome in reconciliation.outcomes]
    assert states.count("unfinished") == summary.trips_unfinished
    assert states.count("finished") == summary.trips_finished
    assert states.count("not_inserted") == len(reconciliation.outcomes) - summary.vehicles_inserted
    assert reconciliation.not_inserted > 0
    assert (
        reconciliation.finished + reconciliation.unfinished + reconciliation.not_inserted
        == reconciliation.requested
    )


def test_an_old_folder_without_zone_runs_as_before_without_fcd(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    published = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    folder = tmp_path / "vieja"
    shutil.copytree(published, folder)
    for item in folder.iterdir():
        item.chmod(0o666)
    (folder / ZONE_FILE).unlink()
    path = folder / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["files"][ZONE_FILE]
    del manifest["measurement_edges"]
    del manifest["measurement_access"]
    manifest["schema_version"] = "1.0.0"
    manifest["required_outputs"] = manifest["required_outputs"][:3]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = run_inputs(folder, runs, sumo=sumo_binary)
    assert result.manifest.status == "succeeded"
    assert not (outputs(runs, result) / "fcd.xml").exists()
    assert not (outputs(runs, result) / "fcd.xml.gz").exists()
    assert "--fcd-output" not in result.manifest.command
