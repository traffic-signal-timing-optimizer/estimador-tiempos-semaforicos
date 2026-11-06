"""Métricas que faltan y conciliación de la base con los archivos (DEV31 F4; QA33)."""

import json
from pathlib import Path

import pytest

from bd_tools import Loadable, copy_workspace
from semaforo.app.bd_commands import publish_metrics, reconcile_database, reconcile_exit_code
from semaforo.bd.carga.motor import LoadOptions, load_workspace
from semaforo.bd.conciliacion import reconcile
from semaforo.evaluacion.published_metrics import (
    METRICS_FILE,
    publish_run_metrics,
    read_run_metrics,
)
from semaforo.trazabilidad.fs import remove_tree

pytestmark = [pytest.mark.bd, pytest.mark.sumo]

PRELIMINARY = LoadOptions(preliminary=True)


def _metrics_folder(workspace: Path, loadable: Loadable, run_id: str) -> Path:
    return workspace / "derivados" / "metricas" / loadable.case_id / run_id


def test_the_metrics_that_are_missing_are_published_with_the_protocol_of_their_search(
    cargable: Loadable, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    run_id = cargable.runs[min(cargable.runs)]
    folder = _metrics_folder(workspace, cargable, run_id)
    original = (folder / METRICS_FILE).read_bytes()
    remove_tree(folder)
    # Otro protocolo, con otro nombre y primero en el orden: una corrida de búsqueda no lo usa.
    protocols = next((workspace / "derivados" / "protocolos").rglob("*.json")).parent
    other = json.loads(next(protocols.glob("*.json")).read_text(encoding="utf-8"))
    other["protocol_id"] = "A_OTRO_PRIMERO"
    (protocols / "a_otro.json").write_text(json.dumps(other), encoding="utf-8")
    report = publish_metrics(workspace)
    assert report.counts == {"published": 1, "already": 3, "skipped": 0, "failed": 0}
    (published,) = [r for r in report.runs if r.status == "published"]
    assert (published.run_id, published.protocol_id) == (run_id, cargable.protocol_id)
    assert (folder / METRICS_FILE).read_bytes() == original  # mismas métricas, byte a byte
    assert read_run_metrics(folder).metrics.run_id == run_id
    again = publish_metrics(workspace)
    assert again.counts == {"published": 0, "already": 4, "skipped": 0, "failed": 0}


def test_a_loose_run_needs_the_protocol_to_be_named_when_two_share_its_zone(
    cargable: Loadable, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    remove_tree(workspace / "derivados" / "referencias")  # ninguna búsqueda las usa
    remove_tree(workspace / "derivados" / "metricas")
    report = publish_metrics(workspace)
    assert report.counts["published"] == 4
    assert {r.protocol_id for r in report.runs} == {cargable.protocol_id}
    remove_tree(workspace / "derivados" / "metricas")
    folder = next((workspace / "derivados" / "protocolos").rglob("*.json"))
    second = json.loads(folder.read_text(encoding="utf-8"))
    second["protocol_id"] = "OTRO_PROTOCOLO"
    (folder.parent / "otro.json").write_text(json.dumps(second), encoding="utf-8")
    ambiguous = publish_metrics(workspace)
    assert ambiguous.counts == {"published": 0, "already": 0, "skipped": 4, "failed": 0}
    assert all("--protocolo" in str(r.detail) for r in ambiguous.runs)
    named = publish_metrics(workspace, protocol_id="OTRO_PROTOCOLO")
    assert named.counts["published"] == 4
    run_id = cargable.runs[min(cargable.runs)]
    stored = read_run_metrics(_metrics_folder(workspace, cargable, run_id))
    assert stored.metrics.protocol_id == "OTRO_PROTOCOLO"


def test_qa33_the_database_matches_the_files_in_counts_and_in_recalculated_delay(
    cargable: Loadable, base: str
) -> None:
    load_workspace(cargable.workspace, PRELIMINARY, database=base)
    report = reconcile(cargable.workspace, database=base)
    assert report.status == "equal", report.differences
    assert report.runs_checked == report.runs_recomputed == 4
    assert report.files_checked > 40
    assert reconcile_exit_code(report) == 0


def test_qa33_a_changed_file_and_a_changed_count_are_both_reported(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    load_workspace(workspace, PRELIMINARY, database=base)
    run_id = cargable.runs[min(cargable.runs)]
    table = workspace / "ejecuciones" / run_id / "outputs" / "cohorte_conciliada.csv"
    lines = table.read_bytes().splitlines(keepends=True)
    table.write_bytes(b"".join(lines[:-1]))  # un vehículo menos
    report = reconcile_database(workspace, database=base, recompute=False)
    assert report.status == "different"
    assert reconcile_exit_code(report) == 5
    items = {(d.where.rsplit("/", 1)[-1], d.item) for d in report.differences}
    assert (table.name, "tamaño") in items
    assert (run_id, "vehículos") in items
    found = next(d for d in report.differences if d.item == "vehículos")
    assert int(found.database) == int(found.files) + 1


def test_qa33_a_metric_that_no_longer_matches_what_is_recalculated_is_reported(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    """Si el protocolo midiera la cola con otro umbral, lo recalculado ya no sería lo cargado."""
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    load_workspace(workspace, PRELIMINARY, database=base)
    path = next((workspace / "derivados" / "protocolos").rglob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["queue_speed_threshold_mps"] = 8.0
    path.write_text(json.dumps(data), encoding="utf-8")
    report = reconcile(workspace, database=base)
    assert report.status == "different"
    moved = {d.item for d in report.differences if d.item.startswith("demora y métricas")}
    assert "demora y métricas: umbral_cola_mps" in moved
    assert "demora y métricas: cola_media_veh" in moved
    assert "demora y métricas: demora_media_s" not in moved  # la demora no depende del umbral


def _first_run(cargable: Loadable) -> str:
    return cargable.runs[min(cargable.runs)]


def _loaded_copy(cargable: Loadable, base: str, tmp_path: Path) -> Path:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    load_workspace(workspace, PRELIMINARY, database=base)
    return workspace


def _items(workspace: Path, base: str) -> set[tuple[str, str]]:
    report = reconcile(workspace, database=base, recompute=False)
    return {(d.where.rsplit("/", 1)[-1], d.item) for d in report.differences}


def test_qa33_a_file_changed_without_changing_its_size_is_found_by_its_fingerprint(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = _loaded_copy(cargable, base, tmp_path)
    log = workspace / "ejecuciones" / _first_run(cargable) / "outputs" / "sumo.stdout.txt"
    data = bytearray(log.read_bytes())
    data[0] = ord("X") if data[0] != ord("X") else ord("Y")
    log.write_bytes(bytes(data))
    assert (log.name, "huella") in _items(workspace, base)


def test_qa33_a_changed_cohort_flag_is_reported_even_if_the_vehicle_count_is_the_same(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = _loaded_copy(cargable, base, tmp_path)
    run_id = _first_run(cargable)
    table = workspace / "ejecuciones" / run_id / "outputs" / "cohorte_conciliada.csv"
    text = table.read_text(encoding="utf-8-sig")
    assert ";sí;" in text
    table.write_text(text.replace(";sí;", ";no;", 1), encoding="utf-8-sig", newline="")
    items = _items(workspace, base)
    assert (run_id, "vehículos de la cohorte") in items
    assert (run_id, "vehículos") not in items


def test_qa33_an_event_that_the_log_has_and_the_base_does_not_is_reported(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = _loaded_copy(cargable, base, tmp_path)
    run_id = _first_run(cargable)
    log = workspace / "ejecuciones" / run_id / "outputs" / "sumo.log"
    log.write_bytes(log.read_bytes() + b"Warning: aviso agregado despues\n")
    assert (run_id, "eventos del registro de SUMO") in _items(workspace, base)


def _forged(workspace: Path, cargable: Loadable, run_id: str) -> None:
    """Publica de nuevo las métricas de la corrida con un paso de cola menos, bien firmadas."""
    folder = _metrics_folder(workspace, cargable, run_id)
    metrics = read_run_metrics(folder).metrics
    zone = metrics.zone
    assert zone is not None
    series = zone.queue_series
    assert series is not None
    shorter = series.model_copy(
        update={
            "times_s": series.times_s[:-1],
            "in_window": series.in_window[:-1],
            "vehicles_by_access": {k: v[:-1] for k, v in series.vehicles_by_access.items()},
        }
    )
    changed = metrics.model_copy(update={"zone": zone.model_copy(update={"queue_series": shorter})})
    remove_tree(folder)
    publish_run_metrics(workspace, changed)


def test_qa33_a_metrics_file_republished_with_a_different_queue_is_reported(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = _loaded_copy(cargable, base, tmp_path)
    run_id = _first_run(cargable)
    _forged(workspace, cargable, run_id)
    assert (run_id, "filas de cola segundo a segundo") in _items(workspace, base)


def test_qa33_a_metrics_folder_that_was_altered_is_reported_instead_of_stopping(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = _loaded_copy(cargable, base, tmp_path)
    run_id = _first_run(cargable)
    data = _metrics_folder(workspace, cargable, run_id) / METRICS_FILE
    data.write_bytes(data.read_bytes() + b" ")
    items = _items(workspace, base)
    assert (run_id, "métricas publicadas") in items
    assert (METRICS_FILE, "tamaño") in items
