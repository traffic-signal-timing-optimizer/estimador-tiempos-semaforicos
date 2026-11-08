"""Métricas de una corrida publicadas una sola vez y verificables (DEV31 F2; decisión B10)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.app.integrity import verify_workspace
from semaforo.app.reception import RUNS as APP_RUNS
from semaforo.bd.carga.corridas import DELAY_COLUMNS, metric_rows
from semaforo.bd.carga.modelo import FileRecord, Unit
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.protocol import Protocol, parse_protocol
from semaforo.dominio.scenario import evidence_origin
from semaforo.evaluacion.cohort import CohortDelay, VehicleDelay, summarize_delays
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.metrics import zone_metrics
from semaforo.evaluacion.published_metrics import (
    MANIFEST_FILE,
    METRICS,
    METRICS_FILE,
    RUNS,
    metrics_bytes,
    publish_run_metrics,
    read_run_metrics,
)
from semaforo.evaluacion.run_metrics import DELAY_DEFINITION, RunMetrics
from semaforo.simulacion.reconcile import Status
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_bytes, sha256_file
from semaforo.trazabilidad.store import TrazabilidadError
from workspace_tools import tamper, writable

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
RUN_ID = "run-0001"
EQUIPMENT = {"cpu_cores": "8", "memory_gb": "15.8", "location": "local"}
N, E = "demo_N_0", "demo_E_0"
STEPS: dict[float, dict[str, tuple[str, float]]] = {
    0.0: {"a": (N, 8.0), "c": (E, 10.0)},
    1.0: {"a": (N, 0.0), "c": (E, 9.0)},
    2.0: {"a": (N, 0.05), "b": (N, 0.0), "c": (E, 11.0)},
    3.0: {"a": (N, 3.0), "b": (N, 0.0)},
}


def case() -> Case:
    return parse_case(json.loads((FIXTURES / "case.json").read_text(encoding="utf-8")))


def protocol() -> Protocol:
    return parse_protocol(json.loads((FIXTURES / "protocol.json").read_text(encoding="utf-8")))


def cohort() -> CohortDelay:
    states: list[tuple[str, str, Status]] = [
        ("a", "N", "finished"),
        ("b", "N", "finished"),
        ("c", "E", "finished"),
    ]
    items = [
        VehicleDelay(
            vehicle_id=vehicle_id,
            movement_id="N_S" if access == "N" else "E_W",
            vehicle_class="car",
            access_id=access,
            status=status,
            time_loss_s=1.5,
            depart_delay_s=0.0,
            depart_delay_source="sumo",
        )
        for vehicle_id, access, status in states
    ]
    return CohortDelay(
        total=summarize_delays(items),
        by_access={
            name: summarize_delays([item for item in items if item.access_id == name])
            for name in ("E", "N")
        },
        by_movement={},
        warmup_vehicles=0,
        simulation_end_s=100.0,
        vehicles=items,
    )


def real_metrics(tmp_path: Path, run_id: str = RUN_ID) -> RunMetrics:
    rows = "".join(
        f'<timestep time="{time:.2f}">'
        + "".join(
            f'<vehicle id="{vid}" speed="{speed:.2f}" lane="{lane}"/>'
            for vid, (lane, speed) in vehicles.items()
        )
        + "</timestep>"
        for time, vehicles in STEPS.items()
    )
    fcd = tmp_path / "fcd.xml"
    fcd.write_text(f"<fcd-export>{rows}</fcd-export>", encoding="utf-8")
    group, rules, demo = cohort(), protocol(), case()
    zone = zone_metrics(fcd, rules, demo, group, step_s=1.0, start_s=0.0, end_s=4.0)
    return RunMetrics(
        run_id=run_id,
        case_id=demo.case_id,
        case_version=demo.case_version,
        case_origin=demo.origin,
        demand_origin="synthetic",
        evidence_origin=evidence_origin(demo.origin, "synthetic"),
        scenario_id="ESC_1",
        sumo_seed=7,
        protocol_id=rules.protocol_id,
        protocol_status=rules.status,
        delay_definition=DELAY_DEFINITION,
        cohort=group,
        zone=zone,
        zone_unavailable=None,
        teleports_total=0,
        collisions=0,
        simulation_findings=[],
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    run = root / RUNS / RUN_ID
    run.mkdir(parents=True)
    (run / "manifest.json").write_text('{"run_id": "run-0001"}', encoding="utf-8")
    protocol_file = root / "derivados" / "protocolos" / "demo" / "protocolo.json"
    protocol_file.parent.mkdir(parents=True)
    protocol_file.write_bytes((FIXTURES / "protocol.json").read_bytes())
    yield root
    remove_tree(root)


def published(workspace: Path, tmp_path: Path) -> Path:
    return publish_run_metrics(workspace, real_metrics(tmp_path), now=NOW, environment=EQUIPMENT)


# --- publicar y volver a leer ------------------------------------------------------------------


def test_the_metrics_are_published_where_the_design_says(workspace: Path, tmp_path: Path) -> None:
    folder = published(workspace, tmp_path)
    assert folder == workspace / METRICS / case().case_id / RUN_ID
    assert sorted(item.name for item in folder.iterdir()) == [MANIFEST_FILE, METRICS_FILE]


def test_the_metrics_read_back_are_the_published_ones(workspace: Path, tmp_path: Path) -> None:
    metrics = real_metrics(tmp_path)
    stored = read_run_metrics(published(workspace, tmp_path))
    assert stored.metrics == metrics
    assert stored.metrics.zone is not None
    assert stored.metrics.zone.queue_series is not None
    assert stored.metrics.zone.queue_series.vehicles_by_access["N"] == [0, 1, 2, 1]


def test_an_access_with_queue_but_no_cohort_has_a_row_without_delay(tmp_path: Path) -> None:
    metrics = real_metrics(tmp_path)
    zone = metrics.zone
    assert zone is not None
    only_queue = zone.queue_by_access["N"]
    changed = metrics.model_copy(
        update={
            "zone": zone.model_copy(
                update={"queue_by_access": {**zone.queue_by_access, "SIN_COHORTE": only_queue}}
            )
        }
    )
    unit = Unit(key="corrida:prueba", kind="run")
    source = FileRecord("datos", "prueba/metricas.json", "metrics", "a" * 64, 1)
    metric_rows(unit, metrics.run_id, changed, source)
    row = next(
        row for row in unit.rows["simulacion.resultados_acceso"] if row["acceso"] == "SIN_COHORTE"
    )
    assert row["con_cohorte"] is False
    assert all(row[column] is None for column in DELAY_COLUMNS)
    assert row["estado_cola"] == only_queue.status


def test_the_manifest_says_where_the_metrics_come_from(workspace: Path, tmp_path: Path) -> None:
    stored = read_run_metrics(published(workspace, tmp_path))
    manifest = stored.manifest
    run_manifest = workspace / RUNS / RUN_ID / "manifest.json"
    assert manifest.run_manifest_sha256 == sha256_file(run_manifest)
    assert (manifest.run_id, manifest.scenario_id) == (RUN_ID, "ESC_1")
    assert manifest.metrics_schema_version == "2.1.0"
    assert manifest.schema_version == "1.1.0"
    assert manifest.protocol_sha256 == sha256_file(
        workspace / "derivados" / "protocolos" / "demo" / "protocolo.json"
    )
    assert manifest.environment == EQUIPMENT
    assert manifest.created_at == NOW
    folder = workspace / METRICS / manifest.case_id / RUN_ID
    assert manifest.files == {METRICS_FILE: sha256_bytes((folder / METRICS_FILE).read_bytes())}


def test_without_an_environment_the_current_one_is_recorded(
    workspace: Path, tmp_path: Path
) -> None:
    folder = publish_run_metrics(workspace, real_metrics(tmp_path), now=NOW)
    environment = read_run_metrics(folder).manifest.environment
    assert environment["python"]
    assert int(environment["cpu_cores"]) > 0


def test_the_run_folder_name_is_the_same_in_the_app_and_in_the_metrics() -> None:
    assert RUNS == APP_RUNS


# --- el archivo ------------------------------------------------------------------------------


def test_the_file_is_the_same_json_with_a_readable_layout(tmp_path: Path) -> None:
    metrics = real_metrics(tmp_path)
    text = metrics_bytes(metrics).decode("utf-8")
    assert json.loads(text) == metrics.model_dump(mode="json")
    assert text.endswith("}\n")
    lines = text.splitlines()
    assert '  "run_id": "run-0001",' in lines
    assert '      "times_s": [0.0, 1.0, 2.0, 3.0],' in lines  # una serie en una sola línea
    assert '        "N": [0, 1, 2, 1]' in lines
    vehicles = [line for line in lines if line.lstrip().startswith('{"vehicle_id"')]
    assert len(vehicles) == 3  # un vehículo por línea


def test_the_same_metrics_always_give_the_same_bytes(tmp_path: Path) -> None:
    assert metrics_bytes(real_metrics(tmp_path)) == metrics_bytes(real_metrics(tmp_path))


# --- lo que se rechaza -----------------------------------------------------------------------


def test_metrics_are_never_overwritten(workspace: Path, tmp_path: Path) -> None:
    published(workspace, tmp_path)
    with pytest.raises(EvaluacionError) as raised:
        published(workspace, tmp_path)
    assert raised.value.code is ErrorCode.RUN_EXISTS


def test_metrics_of_a_run_that_is_not_published_are_refused(
    workspace: Path, tmp_path: Path
) -> None:
    with pytest.raises(EvaluacionError) as raised:
        publish_run_metrics(workspace, real_metrics(tmp_path, "otra-corrida"))
    assert (raised.value.code, raised.value.field) == (ErrorCode.INPUT_SCHEMA, "run_id")
    assert not (workspace / METRICS).exists()


@pytest.mark.parametrize("name", ["../fuera", "a/b", "", ".oculta", "con espacio", "C:\\x"])
def test_a_run_or_case_name_that_is_not_a_safe_folder_is_refused(
    workspace: Path, tmp_path: Path, name: str
) -> None:
    metrics = real_metrics(tmp_path)
    for field in ("run_id", "case_id"):
        changed = metrics.model_copy(update={field: name})
        with pytest.raises(EvaluacionError) as raised:
            publish_run_metrics(workspace, changed)
        assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
        assert raised.value.field == field


# --- lo que se detecta al leer ----------------------------------------------------------------


def replace_metrics(folder: Path, data: bytes) -> None:
    """Cambia ``metricas.json`` y deja la huella del manifiesto al día: solo el contenido miente."""
    writable(folder / METRICS_FILE).write_bytes(data)
    path = writable(folder / MANIFEST_FILE)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"][METRICS_FILE] = sha256_bytes(data)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_a_changed_metrics_file_is_detected(workspace: Path, tmp_path: Path) -> None:
    folder = published(workspace, tmp_path)
    tamper(folder / METRICS_FILE)
    with pytest.raises(TrazabilidadError) as raised:
        read_run_metrics(folder)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_an_extra_file_is_detected(workspace: Path, tmp_path: Path) -> None:
    folder = published(workspace, tmp_path)
    (folder / "extra.txt").write_text("sobra", encoding="utf-8")
    with pytest.raises(TrazabilidadError) as raised:
        read_run_metrics(folder)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_metrics_moved_to_another_run_folder_do_not_match_their_manifest(
    workspace: Path, tmp_path: Path
) -> None:
    folder = published(workspace, tmp_path)
    moved = folder.parent / "otra-corrida"
    folder.rename(moved)
    with pytest.raises(TrazabilidadError, match="no coinciden"):
        read_run_metrics(moved)


def test_metrics_with_another_content_but_the_right_hash_do_not_match_the_manifest(
    workspace: Path, tmp_path: Path
) -> None:
    """Un archivo bien formado de otra corrida, con su huella puesta al día, no pasa."""
    folder = published(workspace, tmp_path)
    replace_metrics(folder, metrics_bytes(real_metrics(tmp_path, "run-9999")))
    with pytest.raises(TrazabilidadError, match="no coinciden"):
        read_run_metrics(folder)


def test_an_invalid_metrics_file_is_refused_without_its_content(
    workspace: Path, tmp_path: Path
) -> None:
    folder = published(workspace, tmp_path)
    replace_metrics(folder, b'{"run_id": 1}\n')
    with pytest.raises(TrazabilidadError, match="no son válidas") as raised:
        read_run_metrics(folder)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


# --- la revisión del espacio de trabajo ---------------------------------------------------------


def test_the_workspace_check_covers_the_published_metrics(workspace: Path, tmp_path: Path) -> None:
    folder = published(workspace, tmp_path)
    report = verify_workspace(workspace)
    items = [item for item in report.items if item.family == "metrics"]
    assert [(item.path, item.status) for item in items] == [
        (f"{METRICS}/{case().case_id}/{RUN_ID}", "intact")
    ]
    tamper(folder / METRICS_FILE)
    altered = verify_workspace(workspace)
    (item,) = [item for item in altered.items if item.family == "metrics"]
    assert (item.status, altered.status) == ("altered", "altered")
