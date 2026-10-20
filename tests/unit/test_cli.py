"""Pruebas de la CLI sin ejecutar SUMO: traducción de errores a JSON y códigos de salida."""

import json

import pytest

from semaforo.cli.main import main
from semaforo.dominio.errors import DomainError, ErrorCode

ARGUMENTS = ["case", "receive", "--source", "x", "--config", "c.sumocfg", "--case-id", "C"]


def fail_with(error: BaseException) -> object:
    def fake(*_args: object, **_kwargs: object) -> None:
        raise error

    return fake


def test_a_domain_error_becomes_a_json_report_and_its_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    error = DomainError(ErrorCode.HASH_MISMATCH, "la copia existente fue modificada", "net.xml")
    monkeypatch.setattr("semaforo.cli.main.receive_case", fail_with(error))
    assert main(ARGUMENTS) == 5
    output = capsys.readouterr()
    assert json.loads(output.out) == {
        "status": "error",
        "code": "HASH_MISMATCH",
        "field": "net.xml",
        "message": "la copia existente fue modificada",
    }
    assert "HASH_MISMATCH" in output.err


def test_an_unexpected_error_is_internal_and_hides_the_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("semaforo.cli.main.receive_case", fail_with(RuntimeError("C:\\secreto")))
    assert main(ARGUMENTS) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["code"] == "INTERNAL"
    assert "secreto" not in output.out + output.err


def test_debug_shows_the_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("semaforo.cli.main.receive_case", fail_with(RuntimeError("detalle")))
    with pytest.raises(RuntimeError, match="detalle"):
        main([*ARGUMENTS, "--debug"])


def test_a_syntax_error_exits_with_two() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["case", "receive", "--source", "x"])
    assert raised.value.code == 2
