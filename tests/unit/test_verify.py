"""Lectura verificada de carpetas publicadas: programas y reportes de calidad (DEV08 F1, D5)."""

import hashlib
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from semaforo.datos.quality_report import QualityManifest, read_quality_report
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.compiler import ProgramManifest, read_program
from semaforo.trazabilidad.fs import publish_files, remove_tree
from semaforo.trazabilidad.verify import MAX_MANIFEST_BYTES, verify_files


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


PROGRAM = b"<additional/>"
SLOTS = b"[]"
PROGRAM_MANIFEST = ProgramManifest(
    created_at="2026-11-01T20:00:00+00:00",
    case_id="CASO_A",
    case_version="1.0.0",
    case_sha256="a" * 64,
    network_sha256=None,
    program_id="derived",
    tls_id="J1",
    files={"programa.tll.xml": digest(PROGRAM), "tramos.json": digest(SLOTS)},
)
DETAIL = b"col;valor\r\n"
SUMMARY = b"{}"
QUALITY_MANIFEST = QualityManifest(
    schema_version="1.0.0",
    created_at="2026-11-01T20:00:00+00:00",
    case_id="CASO_A",
    case_sha256="a" * 64,
    observed_sha256="b" * 64,
    control_sha256="c" * 64,
    max_relative_error=0.1,
    files={"calidad.csv": digest(DETAIL), "resumen.json": digest(SUMMARY)},
)


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "derivados"
    yield folder
    remove_tree(folder)


def program_folder(root: Path) -> Path:
    final = root / "programas" / "P1"
    publish_files(
        final,
        {
            "programa.tll.xml": PROGRAM,
            "tramos.json": SLOTS,
            "manifiesto.json": PROGRAM_MANIFEST.model_dump_json().encode("utf-8"),
        },
    )
    return final


def quality_folder(root: Path) -> Path:
    final = root / "calidad" / "Q1"
    publish_files(
        final,
        {
            "calidad.csv": DETAIL,
            "resumen.json": SUMMARY,
            "manifiesto.json": QUALITY_MANIFEST.model_dump_json().encode("utf-8"),
        },
    )
    return final


def writable(path: Path) -> Path:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    return path


def code_of(action: Callable[[], object]) -> ErrorCode:
    with pytest.raises(DomainError) as raised:
        action()
    return raised.value.code


# --- programas y reportes intactos -----------------------------------------------------------


def test_an_intact_program_is_read_with_its_manifest(root: Path) -> None:
    assert read_program(program_folder(root)) == PROGRAM_MANIFEST


def test_an_intact_quality_report_is_read_with_its_manifest(root: Path) -> None:
    assert read_quality_report(quality_folder(root)) == QUALITY_MANIFEST


# --- alteraciones ---------------------------------------------------------------------------


@pytest.mark.parametrize("reader", [read_program, read_quality_report])
def test_a_changed_file_is_detected(root: Path, reader: Callable[[Path], object]) -> None:
    folder = program_folder(root) if reader is read_program else quality_folder(root)
    victim = sorted(p for p in folder.iterdir() if p.name != "manifiesto.json")[0]
    writable(victim).write_bytes(victim.read_bytes() + b" ")
    assert code_of(lambda: reader(folder)) is ErrorCode.HASH_MISMATCH


def test_an_extra_file_is_detected(root: Path) -> None:
    folder = program_folder(root)
    (folder / "intruso.xml").write_text("<x/>", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        read_program(folder)
    assert raised.value.code is ErrorCode.HASH_MISMATCH
    assert "sobra" in raised.value.message
    assert raised.value.field == "intruso.xml"


def test_a_missing_file_is_detected(root: Path) -> None:
    folder = program_folder(root)
    writable(folder / "tramos.json").unlink()
    with pytest.raises(DomainError) as raised:
        read_program(folder)
    assert (raised.value.code, raised.value.field) == (ErrorCode.HASH_MISMATCH, "tramos.json")
    assert "falta" in raised.value.message


def test_a_rewritten_manifest_that_does_not_match_is_detected(root: Path) -> None:
    folder = program_folder(root)
    changed = PROGRAM_MANIFEST.model_copy(update={"files": {"programa.tll.xml": "0" * 64}})
    writable(folder / "manifiesto.json").write_text(changed.model_dump_json(), encoding="utf-8")
    assert code_of(lambda: read_program(folder)) is ErrorCode.HASH_MISMATCH


PADDED = PROGRAM_MANIFEST.model_dump_json().encode("utf-8") + b" " * MAX_MANIFEST_BYTES


@pytest.mark.parametrize(
    "content",
    [b"{no es json", b"{}", b'{"x": 1}', PADDED],
    ids=["broken", "empty", "other-model", "valid-but-too-big"],
)
def test_a_bad_manifest_is_an_input_error(root: Path, content: bytes) -> None:
    folder = program_folder(root)
    writable(folder / "manifiesto.json").write_bytes(content)
    assert code_of(lambda: read_program(folder)) is ErrorCode.INPUT_SCHEMA


def test_a_missing_manifest_or_folder_is_an_input_error(root: Path) -> None:
    folder = program_folder(root)
    assert code_of(lambda: read_program(root / "no-existe")) is ErrorCode.INPUT_SCHEMA
    writable(folder / "manifiesto.json").unlink()
    assert code_of(lambda: read_program(folder)) is ErrorCode.INPUT_SCHEMA


def test_a_manifest_naming_a_path_outside_the_folder_is_refused(root: Path) -> None:
    folder = program_folder(root)
    escaping = PROGRAM_MANIFEST.model_copy(update={"files": {"../fuera.xml": "0" * 64}})
    writable(folder / "manifiesto.json").write_text(escaping.model_dump_json(), encoding="utf-8")
    assert code_of(lambda: read_program(folder)) is ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.skipif(sys.platform != "win32", reason="las uniones solo existen en Windows")
def test_a_folder_that_is_a_junction_is_refused(root: Path, tmp_path: Path) -> None:
    real = program_folder(root)
    link = tmp_path / "enlace"
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(real)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    try:
        assert code_of(lambda: read_program(link)) is ErrorCode.PATH_NOT_ALLOWED
    finally:
        link.rmdir()


# --- verify_files directo -------------------------------------------------------------------


def test_verify_files_accepts_exactly_the_declared_files(root: Path) -> None:
    folder = root / "x"
    publish_files(folder, {"a.txt": b"a", "m.json": b"{}"})
    verify_files(folder, {"a.txt": digest(b"a")}, manifest="m.json")
    assert json.loads((folder / "m.json").read_text(encoding="utf-8")) == {}
