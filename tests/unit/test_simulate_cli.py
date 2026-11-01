"""El comando ``python -m semaforo simulate run`` sin ejecutar SUMO (DEV07 F4, D12)."""

import json
from pathlib import Path
from typing import Any

import pytest

from semaforo.app.simulate import RunReport
from semaforo.cli.main import main
from semaforo.dominio.errors import DomainError, ErrorCode

RUN_ID = "20261101T150000Z_simulation_abcd1234"


def report(status: str = "succeeded", exit_code: int = 0, **changes: Any) -> RunReport:  # noqa: ANN401
    fields: dict[str, Any] = {
        "status": status,
        "run_id": RUN_ID,
        "path": f"ejecuciones/{RUN_ID}",
        "retry_of": None,
        "scenario_id": "ESC_1",
        "error_code": None,
        "error_message": None,
        "timing": None,
        "summary": None,
        "conciliation": None,
        "recovered_interrupted": [],
        "exit_code": exit_code,
    }
    fields.update(changes)
    return RunReport.model_validate(fields)


class Recorder:
    def __init__(self, result: RunReport | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> RunReport:  # noqa: ANN401
        self.calls.append((args, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def install(monkeypatch: pytest.MonkeyPatch, result: RunReport | BaseException) -> Recorder:
    recorder = Recorder(result)
    monkeypatch.setattr("semaforo.cli.main.run_prepared", recorder)
    return recorder


# --- el informe y el código de salida ---------------------------------------------------------


def test_standard_output_is_only_the_json_report_and_the_exit_code_is_its_own(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, report())
    assert main(["simulate", "run", "--inputs", "entradas"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == json.loads(report().model_dump_json())
    assert f"Corrida {RUN_ID}: succeeded" in output.err


@pytest.mark.parametrize(
    ("status", "code"),
    [("failed", 4), ("cancelled", 4)],
)
def test_a_failed_or_cancelled_run_keeps_its_status_in_the_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    code: int,
) -> None:
    install(monkeypatch, report(status, code))
    assert main(["simulate", "run", "--inputs", "entradas"]) == code
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_the_summary_for_the_person_names_the_reason_and_the_recovered_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(
        monkeypatch,
        report(
            "failed",
            4,
            error_code="SIM_TIMEOUT",
            error_message="SUMO superó el límite",
            recovered_interrupted=[".incompletas/uno", ".incompletas/dos"],
        ),
    )
    main(["simulate", "run", "--inputs", "entradas"])
    error = capsys.readouterr().err
    assert "Motivo: SIM_TIMEOUT: SUMO superó el límite" in error
    assert "Corridas caídas apartadas: .incompletas/uno, .incompletas/dos" in error


def test_a_clean_run_does_not_mention_a_reason_or_recovered_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, report())
    main(["simulate", "run", "--inputs", "entradas"])
    error = capsys.readouterr().err
    assert "Motivo" not in error
    assert "apartadas" not in error


# --- argumentos -------------------------------------------------------------------------------


def test_the_arguments_reach_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = install(monkeypatch, report())
    main(
        [
            "simulate",
            "run",
            "--inputs",
            "entradas",
            "--workspace",
            "mi-espacio",
            "--sumo-bin",
            "sumo.exe",
            "--wall-timeout",
            "30.5",
            "--retry-of",
            "20261101T100000Z_simulation_anterior",
        ]
    )
    ((args, options),) = recorder.calls
    assert args == (Path("entradas"), Path("mi-espacio"))
    assert options == {
        "sumo": Path("sumo.exe"),
        "wall_timeout_s": 30.5,
        "retry_of": "20261101T100000Z_simulation_anterior",
    }


def test_the_defaults_are_the_workspace_datos_and_no_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = install(monkeypatch, report())
    main(["simulate", "run", "--inputs", "entradas"])
    ((args, options),) = recorder.calls
    assert args == (Path("entradas"), Path("datos"))
    assert options == {"sumo": None, "wall_timeout_s": None, "retry_of": None}


@pytest.mark.parametrize("seconds", ["0", "-5", "abc", "inf", "nan", ""])
def test_a_timeout_that_is_not_a_positive_number_exits_with_two(seconds: str) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["simulate", "run", "--inputs", "entradas", "--wall-timeout", seconds])
    assert raised.value.code == 2


def test_the_inputs_folder_is_required() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["simulate", "run"])
    assert raised.value.code == 2


def test_an_unknown_argument_exits_with_two() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["simulate", "run", "--inputs", "entradas", "--no-existe"])
    assert raised.value.code == 2


# --- errores antes de ejecutar ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [
        (ErrorCode.INPUT_SCHEMA, 2),
        (ErrorCode.DEPENDENCY_MISSING, 3),
        (ErrorCode.SIM_FAILED, 4),
        (ErrorCode.HASH_MISMATCH, 5),
        (ErrorCode.PATH_NOT_ALLOWED, 5),
    ],
)
def test_an_error_before_running_becomes_a_json_report_and_its_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: ErrorCode,
    exit_code: int,
) -> None:
    install(monkeypatch, DomainError(code, "no se pudo", "retry_of"))
    assert main(["simulate", "run", "--inputs", "entradas"]) == exit_code
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "status": "error",
        "code": code.value,
        "field": "retry_of",
        "message": "no se pudo",
    }
    assert code.value in output.err


def test_an_unexpected_error_is_internal_and_hides_the_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, RuntimeError("C:\\secreto"))
    assert main(["simulate", "run", "--inputs", "entradas"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["code"] == "INTERNAL"
    assert "secreto" not in output.out + output.err


def test_debug_shows_the_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, RuntimeError("detalle"))
    with pytest.raises(RuntimeError, match="detalle"):
        main(["simulate", "run", "--inputs", "entradas", "--debug"])
