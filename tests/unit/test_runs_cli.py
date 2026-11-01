"""Comandos ``runs verify`` y ``runs compare`` sin SUMO (DEV08 F4, decisión D11)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from semaforo.app.integrity import (
    Link,
    RunTrace,
    WorkspaceItem,
    WorkspaceReport,
    trace_exit_code,
    workspace_exit_code,
)
from semaforo.cli.main import main
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.replica import ReplicaReport, Tolerance

NOW = datetime(2026, 11, 1, 23, 30, tzinfo=UTC)
RUN = "20261101T233000Z_simulation_abcd1234"


def workspace_report(*statuses: str) -> WorkspaceReport:
    items = [
        WorkspaceItem(family="runs", path=f"ejecuciones/r{n}", status=status, detail="x")  # type: ignore[arg-type]
        for n, status in enumerate(statuses)
    ]
    counts = {
        s: statuses.count(s) for s in ("intact", "altered", "incomplete", "temporary", "unknown")
    }
    return WorkspaceReport(
        checked_at=NOW,
        status="altered" if "altered" in statuses else "intact",
        counts=counts,
        items=items,
    )


def trace(*statuses: str) -> RunTrace:
    links = [Link(kind="run", status=s, path="ejecuciones/x", detail=None) for s in statuses]  # type: ignore[arg-type]
    complete = all(s == "verified" for s in statuses)
    return RunTrace(run_id=RUN, status="complete" if complete else "broken", links=links)


def replica(verdict: str = "equivalent") -> ReplicaReport:
    return ReplicaReport(
        created_at=NOW,
        run_a="A",
        run_b="B",
        case_id="C",
        case_version="1",
        scenario_id=None,
        seed_a=1,
        seed_b=1,
        inputs_equal=True,
        input_differences=[],
        tolerance=Tolerance(),
        files=[],
        verdict=verdict,  # type: ignore[arg-type]
        reasons=[] if verdict == "equivalent" else ["outputs/tripinfo.xml: cambia"],
    )


class Recorder:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> object:  # noqa: ANN401
        self.calls.append((args, kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def install(monkeypatch: pytest.MonkeyPatch, name: str, result: object) -> Recorder:
    recorder = Recorder(result)
    monkeypatch.setattr(f"semaforo.cli.main.{name}", recorder)
    return recorder


# --- códigos de salida ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "code"),
    [((), 0), (("intact", "unknown", "temporary", "incomplete"), 0), (("intact", "altered"), 5)],
)
def test_the_workspace_exit_code(statuses: tuple[str, ...], code: int) -> None:
    assert workspace_exit_code(workspace_report(*statuses)) == code


@pytest.mark.parametrize(
    ("statuses", "code"),
    [
        (("verified", "verified"), 0),
        (("verified", "altered", "not_found"), 5),
        (("verified", "not_found"), 3),
        (("verified", "changed"), 3),
        (("verified", "incomplete"), 3),
    ],
)
def test_the_trace_exit_code(statuses: tuple[str, ...], code: int) -> None:
    assert trace_exit_code(trace(*statuses)) == code


# --- runs verify ------------------------------------------------------------------------------


def test_verify_reviews_the_whole_workspace_and_prints_only_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = install(monkeypatch, "verify_workspace", workspace_report("intact", "altered"))
    assert main(["runs", "verify", "--workspace", "mi-espacio"]) == 5
    ((args, _),) = recorder.calls
    assert args == (Path("mi-espacio"),)
    output = capsys.readouterr()
    data = json.loads(output.out)
    assert (data["status"], data["exit_code"]) == ("altered", 5)
    assert "ALTERADA ejecuciones/r1: x" in output.err
    assert "1 íntegras, 1 alteradas" in output.err


def test_verify_uses_datos_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = install(monkeypatch, "verify_workspace", workspace_report())
    assert main(["runs", "verify"]) == 0
    assert recorder.calls[0][0] == (Path("datos"),)


def test_verify_with_a_run_id_traces_that_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = install(monkeypatch, "trace_run", trace("verified", "not_found"))
    assert main(["runs", "verify", "--run-id", RUN]) == 3
    assert recorder.calls[0][0] == (Path("datos"), RUN)
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "broken"
    assert f"Corrida {RUN}: cadena broken" in output.err
    assert "[not_found] run: ejecuciones/x" in output.err


def test_verify_of_a_run_that_does_not_exist_is_an_input_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch, "trace_run", DomainError(ErrorCode.INPUT_SCHEMA, "no existe", "run_id"))
    assert main(["runs", "verify", "--run-id", RUN]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INPUT_SCHEMA"


# --- runs compare -----------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", ["equivalent", "different"])
def test_compare_registers_the_report_and_exits_with_zero_either_way(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verdict: str,
) -> None:
    folder = Path("datos") / "derivados" / "replicas" / "R1"
    install(monkeypatch, "replicate", (replica(verdict), folder))
    assert main(["runs", "compare", "--run-a", "A", "--run-b", "B"]) == 0
    output = capsys.readouterr()
    data = json.loads(output.out)
    assert (data["status"], data["path"], data["exit_code"]) == (
        verdict,
        "derivados/replicas/R1",
        0,
    )
    assert data["report"]["verdict"] == verdict
    assert f"Réplica A y B: {verdict}" in output.err
    if verdict == "different":
        assert "- outputs/tripinfo.xml: cambia" in output.err


def test_compare_passes_the_runs_and_the_tolerance(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = install(monkeypatch, "replicate", (replica(), Path("datos/derivados/replicas/R1")))
    main(["runs", "compare", "--run-a", "A", "--run-b", "B", "--tolerance", "0.001"])
    ((args, options),) = recorder.calls
    assert args == (Path("datos"), "A", "B")
    assert options == {"tolerance": Tolerance(relative=0.001, absolute=0.001)}
    main(["runs", "compare", "--run-a", "A", "--run-b", "B"])
    assert recorder.calls[1][1] == {"tolerance": None}


@pytest.mark.parametrize("tolerance", ["0", "-1", "abc", "inf", "nan"])
def test_a_tolerance_that_is_not_a_positive_number_exits_with_two(tolerance: str) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["runs", "compare", "--run-a", "A", "--run-b", "B", "--tolerance", tolerance])
    assert raised.value.code == 2


@pytest.mark.parametrize("missing", [["--run-a", "A"], ["--run-b", "B"]])
def test_both_runs_are_required(missing: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["runs", "compare", *missing])
    assert raised.value.code == 2


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [(ErrorCode.INPUT_SCHEMA, 2), (ErrorCode.HASH_MISMATCH, 5), (ErrorCode.RUN_EXISTS, 5)],
)
def test_compare_errors_become_json_and_their_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: ErrorCode,
    exit_code: int,
) -> None:
    install(monkeypatch, "replicate", DomainError(code, "no se pudo", "run_b"))
    assert main(["runs", "compare", "--run-a", "A", "--run-b", "B"]) == exit_code
    assert json.loads(capsys.readouterr().out)["code"] == code.value
