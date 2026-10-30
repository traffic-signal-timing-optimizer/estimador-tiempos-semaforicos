"""Diagnóstico con el SUMO instalado (DEV01, F2). Se salta si SUMO no está (``SUMO_HOME``)."""

from pathlib import Path

import pytest

from semaforo.app.doctor import build_report
from semaforo.app.doctor_probe import measure_environment

pytestmark = pytest.mark.sumo


def test_the_installed_sumo_is_found_and_answers_its_version(
    tmp_path: Path, sumo_binary: Path
) -> None:
    facts = measure_environment(tmp_path, sumo=sumo_binary)
    assert facts.sumo_binary == str(sumo_binary)
    assert facts.sumo_version is not None
    assert facts.sumo_problem is None
    report = build_report(facts)
    sumo_checks = [check for check in report.checks if check.name.startswith("sumo")]
    assert all(check.status != "error" for check in sumo_checks)
