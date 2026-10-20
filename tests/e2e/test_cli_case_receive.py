"""Prueba de punta a punta de ``python -m semaforo case receive`` (F7 de DEV00).

Ejecuta la CLI como lo haría el analista, en un proceso aparte, y comprueba el JSON de salida y
los códigos de salida del diseño técnico: 0 completada, 2 entrada inválida, 3 dependencia
faltante, 4 fallo de proceso y 5 integridad o ruta no permitida.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from semaforo.trazabilidad.fs import remove_tree

pytestmark = pytest.mark.sumo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sumo"


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "datos"
    yield root
    remove_tree(root)


def cli(
    workspace: Path, source: Path, *extra: str, environment: dict[str, str] | None = None
) -> tuple[int, dict[str, object], str]:
    command = [
        sys.executable,
        "-m",
        "semaforo",
        "case",
        "receive",
        "--source",
        str(source),
        "--config",
        "demo.sumocfg",
        "--case-id",
        "SYNTHETIC_DEMO",
        "--workspace",
        str(workspace),
        *extra,
    ]
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        command,
        capture_output=True,
        check=False,
        timeout=300,
        env=environment,
    )
    report: dict[str, object] = json.loads(result.stdout.decode("utf-8"))
    return result.returncode, report, result.stderr.decode("utf-8", errors="replace")


def test_a_successful_reception_exits_with_zero(workspace: Path, sumo_binary: Path) -> None:
    code, report, stderr = cli(workspace, FIXTURES / "demo", "--sumo-bin", str(sumo_binary))
    assert code == 0, stderr
    assert report["proposed_status"] == "with_findings"
    reception = workspace / "derivados" / "recepcion" / str(report["reception_id"])
    assert (reception / "reception.json").is_file()
    assert "Recepción" in stderr


def test_a_failed_base_run_exits_with_four(workspace: Path, sumo_binary: Path) -> None:
    source = FIXTURES / "invalid" / "missing_edge"
    code, report, _ = cli(workspace, source, "--sumo-bin", str(sumo_binary))
    assert code == 4
    assert report["proposed_status"] == "failed"


def test_an_absolute_output_path_exits_with_five(workspace: Path, sumo_binary: Path) -> None:
    source = FIXTURES / "invalid" / "absolute_output"
    code, report, _ = cli(workspace, source, "--sumo-bin", str(sumo_binary))
    assert code == 5
    assert (report["status"], report["code"]) == ("error", "PATH_NOT_ALLOWED")


def test_a_missing_source_exits_with_two(workspace: Path, tmp_path: Path) -> None:
    code, report, _ = cli(workspace, tmp_path / "no-existe")
    assert code == 2
    assert (report["status"], report["code"]) == ("error", "INPUT_SCHEMA")
    assert str(tmp_path) not in json.dumps(report)


def test_a_missing_sumo_exits_with_three(workspace: Path, tmp_path: Path) -> None:
    environment = {**os.environ, "SUMO_HOME": str(tmp_path / "sin-sumo")}
    code, report, _ = cli(workspace, FIXTURES / "demo", environment=environment)
    assert code == 3
    assert (report["status"], report["code"]) == ("error", "DEPENDENCY_MISSING")


def run_cli(*arguments: str) -> tuple[int, dict[str, object]]:
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        [sys.executable, "-m", "semaforo", "case", *arguments],
        capture_output=True,
        check=False,
        timeout=300,
    )
    report: dict[str, object] = json.loads(result.stdout.decode("utf-8"))
    return result.returncode, report


def test_publish_report_and_compare(workspace: Path, sumo_binary: Path, tmp_path: Path) -> None:
    code, report, _ = cli(workspace, FIXTURES / "demo", "--sumo-bin", str(sumo_binary))
    assert code == 0
    reception_id = str(report["reception_id"])
    docs = tmp_path / "docs" / "recepcion"
    code, published = run_cli(
        "publish-report",
        "--reception-id",
        reception_id,
        "--workspace",
        str(workspace),
        "--destination",
        str(docs),
    )
    assert (code, published["status"]) == (0, "published")
    assert (docs / f"{reception_id}.md").is_file()
    code, comparison = run_cli(
        "compare", "--before", reception_id, "--after", reception_id, "--workspace", str(workspace)
    )
    assert (code, comparison["changes"]) == (0, [])


def test_missing_arguments_exit_with_two() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "semaforo", "case", "receive"],
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 2
