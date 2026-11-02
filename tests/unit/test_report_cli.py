"""Los comandos ``report case`` y ``report data`` (DEV09 F4, decisión D12)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from html_checks import assert_safe_page
from quality_tools import DEMO_CASE_TEXT, publish_demo_quality, write_case
from semaforo.app.report_commands import report_case, report_data
from semaforo.cli.main import main
from semaforo.dominio.case import parse_case
from workspace_tools import writable

NOW = datetime(2026, 11, 2, 14, 0, 7, tzinfo=UTC)


class Run:
    """El resultado de una invocación: código de salida, JSON de la salida estándar y mensajes."""

    def __init__(self, code: int, out: str, err: str) -> None:
        self.code = code
        self.out = out
        self.err = err

    @property
    def data(self) -> dict[str, object]:
        loaded: object = json.loads(self.out)
        assert isinstance(loaded, dict)
        return cast(dict[str, object], loaded)


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> Run:
    code = main(list(argv))
    captured = capsys.readouterr()
    return Run(code, captured.out, captured.err)


def case_text(**changes: object) -> str:
    data = json.loads(DEMO_CASE_TEXT)
    data.update(changes)
    return json.dumps(data)


def incoherent_text() -> str:
    data = json.loads(DEMO_CASE_TEXT)
    data["green_groups"][0]["slot_ids"] = ["NO_EXISTE"]
    return json.dumps(data)


def warning_text() -> str:
    data = json.loads(DEMO_CASE_TEXT)
    data["slots"][1]["states"] = data["slots"][0]["states"]
    return json.dumps(data)


def case_args(tmp_path: Path, text: str = DEMO_CASE_TEXT) -> list[str]:
    return [
        "report",
        "case",
        "--case",
        str(write_case(tmp_path / "caso", text)),
        "--workspace",
        str(tmp_path / "datos"),
    ]


def data_args(tmp_path: Path, quality: Path, text: str = DEMO_CASE_TEXT) -> list[str]:
    return [
        "report",
        "data",
        "--case",
        str(write_case(tmp_path / "caso", text)),
        "--quality-report",
        str(quality),
        "--workspace",
        str(tmp_path / "datos"),
    ]


def quality_of(tmp_path: Path) -> Path:
    return publish_demo_quality(tmp_path / "calidad", tmp_path / "trabajo")


def nothing_published(tmp_path: Path) -> bool:
    return not (tmp_path / "datos" / "reportes").exists()


# --- report case ------------------------------------------------------------------------------


def test_the_case_report_is_published_and_standard_output_is_only_the_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *case_args(tmp_path))
    assert result.code == 0
    assert result.out.endswith("\n")
    data = result.data
    assert data["status"] == "published"
    assert data["kind"] == "caso"
    assert data["case_id"] == "SYNTHETIC_DEMO"
    assert data["case_status"] == "valid"
    assert data["exit_code"] == 0
    assert data["schema_version"] == "1.0.0"
    folder = str(data["folder"])
    assert folder.startswith("reportes/informes/caso/SYNTHETIC_DEMO/")
    assert data["index"] == f"{folder}/index.html"
    assert set(data) == {
        "schema_version",
        "status",
        "kind",
        "case_id",
        "case_status",
        "folder",
        "index",
        "exit_code",
    }


def test_the_published_page_exists_and_is_safe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *case_args(tmp_path))
    page = tmp_path / "datos" / str(result.data["index"])
    seen = assert_safe_page(page.read_text(encoding="utf-8"))
    assert "Informe del caso: SYNTHETIC_DEMO" in seen.visible_text


def test_the_json_has_only_relative_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *case_args(tmp_path))
    assert str(tmp_path) not in result.out
    assert "\\" not in str(result.data["folder"])


def test_the_message_for_the_person_gives_the_full_path_and_the_state_in_words(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *case_args(tmp_path))
    page = (tmp_path / "datos" / str(result.data["index"])).resolve()
    assert f"Informe de caso publicado: {page}" in result.err
    assert "Estado del caso SYNTHETIC_DEMO: válido" in result.err


@pytest.mark.parametrize(
    ("text", "status", "words"),
    [
        (incoherent_text(), "invalid", "inválido"),
        (warning_text(), "valid_with_warnings", "válido con avisos"),
    ],
)
def test_a_case_that_is_not_plainly_valid_still_gets_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, status: str, words: str
) -> None:
    result = run(capsys, *case_args(tmp_path, text))
    assert result.code == 0
    assert result.data["case_status"] == status
    assert f"Estado del caso SYNTHETIC_DEMO: {words}" in result.err
    page = tmp_path / "datos" / str(result.data["index"])
    assert_safe_page(page.read_text(encoding="utf-8"))


def test_a_case_without_structure_gets_a_report_for_an_unidentified_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *case_args(tmp_path, "{}"))
    assert result.code == 0
    assert result.data["case_id"] is None
    assert result.data["case_status"] == "invalid"
    assert str(result.data["folder"]).startswith("reportes/informes/caso/sin-identificar/")
    assert "Estado del caso None: inválido" in result.err


def test_a_missing_case_file_exits_2_and_publishes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(
        capsys,
        "report",
        "case",
        "--case",
        str(tmp_path / "no-existe.json"),
        "--workspace",
        str(tmp_path / "datos"),
    )
    assert result.code == 2
    assert result.data["status"] == "error"
    assert result.data["code"] == "INPUT_SCHEMA"
    assert nothing_published(tmp_path)


def test_a_case_file_that_is_a_link_exits_5_and_publishes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    real = write_case(tmp_path / "real")
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    result = run(
        capsys, "report", "case", "--case", str(link), "--workspace", str(tmp_path / "datos")
    )
    assert result.code == 5
    assert result.data["code"] == "PATH_NOT_ALLOWED"
    assert nothing_published(tmp_path)


def test_the_same_report_is_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("semaforo.app.reports.utc_now", lambda: NOW)
    args = case_args(tmp_path)
    assert run(capsys, *args).code == 0
    again = run(capsys, *args)
    assert again.code == 5
    assert again.data["code"] == "RUN_EXISTS"


def test_the_default_workspace_is_datos_in_the_current_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    case = write_case(tmp_path / "caso")
    result = run(capsys, "report", "case", "--case", str(case))
    assert result.code == 0
    assert (tmp_path / "datos" / str(result.data["index"])).is_file()


def test_the_case_option_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["report", "case"])
    assert raised.value.code == 2
    assert "--case" in capsys.readouterr().err


def test_an_unexpected_failure_is_reported_as_an_internal_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("secreto interno")

    monkeypatch.setattr("semaforo.cli.main.report_case", boom)
    result = run(capsys, *case_args(tmp_path))
    assert result.code == 1
    assert result.data["code"] == "INTERNAL"
    assert "secreto interno" not in result.out + result.err
    with pytest.raises(RuntimeError):
        main([*case_args(tmp_path), "--debug"])


# --- report data ------------------------------------------------------------------------------


def test_the_data_report_is_published_from_a_verified_quality_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *data_args(tmp_path, quality_of(tmp_path)))
    assert result.code == 0
    data = result.data
    assert (data["status"], data["kind"], data["case_id"]) == (
        "published",
        "datos",
        "SYNTHETIC_DEMO",
    )
    assert str(data["folder"]).startswith("reportes/informes/datos/SYNTHETIC_DEMO/")
    page = tmp_path / "datos" / str(data["index"])
    seen = assert_safe_page(page.read_text(encoding="utf-8"))
    assert "Informe de los datos: SYNTHETIC_DEMO" in seen.visible_text
    assert "Informe de datos publicado:" in result.err


def test_the_quality_report_option_is_required(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["report", "data", "--case", str(write_case(tmp_path))])
    assert raised.value.code == 2
    assert "--quality-report" in capsys.readouterr().err


def test_an_altered_quality_report_exits_5_and_publishes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    quality = quality_of(tmp_path)
    writable(quality / "calidad.csv").write_bytes(b"cambiado")
    result = run(capsys, *data_args(tmp_path, quality))
    assert result.code == 5
    assert result.data["code"] == "HASH_MISMATCH"
    assert nothing_published(tmp_path)


def test_a_quality_report_of_another_case_exits_2_and_publishes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *data_args(tmp_path, quality_of(tmp_path), case_text(case_id="OTRO")))
    assert result.code == 2
    assert result.data["code"] == "INPUT_SCHEMA"
    assert nothing_published(tmp_path)


def test_a_case_edited_after_the_quality_report_exits_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edited = case_text(description="otra descripción")
    result = run(capsys, *data_args(tmp_path, quality_of(tmp_path), edited))
    assert result.code == 5
    assert result.data["code"] == "HASH_MISMATCH"
    assert nothing_published(tmp_path)


def test_a_case_without_structure_cannot_get_a_data_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *data_args(tmp_path, quality_of(tmp_path), "{}"))
    assert result.code == 2
    assert nothing_published(tmp_path)


def test_a_missing_quality_report_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = run(capsys, *data_args(tmp_path, tmp_path / "no-existe"))
    assert result.code == 2
    assert nothing_published(tmp_path)


def test_a_quality_report_that_is_a_link_exits_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    quality = quality_of(tmp_path)
    link = tmp_path / "enlace"
    try:
        link.symlink_to(quality, target_is_directory=True)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    result = run(capsys, *data_args(tmp_path, link))
    assert result.code == 5
    assert result.data["code"] == "PATH_NOT_ALLOWED"
    assert nothing_published(tmp_path)


def test_the_data_report_is_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("semaforo.app.reports.utc_now", lambda: NOW)
    args = data_args(tmp_path, quality_of(tmp_path))
    assert run(capsys, *args).code == 0
    assert run(capsys, *args).data["code"] == "RUN_EXISTS"


def test_the_help_lists_the_report_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["report", "--help"])
    assert raised.value.code == 0
    text = capsys.readouterr().out
    assert "case" in text
    assert "data" in text


def test_the_data_report_tells_how_the_case_stands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = warning_text()
    quality = publish_demo_quality(
        tmp_path / "calidad", tmp_path / "trabajo", case=parse_case(json.loads(text))
    )
    result = run(capsys, *data_args(tmp_path, quality, text))
    assert result.code == 0
    assert result.data["case_status"] == "valid_with_warnings"
    assert "Estado del caso SYNTHETIC_DEMO: válido con avisos" in result.err


# --- los casos de uso, sin la línea de comandos -----------------------------------------------


def test_the_case_use_case_names_the_report_with_the_moment_it_is_given(tmp_path: Path) -> None:
    case = write_case(tmp_path / "caso")
    result = report_case(tmp_path / "datos", case, NOW)
    assert Path(result.folder).name.startswith("20261102T140007Z_")


def test_the_data_use_case_names_the_report_with_the_moment_it_is_given(tmp_path: Path) -> None:
    case = write_case(tmp_path / "caso")
    result = report_data(tmp_path / "datos", case, quality_of(tmp_path), NOW)
    assert Path(result.folder).name.startswith("20261102T140007Z_")
