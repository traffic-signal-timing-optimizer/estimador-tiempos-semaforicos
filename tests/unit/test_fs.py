"""Pruebas de los helpers de sistema de archivos para copias de solo lectura."""

import os
import stat
from pathlib import Path

import pytest

from semaforo.trazabilidad.fs import make_read_only, publish_files, remove_tree


def _is_writable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IWRITE)


def _tree(root: Path) -> Path:
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "sub" / "b.txt").write_text("b", encoding="utf-8")
    return root


def test_make_read_only_protects_every_file(tmp_path: Path) -> None:
    root = _tree(tmp_path / "tree")
    make_read_only(root)
    assert not _is_writable(root / "a.txt")
    assert not _is_writable(root / "sub" / "b.txt")
    assert os.listdir(root)  # las carpetas siguen siendo legibles


def test_remove_tree_deletes_read_only_files(tmp_path: Path) -> None:
    root = _tree(tmp_path / "tree")
    make_read_only(root)
    remove_tree(root)
    assert not root.exists()


def test_remove_tree_ignores_a_missing_path(tmp_path: Path) -> None:
    remove_tree(tmp_path / "does-not-exist")


def test_publish_files_writes_read_only_files_at_once(tmp_path: Path) -> None:
    final = tmp_path / "recepcion" / "R1"
    publish_files(final, {"a.json": b"{}", "sub/b.json": b"[]"})
    assert (final / "a.json").read_bytes() == b"{}"
    assert (final / "sub" / "b.json").read_bytes() == b"[]"
    assert not _is_writable(final / "a.json")
    assert [p.name for p in final.parent.iterdir()] == ["R1"]
    remove_tree(final)


def test_publish_files_never_overwrites(tmp_path: Path) -> None:
    final = tmp_path / "R1"
    final.mkdir()
    (final / "previo.txt").write_text("previo", encoding="utf-8")
    with pytest.raises(FileExistsError):
        publish_files(final, {"a.json": b"{}"})
    assert [p.name for p in final.iterdir()] == ["previo.txt"]
    assert [p.name for p in tmp_path.iterdir()] == ["R1"]


def test_publish_files_rejects_paths_that_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ruta"):
        publish_files(tmp_path / "R1", {"../fuera.json": b"{}"})
    assert list(tmp_path.iterdir()) == []
