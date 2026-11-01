"""Seguridad de la corrida de SUMO (QA10 en DEV07): sin shell ni rutas de la máquina en informes.

Cubre lo que se ejecuta en `simulate run`. Lo demás de QA10 tiene su prueba en otro archivo:
XML con DTD, bombas de entidades y gzip excesivo (`test_tripinfo.py`, `test_reconcile.py`),
recorrido de carpetas y enlaces (`test_run_inputs.py`, `test_runner.py`, `test_run_store.py`) y
entradas de DEV06 (`test_dev06_inputs.py`).
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.app.simulate import run_prepared
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.prepare import publish_inputs
from semaforo.simulacion.reconcile import reconcile_run
from semaforo.trazabilidad.fs import remove_tree

pytestmark = pytest.mark.sumo

# Caracteres que un shell interpretaría: separadores, sustituciones, variables y espacios.
NASTY = "ent & mkdir pwned & echo x;y %PATH% ^z (1) $HOME"


@pytest.fixture
def folder(tmp_path: Path) -> Iterator[Path]:
    yield publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    remove_tree(tmp_path / "entradas")


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    yield root
    remove_tree(root)


def test_folders_with_shell_metacharacters_run_and_inject_nothing(
    tmp_path: Path, folder: Path, sumo_binary: Path
) -> None:
    inputs = tmp_path / NASTY / "entradas"
    shutil.copytree(folder, inputs)
    elsewhere = tmp_path / NASTY / "datos"
    working = tmp_path / "cwd"
    working.mkdir()
    command = [
        sys.executable,
        "-m",
        "semaforo",
        "simulate",
        "run",
        "--inputs",
        str(inputs),
        "--workspace",
        str(elsewhere),
        "--sumo-bin",
        str(sumo_binary),
    ]
    try:
        result = subprocess.run(  # noqa: S603  (lista de argumentos, sin shell)
            command, capture_output=True, text=True, encoding="utf-8", cwd=working, check=False,
            env=dict(os.environ), timeout=300,
        )  # fmt: skip
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == "succeeded"
        assert not (working / "pwned").exists()
        assert not (tmp_path / NASTY / "pwned").exists()
        assert not (tmp_path / "pwned").exists()
    finally:
        remove_tree(elsewhere)
        remove_tree(tmp_path / NASTY / "entradas")


def test_the_report_and_the_manifest_carry_no_path_of_this_machine(
    tmp_path: Path, folder: Path, workspace: Path, sumo_binary: Path
) -> None:
    ok = run_prepared(folder, workspace, sumo=sumo_binary)
    timed_out = run_prepared(folder, workspace, sumo=sumo_binary, wall_timeout_s=0.001)
    assert (ok.status, timed_out.status) == ("succeeded", "failed")
    for report in (ok, timed_out):
        shown = report.model_dump_json()
        manifest = (workspace / report.path / "manifest.json").read_text(encoding="utf-8")
        for text in (shown, manifest):
            assert str(tmp_path) not in text
            assert str(tmp_path).replace("\\", "/") not in text.replace("\\\\", "/")
            assert str(sumo_binary.parent) not in text


def test_a_retry_identifier_cannot_leave_the_runs_folder(
    folder: Path, workspace: Path, sumo_binary: Path
) -> None:
    for hostile in ("../datos", "..\\datos", "C:\\Windows", "/etc/passwd", "a/b", ".oculta"):
        with pytest.raises(DomainError) as raised:
            run_prepared(folder, workspace, sumo=sumo_binary, retry_of=hostile)
        assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (workspace / "ejecuciones").exists()  # no se creó ni una corrida


def test_a_conciliation_refuses_a_run_whose_files_were_changed_afterwards(
    folder: Path, workspace: Path, sumo_binary: Path
) -> None:
    report = run_prepared(folder, workspace, sumo=sumo_binary)
    runs = workspace / "ejecuciones"
    reconcile_run(folder, runs, report.run_id)  # intacta: se concilia
    tripinfo = runs / report.run_id / "outputs" / "tripinfo.xml"
    os.chmod(tripinfo, 0o600)
    tripinfo.write_text(tripinfo.read_text(encoding="utf-8") + "<!-- cambio -->", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        reconcile_run(folder, runs, report.run_id)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
