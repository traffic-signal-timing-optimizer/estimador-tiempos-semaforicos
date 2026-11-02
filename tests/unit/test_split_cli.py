"""Los comandos ``splits create`` y ``splits validate`` (DEV12 F3, decisión D11)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from scenario_tools import publish_set
from semaforo.app import split_commands
from semaforo.cli.main import build_parser, main
from workspace_tools import tamper

NOW = datetime(2026, 11, 2, 15, 30, 0, tzinfo=UTC)
SEED = "7"


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


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(split_commands, "utc_now", lambda: NOW)


def prepared(tmp_path: Path, families: int = 5) -> tuple[Path, Path]:
    workspace = tmp_path / "datos"
    return workspace, publish_set(workspace, families).folder


def create_args(workspace: Path, folder: Path, seed: str = SEED) -> list[str]:
    return [
        "splits",
        "create",
        "--scenarios",
        str(folder),
        "--seed",
        seed,
        "--workspace",
        str(workspace),
    ]


# --- create -----------------------------------------------------------------------------------


def test_the_split_is_published_and_standard_output_is_only_the_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path)
    result = run(capsys, *create_args(workspace, folder))
    assert result.code == 0
    assert result.out.endswith("\n")
    data = result.data
    assert (data["status"], data["exit_code"], data["case_id"]) == (
        "published",
        0,
        "SYNTHETIC_DEMO",
    )
    assert data["groups"] == {"train": 3, "validation": 1, "test": 1}
    assert str(data["folder"]).startswith("derivados/particiones/SYNTHETIC_DEMO/")
    assert (workspace / str(data["manifest"])).is_file()


def test_the_message_for_the_person_gives_the_path_the_counts_and_the_provisional_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path)
    result = run(capsys, *create_args(workspace, folder))
    where = (workspace / str(result.data["folder"])).resolve()
    assert f"Partición publicada: {where}" in result.err
    assert (
        "Grupos: train 3, validation 1, test 1; escenarios: train 12, validation 4, test 4"
        in result.err
    )
    assert "proporciones provisionales: DEC07 pendiente" in result.err


def test_a_policy_file_removes_the_provisional_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path)
    policy = tmp_path / "politica.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "policy_id": "mi_politica",
                "proportions": {"train": 0.5, "validation": 0.25, "test": 0.25},
            }
        ),
        encoding="utf-8",
    )
    result = run(capsys, *create_args(workspace, folder), "--policy", str(policy))
    assert result.code == 0
    assert result.data["provisional"] is False
    assert "DEC07" not in result.err


def test_standard_output_has_no_local_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path)
    result = run(capsys, *create_args(workspace, folder))
    assert str(tmp_path) not in result.out
    assert "\\" not in result.out


def test_the_default_workspace_is_datos() -> None:
    parsed = build_parser().parse_args(["splits", "create", "--scenarios", "x", "--seed", "1"])
    assert parsed.workspace == Path("datos")
    assert parsed.policy is None


@pytest.mark.parametrize("seed", ["-1", "uno", "1.5", "", "9223372036854775808"])
def test_a_bad_seed_is_a_syntax_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seed: str
) -> None:
    workspace, folder = prepared(tmp_path)
    with pytest.raises(SystemExit) as raised:
        main(create_args(workspace, folder, seed))
    assert raised.value.code == 2
    assert "--seed" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["--scenarios", "--seed"])
def test_a_required_argument_is_needed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    workspace, folder = prepared(tmp_path)
    arguments = create_args(workspace, folder)
    position = arguments.index(missing)
    del arguments[position : position + 2]
    with pytest.raises(SystemExit) as raised:
        main(arguments)
    assert raised.value.code == 2
    assert missing in capsys.readouterr().err


def test_two_families_exit_2_and_publish_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path, families=2)
    result = run(capsys, *create_args(workspace, folder))
    assert result.code == 2
    assert result.data["code"] == "INPUT_SCHEMA"
    assert "SPLIT-C04" in str(result.data["message"])
    assert "- SPLIT-C04 scenarios: hacen falta al menos 3 grupos" in result.err
    assert not (workspace / "derivados" / "particiones").exists()


def test_an_invalid_policy_exits_2_and_lists_the_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path)
    policy = tmp_path / "politica.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "policy_id": "p",
                "proportions": {"train": 0.5, "validation": 0.2, "test": 0.2},
            }
        ),
        encoding="utf-8",
    )
    result = run(capsys, *create_args(workspace, folder), "--policy", str(policy))
    assert result.code == 2
    assert "- SPLIT-P01 proportions: las proporciones suman 0.9 y deben sumar 1" in result.err


def test_a_missing_set_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = run(capsys, *create_args(tmp_path / "datos", tmp_path / "no-existe"))
    assert result.code == 2
    assert result.data["code"] == "INPUT_SCHEMA"


def test_an_altered_set_exits_5(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, folder = prepared(tmp_path)
    tamper(folder / "spec.json")
    result = run(capsys, *create_args(workspace, folder))
    assert result.code == 5
    assert result.data["code"] == "HASH_MISMATCH"


def test_the_same_set_cannot_be_split_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path)
    assert run(capsys, *create_args(workspace, folder)).code == 0
    result = run(capsys, *create_args(workspace, folder, "8"))
    assert result.code == 5
    assert result.data["code"] == "RUN_EXISTS"
    assert "la prueba se reserva una sola vez" in result.err


def test_the_json_error_keeps_the_usual_shape(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *create_args(tmp_path / "datos", tmp_path / "no-existe"))
    assert set(result.data) == {"status", "code", "field", "message"}


# --- validate ---------------------------------------------------------------------------------


def validate_args(split: Path, folder: Path) -> list[str]:
    return ["splits", "validate", "--split", str(split), "--scenarios", str(folder)]


def test_a_published_split_validates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, folder = prepared(tmp_path)
    created = run(capsys, *create_args(workspace, folder)).data
    result = run(capsys, *validate_args(workspace / str(created["folder"]), folder))
    assert result.code == 0
    assert result.data["status"] == "valid"
    assert result.data["split_id"] == created["split_id"]
    assert f"La partición {created['split_id']} es válida" in result.err


def test_a_split_of_another_set_exits_2_with_every_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, folder = prepared(tmp_path)
    created = run(capsys, *create_args(workspace, folder)).data
    other = publish_set(workspace, 5, seed=99).folder
    result = run(capsys, *validate_args(workspace / str(created["folder"]), other))
    assert result.code == 2
    assert result.data["code"] == "INPUT_SCHEMA"
    assert "- SPLIT-C01 scenario_set_content_id:" in result.err


def test_an_altered_split_exits_5(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, folder = prepared(tmp_path)
    created = run(capsys, *create_args(workspace, folder)).data
    tamper(workspace / str(created["folder"]) / "split.json")
    result = run(capsys, *validate_args(workspace / str(created["folder"]), folder))
    assert result.code == 5
    assert result.data["code"] == "HASH_MISMATCH"


def test_validate_needs_both_folders(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["splits", "validate", "--split", "x"])
    assert raised.value.code == 2
    assert "--scenarios" in capsys.readouterr().err
