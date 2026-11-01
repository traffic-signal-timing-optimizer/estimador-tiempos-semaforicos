"""Reglas de un reintento: qué corrida se puede reintentar y qué queda intacto (DEV07 F3, D9)."""

import os
import stat
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.interrupted import recover_interrupted
from semaforo.trazabilidad.manifest import Error as RunError
from semaforo.trazabilidad.manifest import RunManifest, TerminalStatus
from semaforo.trazabilidad.retry import check_retry
from semaforo.trazabilidad.store import RunSpec, RunWriter, read_run

NOW = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)
FAILURE = RunError(code="SIM_FAILED", field=None, message="SUMO terminó con código 1")
BASE = RunSpec(kind="simulation", case_id="CASO_A", case_version="2.0.0", scenario_id="ESC_1")


def clock() -> datetime:
    return NOW


@pytest.fixture
def runs(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "runs"
    yield root
    remove_tree(root)


def publish(runs: Path, status: TerminalStatus, spec: RunSpec = BASE) -> RunManifest:
    with RunWriter(runs, spec, clock=clock) as writer:
        writer.output_path("tripinfo.xml").write_text("<tripinfos/>", encoding="utf-8")
        return writer.publish(
            status=status,
            command=["sumo"],
            environment={},
            exit_code=0 if status == "succeeded" else 1,
            error=None if status == "succeeded" else FAILURE,
        )


def retry_of(run_id: str | None, spec: RunSpec = BASE) -> RunSpec:
    return RunSpec(
        kind=spec.kind,
        case_id=spec.case_id,
        case_version=spec.case_version,
        scenario_id=spec.scenario_id,
        retry_of=run_id,
    )


def refused(runs: Path, spec: RunSpec) -> DomainError:
    with pytest.raises(DomainError) as raised:
        check_retry(runs, spec)
    return raised.value


# --- qué se puede reintentar ---------------------------------------------------------------


def test_a_run_that_is_not_a_retry_needs_no_check(runs: Path) -> None:
    check_retry(runs, BASE)  # ni siquiera existe la carpeta
    assert not runs.exists()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_a_failed_or_cancelled_run_can_be_retried(runs: Path, status: TerminalStatus) -> None:
    previous = publish(runs, status)
    check_retry(runs, retry_of(previous.run_id))


def test_a_succeeded_run_cannot_be_retried(runs: Path) -> None:
    previous = publish(runs, "succeeded")
    error = refused(runs, retry_of(previous.run_id))
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert error.field == "retry_of"
    assert "exitosa" in error.message


def test_a_run_that_does_not_exist_cannot_be_retried(runs: Path) -> None:
    error = refused(runs, retry_of("20261101T100000Z_simulation_noexiste"))
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert "no existe" in error.message
    runs.mkdir()
    assert refused(runs, retry_of("20261101T100000Z_simulation_noexiste")).code is (
        ErrorCode.INPUT_SCHEMA
    )


@pytest.mark.parametrize("unsafe", ["../fuera", "a/b", "", ".oculta", "C:\\x"])
def test_an_unsafe_identifier_is_refused(runs: Path, unsafe: str) -> None:
    error = refused(runs, retry_of(unsafe))
    assert (error.code, error.field) == (ErrorCode.PATH_NOT_ALLOWED, "retry_of")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            RunSpec(kind="simulation", case_id="OTRO", case_version="2.0.0", scenario_id="ESC_1"),
            "el caso",
        ),
        (
            RunSpec(kind="simulation", case_id="CASO_A", case_version="3.0.0", scenario_id="ESC_1"),
            "la versión del caso",
        ),
        (
            RunSpec(kind="simulation", case_id="CASO_A", case_version="2.0.0", scenario_id="ESC_2"),
            "el escenario",
        ),
        (RunSpec(kind="simulation", case_id="CASO_A", case_version="2.0.0"), "el escenario"),
    ],
    ids=["case", "version", "scenario", "no-scenario"],
)
def test_a_retry_must_keep_the_case_the_version_and_the_scenario(
    runs: Path, change: RunSpec, message: str
) -> None:
    previous = publish(runs, "failed")
    error = refused(runs, retry_of(previous.run_id, change))
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert error.message.startswith(message)


def test_a_published_run_that_was_altered_is_not_trusted(runs: Path) -> None:
    previous = publish(runs, "failed")
    output = runs / previous.run_id / "outputs" / "tripinfo.xml"
    os.chmod(output, stat.S_IWRITE | stat.S_IREAD)
    output.write_text("<manipulado/>", encoding="utf-8")
    assert refused(runs, retry_of(previous.run_id)).code is ErrorCode.HASH_MISMATCH


def test_a_retry_of_a_retry_is_allowed(runs: Path) -> None:
    first = publish(runs, "failed")
    second = publish(runs, "failed", retry_of(first.run_id))
    assert second.retry_of == first.run_id
    check_retry(runs, retry_of(second.run_id))


# --- corridas interrumpidas -----------------------------------------------------------------


CRASHED = "20261101T100000Z_simulation_caida000"


def crash(runs: Path, spec: RunSpec = BASE) -> str:
    with pytest.raises(RuntimeError), RunWriter(runs, spec, run_id=CRASHED, clock=clock):
        raise RuntimeError("caída simulada")
    return CRASHED


def test_an_interrupted_run_can_be_retried(runs: Path) -> None:
    run_id = crash(runs)
    recover_interrupted(runs, clock=clock)
    check_retry(runs, retry_of(run_id))


def test_an_interrupted_run_of_another_case_cannot_be_retried(runs: Path) -> None:
    other = RunSpec(kind="simulation", case_id="OTRO", case_version="2.0.0", scenario_id="ESC_1")
    run_id = crash(runs, other)
    recover_interrupted(runs, clock=clock)
    error = refused(runs, retry_of(run_id))
    assert error.message.startswith("el caso")


def test_an_interrupted_run_with_unknown_data_cannot_be_checked(runs: Path) -> None:
    run_id = crash(runs)
    recover_interrupted(runs, clock=clock)
    mark = runs / ".incompletas" / run_id / "INCOMPLETA.json"
    mark.write_text("{roto", encoding="utf-8")
    assert refused(runs, retry_of(run_id)).code is ErrorCode.INPUT_SCHEMA


def test_a_run_still_alive_is_not_a_retry_target(runs: Path) -> None:
    with RunWriter(runs, BASE, clock=clock) as writer:
        assert refused(runs, retry_of(writer.run_id)).code is ErrorCode.INPUT_SCHEMA


# --- el reintento no toca nada de lo anterior ------------------------------------------------


def test_a_retry_is_a_new_run_and_the_previous_one_stays_exactly_as_it_was(runs: Path) -> None:
    previous = publish(runs, "failed")
    manifest_hash = sha256_file(runs / previous.run_id / "manifest.json")
    spec = retry_of(previous.run_id)
    check_retry(runs, spec)
    retried = publish(runs, "succeeded", spec)
    assert retried.run_id != previous.run_id
    assert retried.retry_of == previous.run_id
    assert read_run(runs, retried.run_id).retry_of == previous.run_id
    assert read_run(runs, previous.run_id) == previous
    assert sha256_file(runs / previous.run_id / "manifest.json") == manifest_hash
    assert previous.retry_of is None
