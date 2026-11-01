"""Corridas interrumpidas: se detectan, se apartan sin borrar y nunca se publican (DEV07 F3, D8)."""

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
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad import interrupted
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.interrupted import (
    INCOMPLETE_DIR,
    INCOMPLETE_MARK,
    InterruptedRun,
    list_interrupted,
    recover_interrupted,
)
from semaforo.trazabilidad.manifest import Error as RunError
from semaforo.trazabilidad.manifest import RunManifest
from semaforo.trazabilidad.store import RunSpec, RunWriter, read_run

CREATED = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
DETECTED = datetime(2026, 11, 1, 11, 30, 0, tzinfo=UTC)
SPEC = RunSpec(
    kind="simulation", case_id="CASO_A", case_version="2.0.0", scenario_id="ESC_1", seed=7
)
RUN_ID = "20261101T100000Z_simulation_caida000"
FAILURE = RunError(code="SIM_FAILED", field=None, message="SUMO terminó con código 1")


def created() -> datetime:
    return CREATED


def detected() -> datetime:
    return DETECTED


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


def crash(runs: Path, run_id: str = RUN_ID, *, partial: str = "datos parciales") -> None:
    """Una corrida que termina con un error sin publicarse: deja su carpeta temporal."""
    with pytest.raises(RuntimeError), RunWriter(runs, SPEC, run_id=run_id, clock=created) as writer:
        writer.output_path("parcial.txt").write_text(partial, encoding="utf-8")
        raise RuntimeError("caída simulada")


def fail(writer: RunWriter) -> RunManifest:
    return writer.publish(status="failed", command=[], environment={}, exit_code=1, error=FAILURE)


def temporary(runs: Path) -> list[Path]:
    return [p for p in runs.iterdir() if p.name.startswith(".tmp-")]


# --- qué se aparta y cómo ------------------------------------------------------------------


def test_nothing_happens_when_the_runs_folder_does_not_exist(runs: Path) -> None:
    assert recover_interrupted(runs, clock=detected) == []
    assert not runs.exists()  # no se crea nada


def test_a_crashed_run_is_moved_with_a_mark_and_nothing_is_lost(runs: Path) -> None:
    crash(runs)
    (source,) = temporary(runs)
    (moved,) = recover_interrupted(runs, clock=detected)
    assert moved == InterruptedRun(
        run_id=RUN_ID,
        folder=f"{INCOMPLETE_DIR}/{RUN_ID}",
        source_folder=source.name,
        created_at=CREATED,
        detected_at=DETECTED,
        provisional_status="running",
        case_id="CASO_A",
        case_version="2.0.0",
        scenario_id="ESC_1",
        cause="el proceso que ejecutaba la corrida terminó sin publicarla",
    )
    folder = runs / INCOMPLETE_DIR / RUN_ID
    assert (folder / "outputs" / "parcial.txt").read_text(encoding="utf-8") == "datos parciales"
    assert (folder / "manifest.json").is_file()
    mark = json.loads((folder / INCOMPLETE_MARK).read_text(encoding="utf-8"))
    assert mark["run_id"] == RUN_ID
    assert mark["detected_at"].startswith("2026-11-01T11:30:00")
    assert mark["source_folder"] == source.name


def test_after_moving_no_temporary_folder_and_no_lock_remain(runs: Path) -> None:
    crash(runs)
    recover_interrupted(runs, clock=detected)
    assert sorted(p.name for p in runs.iterdir()) == [INCOMPLETE_DIR]


def test_an_interrupted_run_is_never_a_published_run(runs: Path) -> None:
    crash(runs)
    recover_interrupted(runs, clock=detected)
    with pytest.raises(DomainError) as raised:
        read_run(runs, RUN_ID)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert not (runs / RUN_ID).exists()


def test_recovering_twice_moves_it_only_once(runs: Path) -> None:
    crash(runs)
    assert len(recover_interrupted(runs, clock=detected)) == 1
    assert recover_interrupted(runs, clock=detected) == []
    assert [item.run_id for item in list_interrupted(runs)] == [RUN_ID]


def test_the_same_run_id_crashing_twice_keeps_both(runs: Path) -> None:
    crash(runs, partial="primera")
    recover_interrupted(runs, clock=detected)
    crash(runs, partial="segunda")
    recover_interrupted(runs, clock=detected)
    folders = sorted(p.name for p in (runs / INCOMPLETE_DIR).iterdir())
    assert folders == [RUN_ID, f"{RUN_ID}-2"]
    texts = {
        name: (runs / INCOMPLETE_DIR / name / "outputs" / "parcial.txt").read_text("utf-8")
        for name in folders
    }
    assert texts == {RUN_ID: "primera", f"{RUN_ID}-2": "segunda"}
    assert [item.folder for item in list_interrupted(runs)] == [
        f"{INCOMPLETE_DIR}/{RUN_ID}",
        f"{INCOMPLETE_DIR}/{RUN_ID}-2",
    ]


def test_several_crashed_runs_are_all_moved(runs: Path) -> None:
    ids = [f"20261101T10000{n}Z_simulation_caida00{n}" for n in range(3)]
    for run_id in ids:
        crash(runs, run_id)
    moved = recover_interrupted(runs, clock=detected)
    assert sorted(item.run_id or "" for item in moved) == ids


def test_published_runs_and_other_folders_are_left_alone(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=created) as writer:
        writer.output_path("a.txt").write_text("a", encoding="utf-8")
        published = fail(writer)
    (runs / "carpeta-ajena").mkdir()
    assert recover_interrupted(runs, clock=detected) == []
    assert read_run(runs, published.run_id) == published
    assert (runs / "carpeta-ajena").is_dir()


def test_a_run_can_be_written_again_with_the_same_id_after_recovery(runs: Path) -> None:
    crash(runs)
    recover_interrupted(runs, clock=detected)
    with RunWriter(runs, SPEC, run_id=RUN_ID, clock=created) as writer:
        writer.output_path("a.txt").write_text("a", encoding="utf-8")
        fail(writer)
    assert read_run(runs, RUN_ID).status == "failed"
    assert (runs / INCOMPLETE_DIR / RUN_ID).is_dir()  # la caída anterior sigue como evidencia


# --- una corrida viva no se toca -----------------------------------------------------------


def test_a_run_that_is_alive_is_not_touched(runs: Path) -> None:
    with RunWriter(runs, SPEC, run_id=RUN_ID, clock=created) as writer:
        assert recover_interrupted(runs, clock=detected) == []
        assert writer.path.is_dir()
        writer.output_path("a.txt").write_text("a", encoding="utf-8")
        fail(writer)
    assert read_run(runs, RUN_ID).status == "failed"
    assert not (runs / INCOMPLETE_DIR).exists()


LIVE_WRITER = """
    import sys, time
    from pathlib import Path
    from semaforo.trazabilidad.store import RunSpec, RunWriter
    spec = RunSpec(kind="simulation", case_id="CASO_A", case_version="2.0.0", scenario_id="ESC_1")
    with RunWriter(Path(sys.argv[1]), spec, run_id=sys.argv[2]) as writer:
        writer.output_path("parcial.txt").write_text("trabajando")
        Path(sys.argv[3]).write_text(str(writer.path))
        time.sleep(120)
"""


def test_a_run_killed_for_real_is_recovered_but_only_after_it_dies(
    tmp_path: Path, runs: Path
) -> None:
    ready = tmp_path / "listo.txt"
    writer = spawn(tmp_path, LIVE_WRITER, str(runs), RUN_ID, str(ready))
    try:
        wait_until(lambda: ready.exists() and bool(ready.read_text()), "la corrida empezó")
        working = Path(ready.read_text())
        assert recover_interrupted(runs, clock=detected) == []  # viva: no se toca
        assert working.is_dir()
        kill_hard(writer)
        found: list[InterruptedRun] = []

        def recovered() -> bool:
            found.extend(recover_interrupted(runs, clock=detected))
            return bool(found)

        wait_until(recovered, "el sistema soltó el bloqueo y la corrida se apartó")
    finally:
        if writer.poll() is None:
            kill_hard(writer)
    (moved,) = found
    assert moved.run_id == RUN_ID
    assert not working.exists()
    folder = runs / INCOMPLETE_DIR / RUN_ID
    assert (folder / "outputs" / "parcial.txt").read_text(encoding="utf-8") == "trabajando"
    with pytest.raises(DomainError):
        read_run(runs, RUN_ID)
    assert sorted(p.name for p in runs.iterdir()) == [INCOMPLETE_DIR]


# --- carpetas que no se pueden identificar --------------------------------------------------


def make_folder(runs: Path, name: str, manifest: str | None, *, age_s: float) -> Path:
    folder = runs / name
    folder.mkdir(parents=True)
    if manifest is not None:
        (folder / "manifest.json").write_text(manifest, encoding="utf-8")
    old = time.time() - age_s
    for path in (folder / "manifest.json", folder):
        if path.exists():
            os.utime(path, (old, old))
    return folder


def test_a_fresh_folder_without_a_readable_manifest_is_left_alone(runs: Path) -> None:
    folder = make_folder(runs, ".tmp-naciendo", None, age_s=1)
    assert recover_interrupted(runs, clock=detected) == []
    assert folder.is_dir()
    folder = make_folder(runs, ".tmp-escribiendo", "{no es json", age_s=1)
    assert recover_interrupted(runs, clock=detected) == []
    assert folder.is_dir()


def test_an_old_folder_without_a_readable_manifest_is_moved_with_unknown_data(
    runs: Path,
) -> None:
    make_folder(runs, ".tmp-vieja001", "{no es json", age_s=interrupted.FRESH_S + 5)
    (moved,) = recover_interrupted(runs, clock=detected)
    assert (moved.run_id, moved.case_id, moved.created_at) == (None, None, None)
    assert moved.folder == f"{INCOMPLETE_DIR}/vieja001"
    assert (runs / INCOMPLETE_DIR / "vieja001" / "manifest.json").is_file()


def test_a_manifest_that_is_too_big_counts_as_unreadable(runs: Path) -> None:
    big = '{"x": "' + "a" * (1024 * 1024) + '"}'
    make_folder(runs, ".tmp-enorme001", big, age_s=interrupted.FRESH_S + 5)
    (moved,) = recover_interrupted(runs, clock=detected)
    assert moved.run_id is None


# --- si algo falla, nada se pierde ---------------------------------------------------------


def test_a_folder_that_cannot_be_moved_stays_and_the_others_are_still_recovered(
    runs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crash(runs, "20261101T100000Z_simulation_atascada0")
    crash(runs, "20261101T100001Z_simulation_libre0000")
    stuck = [p for p in temporary(runs) if "atascada" in (p / "manifest.json").read_text("utf-8")]
    real = Path.replace

    def replace(self: Path, target: Path) -> Path:
        if self == stuck[0]:
            raise PermissionError("otro programa tiene la carpeta abierta")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    moved = recover_interrupted(runs, clock=detected)
    assert [item.run_id for item in moved] == ["20261101T100001Z_simulation_libre0000"]
    assert stuck[0].is_dir()
    assert (stuck[0] / "outputs" / "parcial.txt").is_file()
    monkeypatch.undo()
    (later,) = recover_interrupted(runs, clock=detected)  # la próxima vez se recoge
    assert later.run_id == "20261101T100000Z_simulation_atascada0"


@pytest.mark.skipif(sys.platform != "win32", reason="las uniones solo existen en Windows")
def test_a_link_with_a_temporary_name_is_not_followed(runs: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "ajena"
    elsewhere.mkdir()
    (elsewhere / "importante.txt").write_text("no tocar", encoding="utf-8")
    old = time.time() - interrupted.FRESH_S - 5
    os.utime(elsewhere, (old, old))  # vieja: solo el enlace puede impedir que se la mueva
    runs.mkdir()
    link = runs / ".tmp-enlace001"
    subprocess.run(  # noqa: S603
        ["cmd.exe", "/c", "mklink", "/J", str(link), str(elsewhere)],  # noqa: S607
        check=True,
        capture_output=True,
    )
    try:
        assert recover_interrupted(runs, clock=detected) == []
        assert (elsewhere / "importante.txt").read_text(encoding="utf-8") == "no tocar"
        assert not (runs / INCOMPLETE_DIR).exists()
    finally:
        link.rmdir()


# --- el listado -----------------------------------------------------------------------------


def test_listing_without_any_interrupted_run_is_empty(runs: Path) -> None:
    assert list_interrupted(runs) == []
    runs.mkdir()
    assert list_interrupted(runs) == []


def test_listing_survives_a_damaged_mark(runs: Path) -> None:
    crash(runs)
    recover_interrupted(runs, clock=detected)
    (runs / INCOMPLETE_DIR / RUN_ID / INCOMPLETE_MARK).write_text("{roto", encoding="utf-8")
    (runs / INCOMPLETE_DIR / "suelto.txt").write_text("no es una corrida", encoding="utf-8")
    (listed,) = list_interrupted(runs)
    assert listed.run_id is None
    assert listed.folder == f"{INCOMPLETE_DIR}/{RUN_ID}"


def test_listing_uses_the_real_folder_not_the_one_written_in_the_mark(runs: Path) -> None:
    crash(runs)
    recover_interrupted(runs, clock=detected)
    (runs / INCOMPLETE_DIR / RUN_ID).rename(runs / INCOMPLETE_DIR / "renombrada")
    (listed,) = list_interrupted(runs)
    assert listed.folder == f"{INCOMPLETE_DIR}/renombrada"
    assert listed.run_id == RUN_ID


def test_a_folder_whose_manifest_was_just_rewritten_is_left_alone(runs: Path) -> None:
    folder = make_folder(runs, ".tmp-reescribe01", "{a medias", age_s=interrupted.FRESH_S + 5)
    (folder / "manifest.json").write_text("{a medias otra vez", encoding="utf-8")  # cambió ahora
    old = time.time() - interrupted.FRESH_S - 5
    os.utime(folder, (old, old))  # la carpeta en sí es vieja; el manifiesto no
    assert recover_interrupted(runs, clock=detected) == []
    assert folder.is_dir()


def test_a_valid_manifest_padded_beyond_the_limit_is_not_trusted(runs: Path) -> None:
    crash(runs)
    (folder,) = temporary(runs)
    with (folder / "manifest.json").open("ab") as stream:
        stream.write(b" " * (1024 * 1024 + 1))
    old = time.time() - interrupted.FRESH_S - 5
    for path in (folder / "manifest.json", folder):
        os.utime(path, (old, old))
    (moved,) = recover_interrupted(runs, clock=detected)
    assert moved.run_id is None  # el manifiesto era demasiado grande para leerlo
