"""Prueba de punta a punta de ``python -m semaforo simulate run`` (F4 de DEV07).

Ejecuta el comando como lo haría el analista, en un proceso aparte, sobre una carpeta de entradas
que publicó DEV06, y comprueba el JSON de salida y los códigos de salida del diseño técnico:
0 exitosa, 2 entradas inválidas, 3 SUMO ausente, 4 fallida, tiempo agotado o cancelada y 5
integridad o ruta no permitida. La salida estándar lleva solo el JSON.
"""

import json
import os
import stat
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.app.simulate import run_prepared
from semaforo.simulacion.prepare import publish_inputs
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.store import RunSpec, RunWriter, read_run

pytestmark = pytest.mark.sumo


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    yield root
    remove_tree(root)


@pytest.fixture
def folder(tmp_path: Path) -> Iterator[Path]:
    yield publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    remove_tree(tmp_path / "entradas")


def cli(
    workspace: Path, inputs: Path, *extra: str, sumo: Path | None = None
) -> tuple[int, dict[str, object], str]:
    command = [
        sys.executable,
        "-m",
        "semaforo",
        "simulate",
        "run",
        "--inputs",
        str(inputs),
        "--workspace",
        str(workspace),
        *extra,
    ]
    if sumo is not None:
        command += ["--sumo-bin", str(sumo)]
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
        timeout=300,
        check=False,
    )
    return result.returncode, json.loads(result.stdout), result.stderr


def test_a_successful_run_exits_with_zero_and_reports_everything(
    workspace: Path, folder: Path, sumo_binary: Path
) -> None:
    code, report, summary = cli(workspace, folder, sumo=sumo_binary)
    assert code == 0
    assert report["status"] == "succeeded"
    assert report["exit_code"] == 0
    assert report["error_code"] is None
    assert report["recovered_interrupted"] == []
    run_id = str(report["run_id"])
    assert report["path"] == f"ejecuciones/{run_id}"
    assert f"Corrida {run_id}: succeeded" in summary
    manifest = read_run(workspace / "ejecuciones", run_id)  # la corrida quedó publicada y íntegra
    assert manifest.status == "succeeded"
    timing = report["timing"]
    assert isinstance(timing, dict)
    assert timing["termination"] == "completed"
    conciliation = report["conciliation"]
    assert isinstance(conciliation, dict)
    assert conciliation["vehicles_total"] == 160
    summary_of_run = report["summary"]
    assert isinstance(summary_of_run, dict)
    assert summary_of_run["vehicles_inserted"] > 0


def test_a_timeout_exits_with_four_and_says_failed(
    workspace: Path, folder: Path, sumo_binary: Path
) -> None:
    code, report, _ = cli(workspace, folder, "--wall-timeout", "0.001", sumo=sumo_binary)
    assert code == 4
    assert report["status"] == "failed"
    assert report["error_code"] == "SIM_TIMEOUT"
    assert report["timing"] is not None


def test_a_failed_run_is_retried_with_a_new_run_id(
    workspace: Path, folder: Path, sumo_binary: Path
) -> None:
    _, first, _ = cli(workspace, folder, "--wall-timeout", "0.001", sumo=sumo_binary)
    code, second, _ = cli(workspace, folder, "--retry-of", str(first["run_id"]), sumo=sumo_binary)
    assert code == 0
    assert second["status"] == "succeeded"
    assert second["retry_of"] == first["run_id"]
    assert second["run_id"] != first["run_id"]
    assert read_run(workspace / "ejecuciones", str(first["run_id"])).status == "failed"


def test_a_succeeded_run_cannot_be_retried_and_exits_with_two(
    workspace: Path, folder: Path, sumo_binary: Path
) -> None:
    _, first, _ = cli(workspace, folder, sumo=sumo_binary)
    code, report, summary = cli(
        workspace, folder, "--retry-of", str(first["run_id"]), sumo=sumo_binary
    )
    assert code == 2
    assert (report["status"], report["code"], report["field"]) == (
        "error",
        "INPUT_SCHEMA",
        "retry_of",
    )
    assert "INPUT_SCHEMA" in summary
    assert sorted(p.name for p in (workspace / "ejecuciones").iterdir()) == [first["run_id"]]


def test_an_inputs_folder_that_does_not_exist_exits_with_two(
    workspace: Path, tmp_path: Path, sumo_binary: Path
) -> None:
    code, report, _ = cli(workspace, tmp_path / "no-existe", sumo=sumo_binary)
    assert (code, report["code"]) == (2, "INPUT_SCHEMA")


def test_a_missing_sumo_exits_with_three(workspace: Path, folder: Path, tmp_path: Path) -> None:
    code, report, _ = cli(workspace, folder, sumo=tmp_path / "no-existe" / "sumo.exe")
    assert (code, report["code"]) == (3, "DEPENDENCY_MISSING")


def test_an_altered_inputs_folder_exits_with_five_and_runs_nothing(
    workspace: Path, folder: Path, sumo_binary: Path
) -> None:
    program = next(folder.glob("*.tll.xml"))
    os.chmod(program, stat.S_IWRITE | stat.S_IREAD)
    program.write_text(program.read_text(encoding="utf-8") + "<!-- cambio -->", encoding="utf-8")
    code, report, _ = cli(workspace, folder, sumo=sumo_binary)
    assert (code, report["code"]) == (5, "HASH_MISMATCH")
    assert not (workspace / "ejecuciones").exists()


def test_a_run_that_fell_earlier_is_set_aside_and_reported(
    workspace: Path, folder: Path, sumo_binary: Path
) -> None:
    caida = "20261101T100000Z_simulation_caida000"
    spec = RunSpec(kind="simulation", case_id="X", case_version="1")
    with pytest.raises(RuntimeError), RunWriter(workspace / "ejecuciones", spec, run_id=caida):
        raise RuntimeError("caída simulada")
    code, report, summary = cli(workspace, folder, sumo=sumo_binary)
    assert code == 0
    assert report["recovered_interrupted"] == [f".incompletas/{caida}"]
    assert f".incompletas/{caida}" in summary


def test_a_cancelled_run_reports_cancelled_with_exit_four(
    workspace: Path, folder: Path, sumo_binary: Path
) -> None:
    cancel = threading.Event()
    cancel.set()
    report = run_prepared(folder, workspace, sumo=sumo_binary, cancel=cancel)
    assert (report.status, report.exit_code, report.error_code) == ("cancelled", 4, None)
    assert report.timing is not None
    assert report.timing.termination == "cancelled"
    assert report.conciliation is None  # una cancelada no se concilia
