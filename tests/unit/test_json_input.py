"""Lectura segura de archivos JSON de entrada (DEV06 F2)."""

from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.caso.json_input import read_json


def write(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "rutas.json"
    path.write_bytes(content)
    return path


def failure(path: Path, max_bytes: int = 1000) -> CasoError:
    with pytest.raises(CasoError) as raised:
        read_json(path, "rutas", max_bytes)
    return raised.value


def test_a_json_object_is_read() -> None:
    assert read_json(Path(__file__).parents[1] / "fixtures" / "scenario.json", "escenario")


def test_the_content_is_returned_as_read(tmp_path: Path) -> None:
    assert read_json(write(tmp_path, b'{"a": [1, 2.5, "x"]}'), "rutas") == {"a": [1, 2.5, "x"]}


def test_a_file_with_bom_is_read(tmp_path: Path) -> None:
    assert read_json(write(tmp_path, b'\xef\xbb\xbf{"a": 1}'), "rutas") == {"a": 1}


def test_a_repeated_key_is_rejected(tmp_path: Path) -> None:
    error = failure(write(tmp_path, b'{"a": 1, "a": 2}'))
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "'a' aparece más de una vez" in error.message
    assert error.field == "rutas.json"


def test_a_repeated_key_inside_a_nested_object_is_rejected(tmp_path: Path) -> None:
    assert "más de una vez" in failure(write(tmp_path, b'{"r": {"x": 1, "x": 1}}')).message


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_constants_that_json_does_not_allow_are_rejected(tmp_path: Path, constant: bytes) -> None:
    error = failure(write(tmp_path, b'{"a": ' + constant + b"}"))
    assert "JSON no admite" in error.message


def test_invalid_json_reports_line_and_column(tmp_path: Path) -> None:
    error = failure(write(tmp_path, b'{"a": 1,\n "b": }'))
    assert "no es JSON válido (línea 2, columna" in error.message
    assert error.message.startswith("rutas: ")


def test_a_file_that_is_not_utf8_is_rejected(tmp_path: Path) -> None:
    assert "UTF-8" in failure(write(tmp_path, '{"a": "ñ"}'.encode("latin-1"))).message


def test_a_file_over_the_limit_is_rejected_without_reading_it_all(tmp_path: Path) -> None:
    error = failure(write(tmp_path, b'{"a": "' + b"x" * 2000 + b'"}'), max_bytes=1000)
    assert "supera el límite de 1000 bytes" in error.message


def test_a_file_exactly_at_the_limit_is_read(tmp_path: Path) -> None:
    content = b'{"a": "' + b"x" * 91 + b'"}'
    assert len(content) == 100
    assert read_json(write(tmp_path, content), "rutas", 100) == {"a": "x" * 91}


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    error = failure(tmp_path / "nada.json")
    assert (error.code, error.field) == (ErrorCode.INPUT_SCHEMA, "nada.json")
    assert "no existe" in error.message


def test_a_folder_is_not_a_file(tmp_path: Path) -> None:
    folder = tmp_path / "carpeta.json"
    folder.mkdir()
    assert "no existe el archivo" in failure(folder).message


def test_deep_nesting_is_reported(tmp_path: Path) -> None:
    error = failure(write(tmp_path, b"[" * 100_000 + b"]" * 100_000), max_bytes=300_000)
    assert "demasiado anidado" in error.message


def test_a_link_is_not_followed(tmp_path: Path) -> None:
    target = write(tmp_path, b'{"a": 1}')
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    assert failure(link).code is ErrorCode.PATH_NOT_ALLOWED


def test_the_message_never_carries_the_folder(tmp_path: Path) -> None:
    error = failure(write(tmp_path, b"{"))
    assert str(tmp_path) not in str(error)
