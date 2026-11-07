"""Los comandos ``bd`` de la línea de comandos (DEV31 F3)."""

import json
from pathlib import Path

import pytest

from bd_tools import Loadable
from semaforo.cli.main import main

pytestmark = [pytest.mark.bd, pytest.mark.sumo]


def _run(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, dict[str, object]]:
    code = main(list(arguments))
    out = capsys.readouterr().out
    return code, json.loads(out)


def _outcome(report: dict[str, object]) -> object:
    reference = report["reference"]
    assert isinstance(reference, dict)
    return reference["outcome"]  # pyright: ignore[reportUnknownVariableType]


def test_load_then_verify_with_fingerprints_from_the_command_line(
    cargable: Loadable, base: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    where = ("--workspace", str(cargable.workspace), "--base", base)
    code, report = _run(capsys, "bd", "cargar", *where, "--preliminar")
    assert code == 0
    assert report["status"] == "completed"
    counts = report["counts"]
    assert isinstance(counts, dict)
    assert counts["loaded"] == 8
    fingerprints = tmp_path / "huellas.json"
    code, checked = _run(
        capsys, "bd", "verificar", *where, "--sin-referencia", "--huellas", str(fingerprints)
    )
    assert (code, checked["status"]) == (0, "intact")
    written = json.loads(fingerprints.read_text(encoding="utf-8"))
    assert written["content_sha256"] == report["content_sha256"]
    assert len(written["roots"]) == checked["roots_checked"]
    assert all(str(r["artefacto_id"]).startswith("datos:") for r in written["roots"])
    assert written["algoritmo_huella"] and written["reglas_sha256"]
    # Con ese archivo como referencia la base coincide; con otra versión del esquema, no concluye.
    code, same = _run(capsys, "bd", "verificar", *where, "--referencia", str(fingerprints))
    assert (code, same["status"]) == (0, "intact")
    assert _outcome(same) == "coincide"
    written["schema_version_db"] = "sql-otra-version"
    fingerprints.write_text(json.dumps(written), encoding="utf-8")
    code, other = _run(capsys, "bd", "verificar", *where, "--referencia", str(fingerprints))
    assert (code, other["status"]) == (6, "inconclusive")
    assert _outcome(other) == "no_concluyente"


def test_qa34_reports_carry_no_machine_paths(
    cargable: Loadable, base: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        ["bd", "cargar", "--workspace", str(cargable.workspace), "--base", base, "--preliminar"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert str(cargable.workspace) not in out
    assert str(cargable.workspace).replace("\\", "\\\\") not in out


def test_without_the_database_the_command_says_so_and_exits_3(
    cargable: Loadable, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(
        [
            "bd",
            "cargar",
            "--workspace",
            str(cargable.workspace),
            "--base",
            "semaforo_pruebas_no_existe",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 3
    assert out["code"] == "DEPENDENCY_MISSING"
