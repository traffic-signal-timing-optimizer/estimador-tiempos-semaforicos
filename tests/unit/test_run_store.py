"""Pruebas de la carpeta de ejecución: escritura temporal, publicación atómica y lectura."""

import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.manifest import Error as RunError
from semaforo.trazabilidad.manifest import RunManifest, TerminalStatus
from semaforo.trazabilidad.store import RunSpec, RunWriter, new_run_id, read_run

NOW = datetime(2026, 10, 20, 15, 0, 0, tzinfo=UTC)
SPEC = RunSpec(kind="simulation", case_id="SYNTHETIC_DEMO", case_version="1.0.0", seed=301)
RUN_ID = "20261020T150000Z_simulation_fixed000"
FAILURE = RunError(code="SIM_FAILED", field=None, message="SUMO terminó con código 1")


def clock() -> datetime:
    return NOW


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    """Carpeta de ejecuciones; al terminar se borra aunque tenga archivos de solo lectura."""
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "origen" / "demo.sumocfg"
    path.parent.mkdir()
    path.write_text("<configuration/>", encoding="utf-8")
    return path


def publish_succeeded(writer: RunWriter) -> RunManifest:
    writer.output_path("tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")
    return writer.publish(
        status="succeeded", command=["sumo"], environment={"sumo": "1.27.1"}, exit_code=0
    )


def files_of(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def make_writable(folder: Path) -> None:
    for path in folder.rglob("*"):
        if path.is_file():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def test_a_succeeded_run_is_published_with_its_hashes(runs: Path, source: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        artifact = writer.add_input(source, "demo.sumocfg")
        manifest = publish_succeeded(writer)
    final = runs / manifest.run_id
    assert files_of(final) == {"manifest.json", "inputs/demo.sumocfg", "outputs/tripinfo.xml"}
    assert (artifact.artifact_id, artifact.path) == ("inputs/demo.sumocfg", "inputs/demo.sumocfg")
    for item in [*manifest.inputs, *manifest.outputs]:
        assert sha256_file(final / item.path) == item.sha256
    assert (manifest.status, manifest.exit_code, manifest.created_at) == ("succeeded", 0, NOW)
    assert (manifest.kind, manifest.case_id, manifest.seed) == ("simulation", "SYNTHETIC_DEMO", 301)
    assert read_run(runs, manifest.run_id) == manifest
    stored = RunManifest.model_validate_json((final / "manifest.json").read_text(encoding="utf-8"))
    assert stored == manifest


def test_published_files_are_read_only(runs: Path, source: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        writer.add_input(source, "demo.sumocfg")
        manifest = publish_succeeded(writer)
    for path in (runs / manifest.run_id).rglob("*"):
        if path.is_file():
            assert not path.stat().st_mode & stat.S_IWRITE


def test_no_temporary_folder_or_lock_is_left_behind(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        manifest = publish_succeeded(writer)
    assert [p.name for p in runs.iterdir()] == [manifest.run_id]


def test_run_ids_are_sortable_and_unique() -> None:
    first, second = new_run_id("simulation", NOW), new_run_id("simulation", NOW)
    assert first.startswith("20261020T150000Z_simulation_")
    assert first != second


def test_nothing_is_visible_until_published(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        assert not (runs / writer.run_id).exists()
        assert len(writer.path.name) <= len(".tmp-") + 8  # corta: SUMO falla con rutas largas
        provisional = (writer.path / "manifest.json").read_text(encoding="utf-8")
        assert RunManifest.model_validate_json(provisional).status == "running"
        publish_succeeded(writer)
    assert (runs / writer.run_id).is_dir()


def test_a_crash_leaves_an_incomplete_folder_never_a_published_run(runs: Path) -> None:
    def crash() -> None:
        with RunWriter(runs, SPEC, run_id=RUN_ID, clock=clock) as writer:
            writer.output_path("tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")
            raise RuntimeError("caída simulada")

    with pytest.raises(RuntimeError):
        crash()
    assert not (runs / RUN_ID).exists()
    (temporary,) = [p for p in runs.iterdir() if p.name.startswith(".tmp-")]
    provisional = (temporary / "manifest.json").read_text(encoding="utf-8")
    assert RunManifest.model_validate_json(provisional).status == "running"
    with RunWriter(runs, SPEC, run_id=RUN_ID, clock=clock) as writer:  # el lock se liberó
        publish_succeeded(writer)


def test_a_failed_run_is_published_with_its_error(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        manifest = writer.publish(
            status="failed", command=["sumo"], environment={}, exit_code=1, error=FAILURE
        )
    assert read_run(runs, manifest.run_id).error == FAILURE


def test_a_success_without_outputs_is_refused_and_not_published(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        with pytest.raises(DomainError) as raised:
            writer.publish(status="succeeded", command=[], environment={}, exit_code=0)
        assert raised.value.code is ErrorCode.OUTPUT_INVALID
        assert not (runs / writer.run_id).exists()
        writer.publish(status="failed", command=[], environment={}, exit_code=0, error=FAILURE)
    assert read_run(runs, writer.run_id).status == "failed"


def test_two_writers_cannot_target_the_same_run(runs: Path) -> None:
    with RunWriter(runs, SPEC, run_id=RUN_ID, clock=clock):
        with pytest.raises(DomainError) as raised:
            RunWriter(runs, SPEC, run_id=RUN_ID, clock=clock)
        assert raised.value.code is ErrorCode.RUN_EXISTS


def test_a_published_run_is_never_overwritten(runs: Path) -> None:
    with RunWriter(runs, SPEC, run_id=RUN_ID, clock=clock) as writer:
        first = publish_succeeded(writer)
    with pytest.raises(DomainError) as raised:
        RunWriter(runs, SPEC, run_id=RUN_ID, clock=clock)
    assert raised.value.code is ErrorCode.RUN_EXISTS
    assert read_run(runs, RUN_ID) == first


def test_publishing_twice_is_refused(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        publish_succeeded(writer)
        with pytest.raises(ValueError, match="publicó"):
            publish_succeeded(writer)


@pytest.mark.parametrize("relative", ["../x.xml", "C:/x.xml", "/x.xml", "a\\b.xml", "", "a//b.xml"])
def test_unsafe_relative_paths_are_rejected(runs: Path, source: Path, relative: str) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        for action in (
            lambda: writer.add_input(source, relative),
            lambda: writer.output_path(relative),
        ):
            with pytest.raises(DomainError) as raised:
                action()
            assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


@pytest.mark.parametrize("run_id", ["../x", "a/b", "", ".hidden"])
def test_unsafe_run_ids_are_rejected(runs: Path, run_id: str) -> None:
    with pytest.raises(DomainError) as raised:
        RunWriter(runs, SPEC, run_id=run_id, clock=clock)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    with pytest.raises(DomainError) as raised:
        read_run(runs, run_id)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


def test_an_unregistered_input_is_refused(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        (writer.path / "inputs" / "intruso.xml").write_text("<x/>", encoding="utf-8")
        with pytest.raises(DomainError) as raised:
            publish_succeeded(writer)
        assert raised.value.code is ErrorCode.OUTPUT_INVALID


def test_an_input_modified_before_publishing_is_detected(runs: Path, source: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        writer.add_input(source, "demo.sumocfg")
        (writer.path / "inputs" / "demo.sumocfg").write_text("<cambiado/>", encoding="utf-8")
        with pytest.raises(DomainError) as raised:
            publish_succeeded(writer)
        assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_stray_file_outside_inputs_and_outputs_is_refused(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        (writer.path / "notas.txt").write_text("suelto", encoding="utf-8")
        with pytest.raises(DomainError) as raised:
            publish_succeeded(writer)
        assert raised.value.code is ErrorCode.OUTPUT_INVALID


def test_a_source_changed_while_copying_is_detected(
    runs: Path, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = shutil.copyfile

    def copy_then_change(origin: Path, destination: Path) -> None:
        original(origin, destination)
        origin.write_text("<cambiado/>", encoding="utf-8")

    with RunWriter(runs, SPEC, clock=clock) as writer:
        monkeypatch.setattr("semaforo.trazabilidad.store.shutil.copyfile", copy_then_change)
        with pytest.raises(DomainError) as raised:
            writer.add_input(source, "demo.sumocfg")
        assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_a_missing_source_is_an_input_error(runs: Path, tmp_path: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        with pytest.raises(DomainError) as raised:
            writer.add_input(tmp_path / "no-existe.xml", "no-existe.xml")
        assert raised.value.code is ErrorCode.INPUT_SCHEMA
        assert str(tmp_path) not in str(raised.value)


def test_only_a_final_status_can_be_published(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        with pytest.raises(ValueError, match="estado final"):
            writer.publish(
                status=cast("TerminalStatus", "running"), command=[], environment={}, exit_code=None
            )


def test_a_destination_created_meanwhile_is_not_overwritten(runs: Path) -> None:
    with RunWriter(runs, SPEC, run_id=RUN_ID, clock=clock) as writer:
        intruder = runs / RUN_ID
        intruder.mkdir()
        (intruder / "otro.txt").write_text("de otro proceso", encoding="utf-8")
        with pytest.raises(DomainError) as raised:
            publish_succeeded(writer)
        assert raised.value.code is ErrorCode.RUN_EXISTS
        provisional = (writer.path / "manifest.json").read_text(encoding="utf-8")
        assert RunManifest.model_validate_json(provisional).status == "running"
    assert files_of(runs / RUN_ID) == {"otro.txt"}


def test_a_corrupt_manifest_is_an_input_error(runs: Path) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        manifest = publish_succeeded(writer)
    final = runs / manifest.run_id
    make_writable(final)
    (final / "manifest.json").write_text("{no es json", encoding="utf-8")
    with pytest.raises(DomainError) as raised:
        read_run(runs, manifest.run_id)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def tamper_modify(final: Path) -> str:
    (final / "outputs" / "tripinfo.xml").write_text("<manipulado/>", encoding="utf-8")
    return final.name


def tamper_delete(final: Path) -> str:
    (final / "outputs" / "tripinfo.xml").unlink()
    return final.name


def tamper_extra(final: Path) -> str:
    (final / "outputs" / "extra.xml").write_text("<extra/>", encoding="utf-8")
    return final.name


def tamper_rename(final: Path) -> str:
    renamed = final.with_name("20261020T150000Z_simulation_otro0000")
    shutil.move(final, renamed)
    return renamed.name


@pytest.mark.parametrize(
    "tamper",
    [tamper_modify, tamper_delete, tamper_extra, tamper_rename],
    ids=["modified", "deleted", "extra-file", "renamed"],
)
def test_reading_detects_a_tampered_run(runs: Path, tamper: Callable[[Path], str]) -> None:
    with RunWriter(runs, SPEC, clock=clock) as writer:
        manifest = publish_succeeded(writer)
    final = runs / manifest.run_id
    make_writable(final)
    run_id = tamper(final)
    with pytest.raises(DomainError) as raised:
        read_run(runs, run_id)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_reading_a_missing_run_fails(runs: Path) -> None:
    with pytest.raises(DomainError) as raised:
        read_run(runs, RUN_ID)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_the_clock_must_be_timezone_aware(runs: Path) -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        RunWriter(runs, SPEC, clock=lambda: datetime(2026, 10, 20))
    assert not runs.exists() or not any(p.name.startswith(".lock-") for p in runs.iterdir())


@pytest.mark.skipif(sys.platform != "win32", reason="las uniones solo existen en Windows")
def test_a_junction_among_the_outputs_is_refused(runs: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with RunWriter(runs, SPEC, clock=clock) as writer:
        link = writer.output_path("linked")
        subprocess.run(  # noqa: S603
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(elsewhere)],  # noqa: S607
            check=True,
            capture_output=True,
        )
        try:
            with pytest.raises(DomainError) as raised:
                publish_succeeded(writer)
            assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
        finally:
            link.rmdir()
