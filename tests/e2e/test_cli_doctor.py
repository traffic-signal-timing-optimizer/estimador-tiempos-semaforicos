"""Prueba de punta a punta de ``python -m semaforo doctor`` (DEV01, F3).

Ejecuta el comando como lo haría la persona, en un proceso aparte, y comprueba el JSON de la salida
estándar, el resumen de la salida de error y los códigos de salida del diseño técnico.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from semaforo.app.doctor_models import DoctorReport


def doctor(*arguments: str) -> tuple[int, DoctorReport, str]:
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        [sys.executable, "-m", "semaforo", "doctor", *arguments],
        capture_output=True,
        check=False,
        timeout=120,
    )
    report = DoctorReport.model_validate_json(result.stdout.decode("utf-8"))
    return result.returncode, report, result.stderr.decode("utf-8", errors="replace")


def statuses(report: DoctorReport) -> dict[str, str]:
    return {check.name: check.status for check in report.checks}


@pytest.mark.sumo
def test_this_computer_passes_with_the_installed_sumo(tmp_path: Path, sumo_binary: Path) -> None:
    code, report, summary = doctor("--workspace", str(tmp_path), "--sumo-bin", str(sumo_binary))
    assert report.status != "failed"
    assert code == 0
    assert statuses(report)["sumo"] == "ok"
    assert statuses(report)["workspace"] == "ok"
    assert "Diagnóstico" in summary
    assert list(tmp_path.iterdir()) == []


def test_a_missing_sumo_bin_exits_with_three(tmp_path: Path) -> None:
    missing = tmp_path / "no-existe" / "sumo.exe"
    code, report, _ = doctor("--workspace", str(tmp_path), "--sumo-bin", str(missing))
    assert code == 3
    assert statuses(report)["sumo"] == "error"


def test_a_missing_workspace_exits_with_two(tmp_path: Path) -> None:
    missing = tmp_path / "no-existe"
    code, report, _ = doctor("--workspace", str(missing), "--sumo-bin", str(tmp_path / "x.exe"))
    assert code == 2
    assert statuses(report)["workspace"] == "error"
    assert not missing.exists()
