"""El catálogo de fuentes frente a una carga real (DEV31 F4c, C1.1 a C1.3).

El cargador, la conciliación y las métricas que faltan recorren ``datos/`` con el mismo catálogo:
lo que el catálogo ve es lo que se carga, y lo que sobra o falta en la base se dice en los dos
sentidos.
"""

import json
from pathlib import Path

import pytest

from bd_tools import Loadable, copy_workspace, scalar
from semaforo.app.bd_commands import publish_metrics, reconcile_exit_code
from semaforo.bd.carga.fuentes import discover
from semaforo.bd.carga.motor import LoadOptions, load_workspace
from semaforo.bd.conciliacion import reconcile
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.evaluacion.published_metrics import METRICS_FILE
from semaforo.trazabilidad.fs import remove_tree

pytestmark = [pytest.mark.bd, pytest.mark.sumo]

PRELIMINARY = LoadOptions(preliminary=True)


def _run_folder(workspace: Path, loadable: Loadable) -> Path:
    return workspace / "ejecuciones" / loadable.runs[min(loadable.runs)]


def test_what_the_catalog_sees_is_what_the_load_loads_and_the_coverage_counts_it(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    sources = discover(workspace)
    assert len(sources.of("run")) == 4
    assert len(sources.of("search")) == 1
    assert len(sources.of("case")) == len(sources.of("protocol")) == 1
    load_workspace(workspace, PRELIMINARY, database=base)
    assert scalar(base, "SELECT count(*) FROM simulacion.corridas") == len(sources.of("run"))
    report = reconcile(workspace, database=base)
    assert report.status == "equal", report.differences
    expected = len([item for item in sources.items if item.kind != "split"])
    assert (report.coverage.expected, report.coverage.loaded) == (expected, expected)
    assert (report.coverage.missing, report.coverage.surplus) == (0, 0)


def test_a_run_folder_that_is_gone_is_a_surplus_in_the_database(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    load_workspace(workspace, PRELIMINARY, database=base)
    folder = _run_folder(workspace, cargable)
    remove_tree(folder)
    report = reconcile(workspace, database=base, recompute=False)
    assert report.status == "different"
    assert reconcile_exit_code(report) == 5
    assert report.coverage.surplus == 1
    assert report.coverage.surplus_keys == [f"corrida:{folder.name}"]


def test_a_run_that_is_not_in_the_database_is_missing(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    folder = _run_folder(workspace, cargable)
    hidden = tmp_path / "apartada"
    folder.rename(hidden)
    load_workspace(workspace, PRELIMINARY, database=base)
    hidden.rename(folder)
    report = reconcile(workspace, database=base, recompute=False)
    assert report.status == "incomplete"
    assert reconcile_exit_code(report) == 5
    assert f"corrida:{folder.name}" in report.coverage.missing_keys


def test_a_scenario_that_cannot_be_read_leaves_its_runs_unverified_not_equal(
    cargable: Loadable, base: str, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    load_workspace(workspace, PRELIMINARY, database=base)
    scenario = next((workspace / "escenarios").rglob(f"{cargable.scenario_id}.json"))
    scenario.write_bytes(b"{no es json")
    report = reconcile(workspace, database=base)
    assert report.runs_unverified == 4
    assert report.status != "equal"
    assert report.unverified
    assert reconcile_exit_code(report) != 0


def test_runs_whose_metrics_cannot_be_recalculated_leave_the_result_inconclusive(
    cargable: Loadable, base: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    load_workspace(workspace, PRELIMINARY, database=base)

    def cannot(*_: object, **__: object) -> None:
        raise DomainError(ErrorCode.INPUT_SCHEMA, "la salida de la corrida no se puede leer")

    monkeypatch.setattr("semaforo.bd.conciliacion.evaluate_run", cannot)
    report = reconcile(workspace, database=base)
    assert (report.runs_checked, report.runs_unverified, report.runs_recomputed) == (4, 4, 0)
    assert report.differences_total == 0  # nada difiere: simplemente no se pudo comprobar
    assert (report.status, reconcile_exit_code(report)) == ("inconclusive", 6)
    assert "no se pudieron verificar" in str(report.reason)


def test_a_run_that_cannot_be_measured_is_reported_and_does_not_stop_the_others(
    cargable: Loadable, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    ids = sorted(cargable.runs.values())
    for run_id in ids[:2]:
        remove_tree(workspace / "derivados" / "metricas" / cargable.case_id / run_id)
    (workspace / "ejecuciones" / ids[0] / "manifiesto.json").write_bytes(b"{no es json")
    report = publish_metrics(workspace)
    by_run = {outcome.run_id: outcome for outcome in report.runs}
    assert by_run[ids[0]].status == "failed"
    assert by_run[ids[1]].status == "published"
    assert report.counts["failed"] == 1
    assert report.counts["published"] == 1
    assert report.counts["already"] == 2
    assert by_run[ids[0]].detail
    assert (
        workspace / "derivados" / "metricas" / cargable.case_id / ids[1] / METRICS_FILE
    ).is_file()


def test_a_metrics_folder_that_is_not_valid_is_failed_not_published_over(
    cargable: Loadable, tmp_path: Path
) -> None:
    workspace = copy_workspace(cargable.workspace, tmp_path / "datos")
    run_id = cargable.runs[min(cargable.runs)]
    folder = workspace / "derivados" / "metricas" / cargable.case_id / run_id
    (folder / METRICS_FILE).write_bytes(json.dumps({"roto": True}).encode())
    report = publish_metrics(workspace)
    by_run = {outcome.run_id: outcome for outcome in report.runs}
    assert by_run[run_id].status == "failed"
    assert report.counts["failed"] == 1
