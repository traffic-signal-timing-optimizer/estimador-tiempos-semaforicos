"""Prueba de punta a punta de ``runs verify`` y ``runs compare`` (F4 de DEV08).

Corre los comandos como lo haría el analista, en un proceso aparte, sobre un espacio de trabajo
sintético completo con dos corridas reales de SUMO.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from semaforo.app.simulate import run_prepared
from semaforo.trazabilidad.fs import remove_tree
from workspace_tools import build_workspace, tamper

pytestmark = pytest.mark.sumo


@pytest.fixture
def prepared(tmp_path: Path, sumo_binary: Path) -> Iterator[tuple[Path, str, str]]:
    workspace, inputs = build_workspace(tmp_path)
    first = run_prepared(inputs, workspace, sumo=sumo_binary).run_id
    second = run_prepared(inputs, workspace, sumo=sumo_binary).run_id
    yield workspace, first, second
    remove_tree(workspace)


def cli(workspace: Path, *arguments: str) -> tuple[int, dict[str, object], str]:
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        [sys.executable, "-m", "semaforo", "runs", *arguments, "--workspace", str(workspace)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
        timeout=300,
        check=False,
    )
    return result.returncode, json.loads(result.stdout), result.stderr


def test_an_intact_workspace_exits_with_zero(prepared: tuple[Path, str, str]) -> None:
    workspace, _, _ = prepared
    code, report, summary = cli(workspace, "verify")
    assert (code, report["status"], report["exit_code"]) == (0, "intact", 0)
    assert "0 alteradas" in summary


def test_an_altered_workspace_exits_with_five(prepared: tuple[Path, str, str]) -> None:
    workspace, first, _ = prepared
    tamper(workspace / "ejecuciones" / first / "outputs" / "tripinfo.xml")
    code, report, summary = cli(workspace, "verify")
    assert (code, report["status"]) == (5, "altered")
    assert f"ALTERADA ejecuciones/{first}" in summary


def test_the_chain_of_a_run_is_complete(prepared: tuple[Path, str, str]) -> None:
    workspace, first, _ = prepared
    code, trace, _ = cli(workspace, "verify", "--run-id", first)
    assert (code, trace["status"]) == (0, "complete")
    links = cast("list[dict[str, str]]", trace["links"])
    assert [link["kind"] for link in links] == ["run", "inputs_copy", "inputs", "program", "case"]


def test_two_runs_of_the_same_inputs_are_a_replica(prepared: tuple[Path, str, str]) -> None:
    workspace, first, second = prepared
    code, result, summary = cli(workspace, "compare", "--run-a", first, "--run-b", second)
    assert (code, result["status"]) == (0, "equivalent")
    path = str(result["path"])
    assert path.startswith("derivados/replicas/")
    assert (workspace / path / "replica.json").is_file()
    assert f"Réplica {first} y {second}: equivalent" in summary
    code, report, _ = cli(workspace, "verify")
    assert (code, report["status"]) == (0, "intact")  # el reporte publicado también se revisa


def test_comparing_an_altered_run_exits_with_five(prepared: tuple[Path, str, str]) -> None:
    workspace, first, second = prepared
    tamper(workspace / "ejecuciones" / second / "outputs" / "tripinfo.xml")
    code, error, _ = cli(workspace, "compare", "--run-a", first, "--run-b", second)
    assert (code, error["code"]) == (5, "HASH_MISMATCH")
    assert not (workspace / "derivados" / "replicas").exists()
