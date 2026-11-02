"""El comando ``scenarios generate`` (DEV11 F4, decisión D12): argumentos, salida y códigos."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from scenario_tools import SEED, spec_data, write_inputs
from semaforo.app import scenario_commands
from semaforo.cli.main import build_parser, main

NOW = datetime(2026, 11, 2, 14, 0, 7, tzinfo=UTC)


class Run:
    """El resultado de una invocación: código de salida, JSON de la salida estándar y mensajes."""

    def __init__(self, code: int, out: str, err: str) -> None:
        self.code = code
        self.out = out
        self.err = err

    @property
    def data(self) -> dict[str, Any]:
        loaded: object = json.loads(self.out)
        assert isinstance(loaded, dict)
        return cast(dict[str, Any], loaded)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> Run:
    code = main(list(argv))
    captured = capsys.readouterr()
    return Run(code, captured.out, captured.err)


def args(tmp_path: Path, spec: dict[str, Any] | None = None, seed: str = str(SEED)) -> list[str]:
    case, spec_path = write_inputs(tmp_path / "entradas", spec)
    return [
        "scenarios",
        "generate",
        "--case",
        str(case),
        "--spec",
        str(spec_path),
        "--seed",
        seed,
        "--workspace",
        str(tmp_path / "datos"),
    ]


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scenario_commands, "utc_now", lambda: NOW)


def nothing_published(tmp_path: Path) -> bool:
    return not (tmp_path / "datos").exists()


def test_the_set_is_published_and_standard_output_is_only_the_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *args(tmp_path))
    assert result.code == 0
    assert result.out.endswith("\n")
    data = result.data
    assert data["status"] == "published"
    assert data["exit_code"] == 0
    assert (data["case_id"], data["spec_id"], data["seed"]) == ("SYNTHETIC_DEMO", "SPEC_DEMO", SEED)
    assert (data["families"], data["scenarios"]) == (2, 10)
    assert str(data["folder"]).startswith("derivados/escenarios/SYNTHETIC_DEMO/20261102T140007Z_")
    assert (tmp_path / "datos" / str(data["manifest"])).is_file()


def test_the_message_for_the_person_gives_the_full_path_and_the_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *args(tmp_path))
    folder = (tmp_path / "datos" / str(result.data["folder"])).resolve()
    assert f"Conjunto de escenarios publicado: {folder}" in result.err
    assert (
        f"10 escenarios en 2 familias; {result.data['vehicles']} vehículos en total" in result.err
    )


def test_standard_output_has_no_local_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *args(tmp_path))
    assert str(tmp_path) not in result.out
    assert "\\" not in result.out


def test_the_debug_flag_is_accepted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, *args(tmp_path), "--debug").code == 0


def test_the_default_workspace_is_datos() -> None:
    parsed = build_parser().parse_args(
        ["scenarios", "generate", "--case", "c", "--spec", "s", "--seed", "1"]
    )
    assert parsed.workspace == Path("datos")


@pytest.mark.parametrize("seed", ["-1", "uno", "1.5", "", "9223372036854775808"])
def test_a_bad_seed_is_a_syntax_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seed: str
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(args(tmp_path, seed=seed))
    assert raised.value.code == 2
    assert "--seed" in capsys.readouterr().err
    assert nothing_published(tmp_path)


def test_the_seed_limits_are_accepted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, *args(tmp_path, seed="0")).code == 0
    other = tmp_path / "otro"
    other.mkdir()
    assert run(capsys, *args(other, seed="9223372036854775807")).code == 0


@pytest.mark.parametrize("missing", ["--case", "--spec", "--seed"])
def test_a_required_argument_is_needed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    arguments = args(tmp_path)
    position = arguments.index(missing)
    del arguments[position : position + 2]
    with pytest.raises(SystemExit) as raised:
        main(arguments)
    assert raised.value.code == 2
    assert missing in capsys.readouterr().err


def test_an_invalid_range_exits_2_and_lists_every_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 600, "max": 400}
    data["families"][1]["demand"][0]["flow_vph"] = {"min": 100, "max": 1300}
    result = run(capsys, *args(tmp_path, data))
    assert result.code == 2
    assert result.data["status"] == "error"
    assert result.data["code"] == "INPUT_SCHEMA"
    assert "SPEC-C03" in str(result.data["message"])
    assert "(y 1 más)" in str(result.data["message"])
    assert "Error INPUT_SCHEMA" in result.err
    assert (
        "- SPEC-C03 families[0].demand[0].flow_vph: el mínimo 600 es mayor que el máximo 400"
        in result.err
    )
    assert "- SPEC-C03 families[1].demand[0].flow_vph: el rango de 100 a 1300 veh/h" in result.err
    assert nothing_published(tmp_path)


def test_a_missing_case_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    arguments = args(tmp_path)
    arguments[arguments.index("--case") + 1] = str(tmp_path / "no-existe.json")
    result = run(capsys, *arguments)
    assert result.code == 2
    assert result.data["code"] == "INPUT_SCHEMA"
    assert nothing_published(tmp_path)


def test_the_same_set_on_the_same_second_exits_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(capsys, *args(tmp_path)).code == 0
    result = run(capsys, *args(tmp_path))
    assert result.code == 5
    assert result.data["code"] == "RUN_EXISTS"
    assert "ya existe ese conjunto de escenarios" in result.err


def test_the_json_error_keeps_the_usual_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = spec_data()
    data["case_id"] = "OTRO"
    result = run(capsys, *args(tmp_path, data))
    assert set(result.data) == {"status", "code", "field", "message"}
    assert result.data["field"] == "case_id"
