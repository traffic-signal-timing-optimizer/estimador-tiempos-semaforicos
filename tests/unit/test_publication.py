"""Publicar una carpeta con candado y apartar las publicaciones caídas (DEV08 F1, D2 a D4)."""

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from process_tools import kill_hard, spawn, wait_until
from semaforo.trazabilidad import fs
from semaforo.trazabilidad.fs import (
    INCOMPLETE_DIR,
    INCOMPLETE_MARK,
    IncompletePublication,
    publication,
    publish_files,
    recover_publications,
    remove_tree,
)
from semaforo.trazabilidad.lock import RunLock

NOW = datetime(2026, 11, 1, 20, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


@pytest.fixture
def parent(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "reportes"
    yield folder
    remove_tree(folder)


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def old(path: Path) -> None:
    moment = time.time() - fs.FRESH_S - 5
    os.utime(path, (moment, moment))


def crashed(parent: Path, name: str, content: str = "a medias") -> Path:
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / "parcial.json").write_text(content, encoding="utf-8")
    return folder


# --- publicar -------------------------------------------------------------------------------


def test_a_publication_leaves_only_the_published_folder(parent: Path) -> None:
    publish_files(parent / "R1", {"a.json": b"{}", "sub/b.json": b"[]"})
    assert names(parent) == ["R1"]  # ni temporal ni candado
    assert (parent / "R1" / "sub" / "b.json").read_bytes() == b"[]"


def test_the_temporary_folder_names_its_destination(
    parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    with publication(parent / "R1") as temporary:
        seen.append(temporary.name)
        assert RunLock.is_held(parent / ".lock-R1")
    assert seen[0].startswith(".tmp-R1-")


def test_a_publication_in_progress_blocks_another_to_the_same_destination(parent: Path) -> None:
    parent.mkdir()
    lock = RunLock.acquire(parent / ".lock-R1")
    assert lock is not None
    try:
        with pytest.raises(FileExistsError):
            publish_files(parent / "R1", {"a.json": b"{}"})
        assert not (parent / "R1").exists()
    finally:
        lock.release()
    publish_files(parent / "R1", {"a.json": b"{}"})  # al soltarse, se puede


def test_a_destination_that_appears_meanwhile_is_not_overwritten(parent: Path) -> None:
    with pytest.raises(FileExistsError), publication(parent / "R1") as temporary:
        (temporary / "a.json").write_text("nuevo", encoding="utf-8")
        (parent / "R1").mkdir()
        (parent / "R1" / "otro.txt").write_text("de otro", encoding="utf-8")
    assert names(parent / "R1") == ["otro.txt"]
    assert names(parent) == ["R1"]  # la temporal se borró y el candado se soltó


def test_an_error_while_writing_publishes_nothing_and_frees_the_lock(parent: Path) -> None:
    with pytest.raises(RuntimeError), publication(parent / "R1"):
        raise RuntimeError("falló al escribir")
    assert not parent.exists() or names(parent) == []
    publish_files(parent / "R1", {"a.json": b"{}"})


# --- publicaciones caídas -------------------------------------------------------------------


def test_a_crashed_publication_is_set_aside_by_the_next_one(parent: Path) -> None:
    crashed(parent, ".tmp-R1-abc123")
    publish_files(parent / "R2", {"a.json": b"{}"})
    assert names(parent) == [INCOMPLETE_DIR, "R2"]
    moved = parent / INCOMPLETE_DIR / "R1-abc123"
    assert (moved / "parcial.json").read_text(encoding="utf-8") == "a medias"
    mark = json.loads((moved / INCOMPLETE_MARK).read_text(encoding="utf-8"))
    assert (mark["target"], mark["source_folder"]) == ("R1", ".tmp-R1-abc123")


def test_recovering_reports_what_it_moved(parent: Path) -> None:
    crashed(parent, ".tmp-R1-abc123")
    (moved,) = recover_publications(parent, clock=clock)
    assert moved == IncompletePublication(
        folder=f"{INCOMPLETE_DIR}/R1-abc123",
        source_folder=".tmp-R1-abc123",
        target="R1",
        detected_at=NOW,
        cause="el programa que publicaba la carpeta terminó sin publicarla",
    )
    assert recover_publications(parent, clock=clock) == []


def test_the_same_destination_can_be_published_after_a_crash(parent: Path) -> None:
    crashed(parent, ".tmp-R1-abc123")
    publish_files(parent / "R1", {"a.json": b"{}"})
    assert names(parent) == [INCOMPLETE_DIR, "R1"]


def test_a_publication_that_is_alive_is_not_touched(parent: Path) -> None:
    crashed(parent, ".tmp-R1-abc123")
    lock = RunLock.acquire(parent / ".lock-R1")
    assert lock is not None
    try:
        assert recover_publications(parent, clock=clock) == []
        assert (parent / ".tmp-R1-abc123").is_dir()
    finally:
        lock.release()


def test_an_old_style_temporary_is_moved_only_when_old(parent: Path) -> None:
    folder = crashed(parent, ".tmp-abcd1234")
    assert recover_publications(parent, clock=clock) == []
    old(folder)
    (moved,) = recover_publications(parent, clock=clock)
    assert (moved.target, moved.folder) == (None, f"{INCOMPLETE_DIR}/abcd1234")


def test_a_run_temporary_is_left_for_the_run_recovery(parent: Path) -> None:
    folder = crashed(parent, ".tmp-corrida1")
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    old(folder)
    assert recover_publications(parent, clock=clock) == []
    assert folder.is_dir()


def test_two_crashes_with_the_same_name_are_both_kept(parent: Path) -> None:
    crashed(parent, ".tmp-R1-abc123", "primera")
    recover_publications(parent, clock=clock)
    crashed(parent, ".tmp-R1-abc123", "segunda")
    recover_publications(parent, clock=clock)
    assert names(parent / INCOMPLETE_DIR) == ["R1-abc123", "R1-abc123-2"]


def test_a_folder_that_cannot_be_moved_is_left_and_the_rest_continue(
    parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stuck = crashed(parent, ".tmp-R1-abc123")
    crashed(parent, ".tmp-R2-def456")
    real = Path.replace

    def replace(self: Path, target: Path) -> Path:
        if self == stuck:
            raise PermissionError("abierta por otro programa")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    moved = recover_publications(parent, clock=clock)
    assert [item.target for item in moved] == ["R2"]
    assert stuck.is_dir()


def test_nothing_happens_in_a_folder_that_does_not_exist(parent: Path) -> None:
    assert recover_publications(parent, clock=clock) == []
    assert not parent.exists()


def test_other_folders_are_left_alone(parent: Path) -> None:
    (parent / "R1").mkdir(parents=True)
    (parent / "notas").mkdir()
    assert recover_publications(parent, clock=clock) == []
    assert names(parent) == ["R1", "notas"]


@pytest.mark.skipif(sys.platform != "win32", reason="las uniones solo existen en Windows")
def test_a_link_with_a_temporary_name_is_not_followed(parent: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "ajena"
    elsewhere.mkdir()
    (elsewhere / "importante.txt").write_text("no tocar", encoding="utf-8")
    old(elsewhere)
    parent.mkdir()
    link = parent / ".tmp-enlace01"
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(elsewhere)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    try:
        assert recover_publications(parent, clock=clock) == []
        assert (elsewhere / "importante.txt").is_file()
    finally:
        link.rmdir()


# --- caída de verdad ------------------------------------------------------------------------

PUBLISHER = """
    import sys, time
    from pathlib import Path
    from semaforo.trazabilidad.fs import publication
    with publication(Path(sys.argv[1])) as temporary:
        (temporary / "parcial.json").write_text("a medias")
        Path(sys.argv[2]).write_text(temporary.name)
        time.sleep(120)
"""


def test_a_publisher_killed_for_real_is_set_aside_only_after_it_dies(
    tmp_path: Path, parent: Path
) -> None:
    ready = tmp_path / "listo.txt"
    publisher = spawn(tmp_path, PUBLISHER, str(parent / "R1"), str(ready))
    try:
        wait_until(lambda: ready.exists() and bool(ready.read_text()), "empezó a publicar")
        temporary = ready.read_text()
        assert recover_publications(parent, clock=clock) == []  # viva
        with pytest.raises(FileExistsError):
            publish_files(parent / "R1", {"a.json": b"{}"})  # el mismo destino está en curso
        kill_hard(publisher)
        found: list[IncompletePublication] = []

        def recovered() -> bool:
            found.extend(recover_publications(parent, clock=clock))
            return bool(found)

        wait_until(recovered, "se apartó la publicación caída")
    finally:
        if publisher.poll() is None:
            kill_hard(publisher)
    (moved,) = found
    assert (moved.source_folder, moved.target) == (temporary, "R1")
    assert not (parent / "R1").exists()
    publish_files(parent / "R1", {"a.json": b"{}"})
    assert names(parent) == [INCOMPLETE_DIR, "R1"]


def test_a_temporary_with_an_empty_destination_counts_as_old_style(parent: Path) -> None:
    folder = crashed(parent, ".tmp--abc123")
    assert recover_publications(parent, clock=clock) == []  # reciente y sin destino: no se toca
    old(folder)
    (moved,) = recover_publications(parent, clock=clock)
    assert moved.target is None


def test_an_existing_destination_is_refused_before_writing_anything(parent: Path) -> None:
    (parent / "R1").mkdir(parents=True)
    written: list[str] = []
    with pytest.raises(FileExistsError), publication(parent / "R1") as temporary:
        written.append(temporary.name)
    assert written == []
    assert names(parent) == ["R1"]
