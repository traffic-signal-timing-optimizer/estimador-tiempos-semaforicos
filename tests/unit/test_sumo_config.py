"""Pruebas de la lectura de referencias a archivos de un .sumocfg."""

from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.sumo_config import FileReference, is_absolute_like, read_config_references

MAX_BYTES = 10_000
CONFIG = """<?xml version="1.0" encoding="UTF-8"?>
<configuration>
    <input>
        <net-file value="a.net.xml"/>
        <route-files value="r1.rou.xml, r2.rou.xml"/>
        <additional-files value="x.add.xml"/>
    </input>
    <time>
        <begin value="0"/>
    </time>
    <output>
        <tripinfo-output value="viajes.xml"/>
        <tripinfo-output.write-unfinished value="true"/>
    </output>
    <gui_only>
        <gui-settings-file value="view.xml"/>
        <delay value="100"/>
    </gui_only>
</configuration>
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "entry.sumocfg"
    path.write_text(text, encoding="utf-8")
    return path


def _paths(references: tuple[FileReference, ...], section: str) -> list[str]:
    return [ref.path for ref in references if ref.section == section]


def test_reads_files_by_section(tmp_path: Path) -> None:
    result = read_config_references(_write(tmp_path, CONFIG), MAX_BYTES)
    assert _paths(result.files, "input") == ["a.net.xml", "r1.rou.xml", "r2.rou.xml", "x.add.xml"]
    assert _paths(result.files, "gui_only") == ["view.xml"]
    assert _paths(result.files, "output") == ["viajes.xml"]


def test_ignores_options_that_are_not_files(tmp_path: Path) -> None:
    result = read_config_references(_write(tmp_path, CONFIG), MAX_BYTES)
    options = {ref.option for ref in result.files}
    assert "delay" not in options
    assert "begin" not in options
    assert "tripinfo-output.write-unfinished" not in options


def test_reports_the_option_name(tmp_path: Path) -> None:
    result = read_config_references(_write(tmp_path, CONFIG), MAX_BYTES)
    first = result.files[0]
    assert (first.section, first.option, first.path) == ("input", "net-file", "a.net.xml")


def test_accepts_the_sumo_configuration_root(tmp_path: Path) -> None:
    text = CONFIG.replace("<configuration>", "<sumoConfiguration>").replace(
        "</configuration>", "</sumoConfiguration>"
    )
    result = read_config_references(_write(tmp_path, text), MAX_BYTES)
    assert _paths(result.files, "input")[0] == "a.net.xml"


def test_finds_absolute_paths_in_any_section(tmp_path: Path) -> None:
    text = CONFIG.replace('value="viajes.xml"', 'value="Q:\\salida\\viajes.xml"').replace(
        'value="a.net.xml"', 'value="/etc/net.xml"'
    )
    result = read_config_references(_write(tmp_path, text), MAX_BYTES)
    found = {(ref.section, ref.option, ref.path) for ref in result.absolute_paths}
    assert found == {
        ("output", "tripinfo-output", "Q:\\salida\\viajes.xml"),
        ("input", "net-file", "/etc/net.xml"),
    }


def test_a_clean_config_has_no_absolute_paths(tmp_path: Path) -> None:
    assert read_config_references(_write(tmp_path, CONFIG), MAX_BYTES).absolute_paths == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("net.xml", False),
        ("sub/net.xml", False),
        ("../net.xml", False),
        ("C:\\x\\net.xml", True),
        ("C:/x/net.xml", True),
        ("C:net.xml", True),
        ("/etc/net.xml", True),
        ("\\\\servidor\\recurso\\net.xml", True),
        ("100", False),
        ("true", False),
    ],
)
def test_is_absolute_like(text: str, expected: bool) -> None:
    assert is_absolute_like(text) is expected


@pytest.mark.parametrize(
    "text",
    [
        "<configuration><input>",
        "",
        "<otra><input/></otra>",
        '<?xml version="1.0"?><!DOCTYPE configuration [<!ENTITY x "y">]>'
        '<configuration><input><net-file value="&x;"/></input></configuration>',
        '<?xml version="1.0"?><!DOCTYPE configuration><configuration/>',
    ],
    ids=["truncated", "empty", "wrong-root", "entity", "doctype"],
)
def test_rejects_invalid_or_dangerous_xml(tmp_path: Path, text: str) -> None:
    with pytest.raises(CasoError) as raised:
        read_config_references(_write(tmp_path, text), MAX_BYTES)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_rejects_a_file_over_the_size_limit(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        read_config_references(_write(tmp_path, CONFIG), 50)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        read_config_references(tmp_path / "absent.sumocfg", MAX_BYTES)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
