"""Comando ``python -m semaforo doctor`` sin medir el equipo ni ejecutar SUMO (DEV01, F3)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from semaforo.app.doctor import EXPECTED_SUMO_VERSION, EnvironmentFacts, WorkspaceFacts
from semaforo.app.doctor_models import DoctorReport
from semaforo.cli.main import main

GIB = 1024**3
GOOD = EnvironmentFacts(
    python_version="3.12.3",
    packages={"semaforo": "0.1.0", "pydantic": "2.14.1", "defusedxml": "0.7.1"},
    operating_system="Windows-11-10.0.26200-SP0",
    cpu_count=16,
    memory_total_bytes=16 * GIB,
    memory_available_bytes=8 * GIB,
    workspace=WorkspaceFacts(
        path="datos", exists=True, is_directory=True, is_link=False, writable=True
    ),
    disk_free_bytes=100 * GIB,
    sumo_binary="C:/Sumo/bin/sumo.exe",
    sumo_version=EXPECTED_SUMO_VERSION,
)


def measuring(facts: EnvironmentFacts, calls: list[tuple[Path, Path | None]]) -> object:
    def fake(workspace: Path, sumo: Path | None) -> EnvironmentFacts:
        calls.append((workspace, sumo))
        return facts

    return fake


def run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    facts: EnvironmentFacts,
    *arguments: str,
) -> tuple[int, DoctorReport, str, list[tuple[Path, Path | None]]]:
    calls: list[tuple[Path, Path | None]] = []
    monkeypatch.setattr("semaforo.cli.doctor.measure_environment", measuring(facts, calls))
    code = main(["doctor", *arguments])
    output = capsys.readouterr()
    return code, DoctorReport.model_validate_json(output.out), output.err, calls


def test_a_good_environment_exits_with_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report, summary, _ = run(monkeypatch, capsys, GOOD)
    assert code == 0
    assert report.status == "ok"
    assert "Diagnóstico todo bien (código de salida 0)" in summary
    assert "[bien] python: Python 3.12.3" in summary


def test_warnings_still_exit_with_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, report, summary, _ = run(monkeypatch, capsys, replace(GOOD, sumo_version="1.26.0"))
    assert code == 0
    assert report.status == "warnings"
    assert "[AVISO] sumo_version" in summary
    assert "con avisos" in summary


@pytest.mark.parametrize(
    ("facts", "exit_code"),
    [
        (replace(GOOD, sumo_binary=None, sumo_version=None), 3),
        (replace(GOOD, workspace=replace(GOOD.workspace, exists=False)), 2),
        (replace(GOOD, workspace=replace(GOOD.workspace, is_link=True)), 5),
    ],
    ids=["no-sumo", "no-workspace", "linked-workspace"],
)
def test_an_error_sets_the_exit_code_of_the_design(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    facts: EnvironmentFacts,
    exit_code: int,
) -> None:
    code, report, summary, _ = run(monkeypatch, capsys, facts)
    assert code == exit_code
    assert report.exit_code == exit_code
    assert report.status == "failed"
    assert "[ERROR]" in summary
    assert "con errores" in summary


def test_the_workspace_defaults_to_datos_and_sumo_to_sumo_home(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    *_, calls = run(monkeypatch, capsys, GOOD)
    assert calls == [(Path("datos"), None)]


def test_the_arguments_reach_the_measurement(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = ("--workspace", "otra", "--sumo-bin", "C:/Sumo/bin/sumo.exe")
    *_, calls = run(monkeypatch, capsys, GOOD, *arguments)
    assert calls == [(Path("otra"), Path("C:/Sumo/bin/sumo.exe"))]


def test_standard_output_is_only_the_json_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("semaforo.cli.doctor.measure_environment", measuring(GOOD, []))
    main(["doctor"])
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == "1.0.0"
    assert data["checks"][0]["name"] == "python"


def test_an_unexpected_error_is_internal_and_hides_the_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(_workspace: Path, _sumo: Path | None) -> EnvironmentFacts:
        raise RuntimeError("C:\\secreto")

    monkeypatch.setattr("semaforo.cli.doctor.measure_environment", broken)
    assert main(["doctor"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["code"] == "INTERNAL"
    assert "secreto" not in output.out + output.err


def test_debug_shows_the_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_workspace: Path, _sumo: Path | None) -> EnvironmentFacts:
        raise RuntimeError("detalle")

    monkeypatch.setattr("semaforo.cli.doctor.measure_environment", broken)
    with pytest.raises(RuntimeError, match="detalle"):
        main(["doctor", "--debug"])


def test_an_unknown_argument_exits_with_two() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["doctor", "--no-existe"])
    assert raised.value.code == 2
