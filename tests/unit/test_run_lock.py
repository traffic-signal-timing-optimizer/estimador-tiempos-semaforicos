"""El bloqueo del sistema que dice si una corrida sigue viva (DEV07 F3, D8)."""

from pathlib import Path

import pytest

from process_tools import alive, kill_hard, kill_pid, spawn, wait_until
from semaforo.trazabilidad.lock import RunLock


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / ".lock-ejemplo"


def test_acquiring_creates_the_file_and_holds_it(lock_path: Path) -> None:
    lock = RunLock.acquire(lock_path)
    assert lock is not None
    assert lock_path.is_file()
    assert RunLock.is_held(lock_path)
    assert RunLock.acquire(lock_path) is None  # otro intento, aun en el mismo programa
    lock.release()


def test_releasing_frees_it_and_removes_the_file(lock_path: Path) -> None:
    lock = RunLock.acquire(lock_path)
    assert lock is not None
    lock.release()
    assert not lock_path.exists()
    assert not RunLock.is_held(lock_path)
    again = RunLock.acquire(lock_path)
    assert again is not None
    again.release()


def test_releasing_twice_is_safe(lock_path: Path) -> None:
    lock = RunLock.acquire(lock_path)
    assert lock is not None
    lock.release()
    lock.release()
    assert not lock_path.exists()


def test_it_works_as_a_context_manager(lock_path: Path) -> None:
    lock = RunLock.acquire(lock_path)
    assert lock is not None
    with lock:
        assert RunLock.is_held(lock_path)
    assert not lock_path.exists()


def test_a_missing_file_is_not_held(lock_path: Path) -> None:
    assert not RunLock.is_held(lock_path)
    assert not lock_path.exists()  # preguntar no lo crea


def test_a_leftover_file_with_nobody_holding_it_is_taken_over(lock_path: Path) -> None:
    lock_path.write_bytes(b"")  # lo que dejaba antes una caída: un archivo sin dueño
    assert not RunLock.is_held(lock_path)
    lock = RunLock.acquire(lock_path)
    assert lock is not None
    lock.release()


HOLDER = """
    import sys, time
    from pathlib import Path
    from semaforo.trazabilidad.lock import RunLock
    lock = RunLock.acquire(Path(sys.argv[1]))
    assert lock is not None
    Path(sys.argv[2]).write_text("listo")
    time.sleep(120)
"""


def test_a_lock_held_by_another_live_process_is_seen_as_held(
    tmp_path: Path, lock_path: Path
) -> None:
    ready = tmp_path / "listo.txt"
    holder = spawn(tmp_path, HOLDER, str(lock_path), str(ready))
    try:
        wait_until(ready.exists, "el otro programa tomó el bloqueo")
        assert RunLock.is_held(lock_path)
        assert RunLock.acquire(lock_path) is None
    finally:
        kill_hard(holder)


def test_the_system_frees_the_lock_when_its_owner_is_killed(
    tmp_path: Path, lock_path: Path
) -> None:
    ready = tmp_path / "listo.txt"
    holder = spawn(tmp_path, HOLDER, str(lock_path), str(ready))
    wait_until(ready.exists, "el otro programa tomó el bloqueo")
    kill_hard(holder)
    wait_until(lambda: not RunLock.is_held(lock_path), "el sistema soltó el bloqueo")
    assert lock_path.exists() is False  # is_held lo recogió al tomarlo y soltarlo


HOLDER_WITH_CHILD = """
    import subprocess, sys, time
    from pathlib import Path
    from semaforo.trazabilidad.lock import RunLock
    lock = RunLock.acquire(Path(sys.argv[1]))
    assert lock is not None
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    Path(sys.argv[2]).write_text(str(child.pid))
    time.sleep(120)
"""


def test_a_child_process_does_not_keep_the_lock_alive(tmp_path: Path, lock_path: Path) -> None:
    ready = tmp_path / "hijo.txt"
    holder = spawn(tmp_path, HOLDER_WITH_CHILD, str(lock_path), str(ready))
    child = 0
    try:
        wait_until(ready.exists, "el otro programa lanzó a su hijo")
        wait_until(lambda: bool(ready.read_text()), "se escribió el número del hijo")
        child = int(ready.read_text())
        kill_hard(holder)
        assert alive(child)  # el hijo sigue vivo...
        wait_until(lambda: not RunLock.is_held(lock_path), "el bloqueo se soltó igual")
    finally:
        if holder.poll() is None:
            kill_hard(holder)
        if child:
            kill_pid(child)


def test_a_file_that_is_being_deleted_right_now_counts_as_held(
    lock_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(*_: object, **__: object) -> int:
        raise PermissionError("el archivo se está borrando")

    with monkeypatch.context() as patch:
        patch.setattr("semaforo.trazabilidad.lock.os.open", denied)
        assert RunLock.acquire(lock_path) is None
