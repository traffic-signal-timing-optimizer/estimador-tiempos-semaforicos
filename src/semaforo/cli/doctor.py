"""Comando ``python -m semaforo doctor`` (DEV01): diagnóstico del entorno de trabajo.

Mide el equipo y SUMO (``semaforo.app.doctor_probe``) y aplica las reglas del diagnóstico
(``semaforo.app.doctor``). ``semaforo.cli.main`` escribe el diagnóstico en JSON por la salida
estándar y este resumen para la persona por la salida de error.
"""

import argparse
from pathlib import Path

from semaforo.app.doctor import build_report
from semaforo.app.doctor_models import DoctorReport
from semaforo.app.doctor_probe import measure_environment

CHECK_LABELS = {"ok": "bien", "warning": "AVISO", "error": "ERROR"}
STATUS_LABELS = {"ok": "todo bien", "warnings": "con avisos", "failed": "con errores"}


def configure_doctor(parser: argparse.ArgumentParser) -> None:
    """Argumentos propios de ``doctor``; ``--workspace`` y ``--debug`` los agrega ``main``."""
    parser.add_argument("--sumo-bin", type=Path, default=None, help="SUMO; por defecto, SUMO_HOME")


def run_doctor(workspace: Path, sumo: Path | None) -> DoctorReport:
    """Diagnóstico del equipo para la carpeta de trabajo ``workspace``."""
    return build_report(measure_environment(workspace, sumo))


def summary(report: DoctorReport) -> str:
    """Resumen para la persona: una línea por comprobación y el resultado final."""
    lines = [
        f"[{CHECK_LABELS[check.status]}] {check.name}: {check.message}" for check in report.checks
    ]
    result = STATUS_LABELS[report.status]
    lines.append(f"Diagnóstico {result} (código de salida {report.exit_code})")
    return "\n".join(lines)
