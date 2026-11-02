"""Métricas de corridas reales con SUMO (DEV19 F4; QA25, QA26 y QA27 de integración)."""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.dominio.case import Case
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.protocol import Protocol, parse_protocol
from semaforo.evaluacion.cohort import compare_cohorts
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.simulacion.prepare import MANIFEST_FILE, ZONE_FILE, publish_inputs
from semaforo.simulacion.reconcile import reconcile_run
from semaforo.simulacion.run_inputs import run_inputs
from semaforo.simulacion.runner import RunLimits
from semaforo.trazabilidad.fs import remove_tree

pytestmark = pytest.mark.sumo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def protocol(**changes: object) -> Protocol:
    data: dict[str, Any] = json.loads((FIXTURES / "protocol.json").read_text(encoding="utf-8"))
    data.update(changes)
    return parse_protocol(data)


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


def saturate(scenario: dict[str, Any]) -> None:
    scenario["request"]["demand"][0]["flow_vph"] = 1200
    scenario["drain_max_s"] = 0


def saturate_with_drain(scenario: dict[str, Any]) -> None:
    """Saturada y con 60 s de drenaje: el fin de la simulación no es el de la cohorte."""
    saturate(scenario)
    scenario["drain_max_s"] = 60


def prepared(tmp_path: Path, name: str, **options: Any) -> tuple[Path, Case]:  # noqa: ANN401
    request = request_for(tmp_path, **options)
    return publish_inputs(tmp_path / name, request, MOMENT), request.case


def test_a_full_run_gives_a_complete_cohort_and_the_zone_metrics(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder, case = prepared(tmp_path, "entradas")
    run = run_inputs(folder, runs, sumo=sumo_binary)
    metrics = evaluate_run(folder, runs, run.manifest.run_id, case, protocol())
    manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
    cohort = metrics.cohort
    assert cohort.total.requested == manifest["vehicles"]["cohort"] == 150
    assert cohort.warmup_vehicles == manifest["vehicles"]["warmup"]
    assert cohort.total.status == "complete"
    assert cohort.total.mean_delay_s is not None
    assert cohort.total.mean_delay_s > 0
    assert sorted(cohort.by_access) == ["E", "N"]
    assert metrics.zone is not None
    queue = metrics.zone.queue
    assert (queue.status, queue.coverage) == ("complete", 1.0)
    assert queue.ticks_expected == manifest["times"]["measure_s"]
    assert queue.max_vehicles is not None
    assert queue.max_vehicles > 0  # hay rojo: alguien se detiene
    assert metrics.zone.stops.total_stops > 0
    assert metrics.zone_unavailable is None
    assert (metrics.origin, metrics.protocol_status) == ("synthetic", "draft")


def test_qa25_a_saturated_run_keeps_every_requested_vehicle_and_is_censored(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder, case = prepared(tmp_path, "entradas", scenario_change=saturate)
    run = run_inputs(folder, runs, sumo=sumo_binary)
    metrics = evaluate_run(folder, runs, run.manifest.run_id, case, protocol())
    total = metrics.cohort.total
    manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert total.requested == manifest["vehicles"]["cohort"]
    assert total.finished + total.unfinished + total.not_inserted == total.requested
    assert total.not_inserted > 0
    assert total.status == "censored"
    assert total.mean_delay_s is None
    assert total.lower_bound_mean_delay_s is not None
    assert len(metrics.cohort.vehicles) == total.requested
    sources = {vehicle.depart_delay_source for vehicle in metrics.cohort.vehicles}
    assert sources == {"sumo"}
    assert metrics.zone is not None
    assert metrics.zone.stops.status == "censored"
    assert metrics.zone.stops.mean_stops is None


def test_two_censored_real_runs_are_undetermined_even_when_identical(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    """Dos corridas censuradas no tienen medias completas: no se declara ganadora a ninguna,
    aunque sean la misma (QA26). Comparar planes distintos con la misma demanda es de DEV20."""
    folder, case = prepared(tmp_path, "entradas", scenario_change=saturate)
    first = run_inputs(folder, runs, sumo=sumo_binary)
    second = run_inputs(folder, runs, sumo=sumo_binary)
    a = evaluate_run(folder, runs, first.manifest.run_id, case, protocol()).cohort
    b = evaluate_run(folder, runs, second.manifest.run_id, case, protocol()).cohort
    result = compare_cohorts(a, b, protocol().numeric_abs_tolerance)
    assert result.same_cohort is True
    assert result.total.verdict == "undetermined"  # dos censuradas: no hay medias completas


def as_old_folder(tmp_path: Path, published: Path) -> Path:
    """Copia de una carpeta de entradas convertida en una 1.0.0 de DEV06 (sin zona)."""
    folder = tmp_path / "vieja"
    shutil.copytree(published, folder)
    for item in folder.iterdir():
        item.chmod(0o666)
    (folder / ZONE_FILE).unlink()
    path = folder / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["files"][ZONE_FILE]
    del manifest["measurement_edges"]
    manifest["schema_version"] = "1.0.0"
    manifest["required_outputs"] = manifest["required_outputs"][:3]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_an_old_folder_has_no_zone_metrics_and_says_why(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    published, case = prepared(tmp_path, "entradas")
    folder = as_old_folder(tmp_path, published)
    run = run_inputs(folder, runs, sumo=sumo_binary)
    metrics = evaluate_run(folder, runs, run.manifest.run_id, case, protocol())
    assert metrics.zone is None
    assert metrics.zone_unavailable is not None
    assert "1.0.0" in metrics.zone_unavailable
    assert metrics.cohort.total.status == "complete"


def test_in_an_old_saturated_folder_the_wait_comes_from_the_end_of_the_simulation(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    published, case = prepared(tmp_path, "entradas", scenario_change=saturate_with_drain)
    folder = as_old_folder(tmp_path, published)
    run = run_inputs(folder, runs, sumo=sumo_binary)
    metrics = evaluate_run(folder, runs, run.manifest.run_id, case, protocol())
    times = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))["times"]
    end_s = times["end_s"]
    assert end_s > times["cohort_end_s"]
    waiting = [v for v in metrics.cohort.vehicles if v.status == "not_inserted"]
    assert waiting
    assert {v.depart_delay_source for v in waiting} == {"schedule"}
    assert metrics.cohort.simulation_end_s == end_s
    scheduled = {
        o.vehicle_id: o.scheduled_s
        for o in reconcile_run(folder, runs, run.manifest.run_id).outcomes
    }
    for vehicle in waiting:
        assert vehicle.depart_delay_s == max(0.0, end_s - scheduled[vehicle.vehicle_id])


def test_the_case_must_be_the_one_of_the_inputs(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder, case = prepared(tmp_path, "entradas")
    run = run_inputs(folder, runs, sumo=sumo_binary)
    other = case.model_copy(update={"case_version": "1.0.1"})
    with pytest.raises(EvaluacionError, match="el caso no es") as raised:
        evaluate_run(folder, runs, run.manifest.run_id, other, protocol())
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_run_made_with_other_inputs_is_refused(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder, case = prepared(tmp_path, "entradas")
    other, _ = prepared(tmp_path, "otras", scenario_change=saturate)
    run = run_inputs(other, runs, sumo=sumo_binary)
    with pytest.raises(DomainError) as raised:
        evaluate_run(folder, runs, run.manifest.run_id, case, protocol())
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_failed_run_has_no_metrics(tmp_path: Path, runs: Path, sumo_binary: Path) -> None:
    folder, case = prepared(tmp_path, "entradas")
    run = run_inputs(folder, runs, sumo=sumo_binary, limits=RunLimits(wall_timeout_s=0.01))
    assert run.manifest.status == "failed"
    with pytest.raises(DomainError) as raised:
        evaluate_run(folder, runs, run.manifest.run_id, case, protocol())
    assert raised.value.code is ErrorCode.OUTPUT_INVALID


def test_a_zone_the_run_did_not_record_is_refused(
    tmp_path: Path, runs: Path, sumo_binary: Path
) -> None:
    folder, case = prepared(tmp_path, "entradas")
    run = run_inputs(folder, runs, sumo=sumo_binary)
    with pytest.raises(EvaluacionError, match="no están en la FCD") as raised:
        evaluate_run(folder, runs, run.manifest.run_id, case, protocol(zone_lane_ids=["demo_S_0"]))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_an_unsupported_protocol_is_refused_before_reading_the_run(
    tmp_path: Path, runs: Path
) -> None:
    folder, case = prepared(tmp_path, "entradas")
    with pytest.raises(EvaluacionError, match="población"):
        evaluate_run(folder, runs, "no-existe", case, protocol(cohort_policy="todos"))
