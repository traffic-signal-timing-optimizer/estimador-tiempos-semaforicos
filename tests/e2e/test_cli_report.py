"""Prueba de punta a punta de ``python -m semaforo report`` (DEV09 F4).

Ejecuta el comando como lo haría el analista, en un proceso aparte, y comprueba la salida estándar
(solo el JSON), los mensajes para la persona, los códigos de salida y las páginas publicadas.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from html_checks import assert_safe_page
from quality_tools import publish_demo_quality, write_case


def cli(cwd: Path, *arguments: str) -> tuple[int, dict[str, object], str]:
    result = subprocess.run(  # noqa: S603  (intérprete actual y argumentos fijos)
        [sys.executable, "-m", "semaforo", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ),
        cwd=cwd,
        timeout=120,
        check=False,
    )
    return result.returncode, json.loads(result.stdout), result.stderr


def test_the_case_report_is_published_from_a_separate_process(tmp_path: Path) -> None:
    case = write_case(tmp_path / "caso")
    code, data, message = cli(
        tmp_path, "report", "case", "--case", str(case), "--workspace", "datos"
    )
    assert code == 0
    assert data["status"] == "published"
    assert data["case_status"] == "valid"
    page = tmp_path / "datos" / str(data["index"])
    seen = assert_safe_page(page.read_text(encoding="utf-8"))
    assert "Informe del caso: SYNTHETIC_DEMO" in seen.visible_text
    assert str(page.resolve()) in message
    assert "Estado del caso SYNTHETIC_DEMO: válido" in message


def test_the_data_report_is_published_from_a_separate_process(tmp_path: Path) -> None:
    case = write_case(tmp_path / "caso")
    quality = publish_demo_quality(tmp_path / "calidad", tmp_path / "trabajo")
    code, data, message = cli(
        tmp_path,
        "report",
        "data",
        "--case",
        str(case),
        "--quality-report",
        str(quality),
        "--workspace",
        "datos",
    )
    assert code == 0
    assert data["kind"] == "datos"
    page = tmp_path / "datos" / str(data["index"])
    seen = assert_safe_page(page.read_text(encoding="utf-8"))
    assert "Informe de los datos: SYNTHETIC_DEMO" in seen.visible_text
    assert "Informe de datos publicado" in message


def test_the_error_codes_of_the_design_are_returned(tmp_path: Path) -> None:
    code, data, message = cli(
        tmp_path,
        "report",
        "case",
        "--case",
        str(tmp_path / "no-existe.json"),
        "--workspace",
        "datos",
    )
    assert code == 2
    assert data["code"] == "INPUT_SCHEMA"
    assert "Error INPUT_SCHEMA" in message
    assert not (tmp_path / "datos").exists()
