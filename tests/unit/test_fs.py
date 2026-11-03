"""Pruebas de los helpers de sistema de archivos para copias de solo lectura."""

import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from semaforo.trazabilidad import fs
from semaforo.trazabilidad.fs import (
    RENAME_ATTEMPTS,
    RENAME_PAUSE_S,
    make_read_only,
    publish_files,
    remove_tree,
    replace_patiently,
)


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


class _FlakyReplace:
    """``Path.replace`` que niega el permiso las primeras ``failures`` veces."""

    def __init__(self, failures: int, error: type[OSError] = PermissionError) -> None:
        self.failures = failures
        self.error = error
        self.calls = 0
        self.original = Path.replace

    def __call__(self, source: Path, target: Path) -> Path:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("acceso denegado")
        return self.original(source, target)

    def as_method(self) -> Callable[[Path, Path], Path]:
        """Una función (no un objeto) para que ``Path`` la use como método."""

        def replace(source: Path, target: Path) -> Path:
            return self(source, target)

        return replace


def test_a_rename_denied_for_an_instant_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = _FlakyReplace(3)
    monkeypatch.setattr(Path, "replace", flaky.as_method())
    pauses: list[float] = []
    (tmp_path / "a").mkdir()
    replace_patiently(tmp_path / "a", tmp_path / "b", pause=pauses.append)
    assert (tmp_path / "b").is_dir()
    assert not (tmp_path / "a").exists()
    assert flaky.calls == 4
    assert pauses == [RENAME_PAUSE_S] * 3


def test_a_rename_denied_every_time_gives_up_after_the_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = _FlakyReplace(10_000)
    monkeypatch.setattr(Path, "replace", flaky.as_method())
    pauses: list[float] = []
    (tmp_path / "a").mkdir()
    with pytest.raises(PermissionError):
        replace_patiently(tmp_path / "a", tmp_path / "b", pause=pauses.append)
    assert flaky.calls == RENAME_ATTEMPTS
    assert len(pauses) == RENAME_ATTEMPTS - 1
    assert (tmp_path / "a").is_dir()


def test_a_denied_rename_onto_an_existing_target_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = _FlakyReplace(10_000)
    monkeypatch.setattr(Path, "replace", flaky.as_method())
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with pytest.raises(PermissionError):
        replace_patiently(tmp_path / "a", tmp_path / "b", pause=lambda _: None)
    assert flaky.calls == 1


def test_another_rename_error_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flaky = _FlakyReplace(10_000, FileNotFoundError)
    monkeypatch.setattr(Path, "replace", flaky.as_method())
    with pytest.raises(FileNotFoundError):
        replace_patiently(tmp_path / "a", tmp_path / "b", pause=lambda _: None)
    assert flaky.calls == 1


def test_publishing_survives_a_rename_denied_for_an_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "replace", _FlakyReplace(2).as_method())
    monkeypatch.setattr(fs, "RENAME_PAUSE_S", 0.0)
    publish_files(tmp_path / "final", {"x.txt": b"hola"})
    assert (tmp_path / "final" / "x.txt").read_bytes() == b"hola"
