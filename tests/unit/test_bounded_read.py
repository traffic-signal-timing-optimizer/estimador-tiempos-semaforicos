"""Lectura con tope sin reservar el tope en memoria (DEV07 F0, decisión D17).

Antes, ``handle.read(tope + 1)`` reservaba de una vez memoria para todo el tope: leer un archivo
de 0,8 MB con el tope de 512 MiB ocupaba 512 MB. Estas pruebas miden la memoria con
``tracemalloc`` para que el defecto no vuelva.
"""

import ast
import gzip
import io
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pytest

from semaforo.caso.errors import CasoError
from semaforo.caso.json_input import read_json, read_text_file
from semaforo.caso.xml_input import parse_root, read_bounded
from semaforo.trazabilidad import fs
from semaforo.trazabilidad.fs import READ_CHUNK_BYTES, read_at_most

BIG_LIMIT = 256 * 1024 * 1024
# Lo que puede ocupar leer un archivo de unos KB: las partes, el resultado y lo propio de Python.
SMALL_PEAK = 8 * 1024 * 1024


def peak_of(action: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        action()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


# --- read_at_most ---------------------------------------------------------------------------


def test_a_short_stream_is_read_whole() -> None:
    assert read_at_most(io.BytesIO(b"abc"), 10) == b"abc"


def test_the_reading_stops_at_the_limit() -> None:
    assert read_at_most(io.BytesIO(b"abcdef"), 4) == b"abcd"


def test_a_limit_of_zero_reads_nothing() -> None:
    assert read_at_most(io.BytesIO(b"abc"), 0) == b""


def test_an_empty_stream_gives_nothing() -> None:
    assert read_at_most(io.BytesIO(b""), 10) == b""


def test_a_stream_longer_than_one_part_is_read_whole() -> None:
    data = bytes(range(256)) * (READ_CHUNK_BYTES // 256 * 2 + 3)
    assert read_at_most(io.BytesIO(data), len(data) + 1) == data
    assert read_at_most(io.BytesIO(data), READ_CHUNK_BYTES + 5) == data[: READ_CHUNK_BYTES + 5]


def test_each_read_asks_for_one_part_at_most(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fs, "READ_CHUNK_BYTES", 4)
    sizes: list[int] = []

    class Spy(io.BytesIO):
        def read(self, size: int | None = -1, /) -> bytes:
            sizes.append(-1 if size is None else size)
            return super().read(size)

    assert read_at_most(Spy(b"abcdefghij"), 9) == b"abcdefghi"
    assert sizes == [4, 4, 1]


def test_a_gzip_stream_is_read_by_parts() -> None:
    data = b"x" * 5000
    with gzip.GzipFile(fileobj=io.BytesIO(gzip.compress(data))) as stream:
        assert read_at_most(stream, 100_000) == data


def test_a_big_limit_does_not_reserve_memory() -> None:
    assert peak_of(lambda: read_at_most(io.BytesIO(b"a" * 10_000), BIG_LIMIT)) < SMALL_PEAK


# --- las lecturas que lo usan ---------------------------------------------------------------


def small_xml(tmp_path: Path, *, compressed: bool = False) -> Path:
    text = "<tripinfos>" + '<tripinfo id="v" depart="1" arrival="2"/>' * 200 + "</tripinfos>"
    path = tmp_path / ("t.xml.gz" if compressed else "t.xml")
    data = text.encode("utf-8")
    path.write_bytes(gzip.compress(data) if compressed else data)
    return path


@pytest.mark.parametrize("compressed", [False, True])
def test_read_bounded_uses_the_memory_of_the_file(tmp_path: Path, compressed: bool) -> None:
    path = small_xml(tmp_path, compressed=compressed)
    assert peak_of(lambda: read_bounded(path, BIG_LIMIT)) < SMALL_PEAK


def test_parse_root_uses_the_memory_of_the_file(tmp_path: Path) -> None:
    path = small_xml(tmp_path)
    roots = frozenset({"tripinfos"})
    assert peak_of(lambda: parse_root(path, BIG_LIMIT, roots, "tripinfo")) < SMALL_PEAK


def test_read_text_file_uses_the_memory_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_text("a;b\n" * 2000, encoding="utf-8")
    assert peak_of(lambda: read_text_file(path, "planilla", BIG_LIMIT)) < SMALL_PEAK


def test_read_json_uses_the_memory_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / "a.json"
    path.write_text('{"a": [' + ", ".join(["1"] * 2000) + "]}", encoding="utf-8")
    assert peak_of(lambda: read_json(path, "datos", BIG_LIMIT)) < SMALL_PEAK


@pytest.mark.parametrize("compressed", [False, True])
def test_the_limit_is_still_enforced(tmp_path: Path, compressed: bool) -> None:
    path = small_xml(tmp_path, compressed=compressed)
    size = len(read_bounded(path, BIG_LIMIT))
    assert len(read_bounded(path, size)) == size
    with pytest.raises(CasoError, match="supera el límite"):
        read_bounded(path, size - 1)


def test_the_text_limit_is_still_enforced(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_bytes(b"x" * 100)
    assert read_text_file(path, "planilla", 100) == "x" * 100
    with pytest.raises(CasoError, match="supera el límite"):
        read_text_file(path, "planilla", 99)


# --- ninguna lectura del código reserva el tope ---------------------------------------------

SOURCE = Path(__file__).resolve().parents[2] / "src" / "semaforo"


def reads_with_a_limit(path: Path) -> list[int]:
    """Líneas con ``algo.read(<tope> + 1)``: la forma que reserva el tope entero."""
    found: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "read"
            and node.args
            and isinstance(limit := node.args[0], ast.BinOp)
            and isinstance(limit.op, ast.Add)
            and isinstance(limit.right, ast.Constant)
            and limit.right.value == 1
        ):
            found.append(node.lineno)
    return found


def test_no_read_in_the_code_asks_for_the_whole_limit() -> None:
    offenders = {
        str(path.relative_to(SOURCE)): lines
        for path in sorted(SOURCE.rglob("*.py"))
        if (lines := reads_with_a_limit(path))
    }
    assert offenders == {}


def test_the_code_check_finds_the_old_form(tmp_path: Path) -> None:
    path = tmp_path / "viejo.py"
    path.write_text("def f(h, n):\n    return h.read(n + 1)\n", encoding="utf-8")
    assert reads_with_a_limit(path) == [2]
