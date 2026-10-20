"""Comprueba los fixtures sintéticos y el validador de contratos de referencia."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
VALIDATOR = ROOT / "tools" / "contracts" / "validar_paquete.py"
CONTRACT_FIXTURES = [
    "case",
    "label",
    "model_manifest",
    "protocol",
    "request",
    "response",
    "run_manifest",
    "scenario",
    "split",
]
EXTRA_FIXTURES = [
    "scenario_test.json",
    "scenario_validation.json",
    "aforos.csv",
    "expected_normalization.json",
]
NEGATIVE_FIXTURES = 19


def test_fixture_files_exist() -> None:
    expected = {f"{name}.json" for name in CONTRACT_FIXTURES} | set(EXTRA_FIXTURES)
    assert {path.name for path in FIXTURES.iterdir() if path.is_file()} == expected


def test_reference_validator_passes() -> None:
    # Comando fijo: intérprete actual y ruta del repositorio, sin entrada externa.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-B", str(VALIDATOR)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    report: dict[str, object] = json.loads(result.stdout)
    assert report["status"] == "passed"
    assert report["negative_fixtures"] == NEGATIVE_FIXTURES
