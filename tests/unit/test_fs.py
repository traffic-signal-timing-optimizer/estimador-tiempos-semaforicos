"""Pruebas de los helpers de sistema de archivos para copias de solo lectura."""

import os
import stat
from pathlib import Path

from semaforo.trazabilidad.fs import make_read_only, remove_tree


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
