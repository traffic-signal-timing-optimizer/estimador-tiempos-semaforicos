"""Lectura del archivo del caso (DEV02, F1): CASE-S04, codificación y límites de entrada."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from semaforo.caso.case_validation import MAX_CASE_BYTES, read_case
from semaforo.caso.errors import CasoError
from semaforo.dominio.case import CaseInvalidError
from semaforo.dominio.errors import ErrorCode

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "case.json"
WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="las uniones (junctions) solo existen en Windows"
)


def write(folder: Path, content: bytes | str, name: str = "case.json") -> Path:
    path = folder / name
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def fixture_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def invalid(path: Path) -> CaseInvalidError:
    with pytest.raises(CaseInvalidError) as raised:
        read_case(path)
    return raised.value


def test_the_reference_file_is_read() -> None:
    case = read_case(FIXTURE)
    assert case.case_id == "SYNTHETIC_DEMO"
    assert len(case.slots) == 6


def test_a_utf8_bom_is_accepted(tmp_path: Path) -> None:
    path = write(tmp_path, b"\xef\xbb\xbf" + fixture_text().encode("utf-8"))
    assert read_case(path).case_id == "SYNTHETIC_DEMO"


def test_reading_does_not_change_the_file_or_leave_anything(tmp_path: Path) -> None:
    path = write(tmp_path, fixture_text())
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    read_case(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert [item.name for item in tmp_path.iterdir()] == ["case.json"]


def test_a_missing_file_is_input_schema(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        read_case(tmp_path / "no-existe.json")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "case"
    assert "no existe" in raised.value.message


def test_a_folder_is_not_a_case_file(tmp_path: Path) -> None:
    with pytest.raises(CasoError) as raised:
        read_case(tmp_path)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert "no es un archivo" in raised.value.message


@WINDOWS_ONLY
def test_a_junction_is_not_followed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    write(real, fixture_text())
    link = tmp_path / "enlace"
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(real)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    try:
        with pytest.raises(CasoError) as raised:
            read_case(link)
        assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    finally:
        link.rmdir()


def test_a_symlink_is_not_followed(tmp_path: Path) -> None:
    real = write(tmp_path, fixture_text())
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    with pytest.raises(CasoError) as raised:
        read_case(link)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


def padded(size: int) -> bytes:
    """El caso de ejemplo con espacios al final hasta pesar exactamente ``size`` bytes."""
    content = fixture_text().encode("utf-8")
    return content + b" " * (size - len(content))


def test_a_file_of_exactly_the_maximum_size_is_read(tmp_path: Path) -> None:
    path = write(tmp_path, padded(MAX_CASE_BYTES))
    assert path.stat().st_size == MAX_CASE_BYTES
    assert read_case(path).case_id == "SYNTHETIC_DEMO"


def test_one_byte_over_the_maximum_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, padded(MAX_CASE_BYTES + 1))
    error = invalid(path)
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert [(issue.rule_id, issue.field) for issue in error.issues] == [("CASE-S04", None)]
    assert str(MAX_CASE_BYTES) in error.issues[0].message


def test_only_the_limit_is_read_from_a_huge_file(tmp_path: Path) -> None:
    path = tmp_path / "enorme.json"
    with path.open("wb") as handle:
        handle.seek(50 * 1024 * 1024)
        handle.write(b"x")
    assert invalid(path).issues[0].rule_id == "CASE-S04"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"\xff\xfe\x00", "el archivo no está en UTF-8"),
        (b"", "el archivo no es JSON válido (línea 1, columna 1)"),
        (b"{", "el archivo no es JSON válido"),
        (b'{"a": 1,}', "el archivo no es JSON válido (línea 1, columna 9)"),
        (b"[1, 2", "el archivo no es JSON válido"),
    ],
    ids=["not-utf8", "empty", "unclosed", "trailing-comma", "truncated"],
)
def test_a_file_that_is_not_json_is_rejected_with_the_position(
    tmp_path: Path, content: bytes, message: str
) -> None:
    error = invalid(write(tmp_path, content))
    assert error.issues[0].rule_id == "CASE-S01"
    assert error.issues[0].field is None
    assert error.issues[0].message.startswith(message)


def test_a_repeated_key_is_rejected(tmp_path: Path) -> None:
    text = fixture_text().replace('"tick_s": 1,', '"tick_s": 1, "tick_s": 2,', 1)
    assert text != fixture_text()
    error = invalid(write(tmp_path, text))
    assert "'tick_s'" in error.issues[0].message
    assert "más de una vez" in error.issues[0].message


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_constants_that_are_not_numbers_are_rejected(tmp_path: Path, constant: str) -> None:
    text = fixture_text().replace('"tick_s": 1,', f'"tick_s": {constant},', 1)
    error = invalid(write(tmp_path, text))
    assert constant.lstrip("-") in error.issues[0].message


def test_a_deeply_nested_file_does_not_crash(tmp_path: Path) -> None:
    error = invalid(write(tmp_path, b"[" * 200_000))
    assert error.issues[0].message == "el JSON está demasiado anidado"


def test_a_json_array_is_not_a_case(tmp_path: Path) -> None:
    error = invalid(write(tmp_path, "[]"))
    assert error.issues[0].message == "debe ser un objeto"


def test_the_contract_problems_of_the_content_are_listed(tmp_path: Path) -> None:
    data = json.loads(fixture_text())
    data["case_version"] = "1.0"
    del data["slots"]
    error = invalid(write(tmp_path, json.dumps(data)))
    assert {(i.rule_id, i.field) for i in error.issues} == {
        ("CASE-S03", "case_version"),
        ("CASE-S01", "slots"),
    }
