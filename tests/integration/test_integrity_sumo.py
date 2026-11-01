"""Vínculos de una corrida y revisión del espacio de trabajo con SUMO real (DEV08 F2, D6 y D7)."""

import shutil
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from prepared_inputs import request_for
from semaforo.app.integrity import (
    CASES,
    INPUT_FOLDERS,
    PROGRAMS,
    RunTrace,
    trace_run,
    verify_workspace,
)
from semaforo.app.reception import receive_case
from semaforo.app.simulate import run_prepared
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.prepare import publish_inputs
from semaforo.simulacion.run_inputs import verify_inputs
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.store import RunSpec, RunWriter
from workspace_tools import build_workspace, tamper

pytestmark = pytest.mark.sumo

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"


def clock() -> datetime:
    return datetime(2026, 11, 1, 21, 0, tzinfo=UTC)


@pytest.fixture
def built(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    workspace, inputs = build_workspace(tmp_path)
    yield workspace, inputs
    remove_tree(workspace)


def run_once(
    workspace: Path,
    inputs: Path,
    sumo: Path,
    *,
    wall_timeout_s: float | None = None,
    retry_of: str | None = None,
) -> str:
    report = run_prepared(
        inputs, workspace, sumo=sumo, clock=clock, wall_timeout_s=wall_timeout_s, retry_of=retry_of
    )
    return report.run_id


def statuses(trace: RunTrace) -> dict[str, str]:
    return {link.kind: link.status for link in trace.links}


# --- la cadena completa -----------------------------------------------------------------------


def test_the_chain_of_a_prepared_run_is_verified_link_by_link(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    trace = trace_run(workspace, run_id)
    assert trace.status == "complete"
    assert [(link.kind, link.status) for link in trace.links] == [
        ("run", "verified"),
        ("inputs_copy", "verified"),
        ("inputs", "verified"),
        ("program", "verified"),
        ("case", "verified"),
    ]
    paths = {link.kind: link.path for link in trace.links}
    assert paths["inputs"] == inputs.relative_to(workspace).as_posix()
    assert paths["program"] is not None and paths["program"].startswith(PROGRAMS)
    case_id = next((workspace / CASES).iterdir()).name
    assert paths["case"] == f"{CASES}/{case_id}/case.json"
    for link in trace.links:
        assert link.path is None or not Path(link.path).is_absolute()


def test_a_case_edited_after_preparing_the_inputs_breaks_the_chain(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    case_file = next((workspace / CASES).iterdir()) / "case.json"
    text = case_file.read_text(encoding="utf-8")
    case_file.write_text(
        text.replace('"description": "', '"description": "editada: ', 1), encoding="utf-8"
    )
    trace = trace_run(workspace, run_id)
    case_link = next(link for link in trace.links if link.kind == "case")
    assert (trace.status, case_link.status) == ("broken", "changed")
    assert case_link.detail == "el caso cambió después de preparar las entradas"


def test_a_case_that_is_no_longer_valid_breaks_the_chain(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    case_file = next((workspace / CASES).iterdir()) / "case.json"
    case_file.write_text("{no es json", encoding="utf-8")
    case_link = next(link for link in trace_run(workspace, run_id).links if link.kind == "case")
    assert case_link.status == "changed"
    assert case_link.detail is not None and case_link.detail.startswith("INPUT_SCHEMA")


def test_the_inputs_link_finds_the_exact_folder_among_several(
    tmp_path: Path, built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, first = built
    request = request_for(tmp_path)
    later = publish_inputs(workspace / INPUT_FOLDERS, request, datetime(2026, 11, 2, tzinfo=UTC))
    assert sorted([first.name, later.name])[0] == first.name  # la primera queda antes
    run_id = run_once(workspace, later, sumo_binary)
    link = next(link for link in trace_run(workspace, run_id).links if link.kind == "inputs")
    assert (link.status, link.path) == ("verified", later.relative_to(workspace).as_posix())


def test_a_set_aside_copy_is_never_taken_for_the_published_inputs(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    hidden = inputs.parent / f".tmp-{inputs.name}-abc123"  # una publicación a medias, idéntica
    shutil.copytree(inputs, hidden)
    remove_tree(inputs)
    link = next(link for link in trace_run(workspace, run_id).links if link.kind == "inputs")
    assert link.status == "not_found"


def test_an_inputs_folder_altered_after_the_run_is_detected(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    tamper(inputs / "programa.tll.xml")
    trace = trace_run(workspace, run_id)
    assert statuses(trace)["inputs"] == "altered"
    assert statuses(trace)["inputs_copy"] == "verified"  # la copia de la corrida no cambió


@pytest.mark.parametrize(
    ("removed", "kind"), [(INPUT_FOLDERS, "inputs"), (PROGRAMS, "program"), (CASES, "case")]
)
def test_a_missing_link_is_reported_as_not_found(
    built: tuple[Path, Path], sumo_binary: Path, removed: str, kind: str
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    remove_tree(workspace / removed)
    trace = trace_run(workspace, run_id)
    assert (trace.status, statuses(trace)[kind]) == ("broken", "not_found")


def test_a_program_altered_after_the_run_is_detected(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    program_dir = next(next((workspace / PROGRAMS).iterdir()).iterdir())
    tamper(program_dir / "tramos.json")
    assert statuses(trace_run(workspace, run_id))["program"] == "altered"


def test_an_altered_run_stops_the_chain_at_the_first_link(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_id = run_once(workspace, inputs, sumo_binary)
    tamper(workspace / "ejecuciones" / run_id / "outputs" / "tripinfo.xml")
    trace = trace_run(workspace, run_id)
    assert trace.status == "broken"
    assert [(link.kind, link.status) for link in trace.links] == [("run", "altered")]


def test_a_retry_links_to_the_run_it_retried(built: tuple[Path, Path], sumo_binary: Path) -> None:
    workspace, inputs = built
    first = run_once(workspace, inputs, sumo_binary, wall_timeout_s=0.001)
    second = run_once(workspace, inputs, sumo_binary, retry_of=first)
    trace = trace_run(workspace, second)
    assert statuses(trace)["retry_of"] == "verified"
    assert trace.status == "complete"


def test_a_retry_of_an_interrupted_run_links_to_the_set_aside_folder(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    crashed = "20261101T210000Z_simulation_caida000"
    manifest = verify_inputs(inputs)
    spec = RunSpec(
        kind="simulation",
        case_id=manifest.case_id,
        case_version=manifest.case_version,
        scenario_id=manifest.scenario_id,
    )
    with pytest.raises(RuntimeError), RunWriter(workspace / "ejecuciones", spec, run_id=crashed):
        raise RuntimeError("caída simulada")
    second = run_once(workspace, inputs, sumo_binary, retry_of=crashed)
    trace = trace_run(workspace, second)
    assert statuses(trace)["retry_of"] == "incomplete"
    assert trace.status == "broken"  # la anterior no es una corrida verificable


def test_tracing_a_run_that_does_not_exist_or_is_unsafe_is_refused(
    built: tuple[Path, Path],
) -> None:
    workspace, _ = built
    with pytest.raises(DomainError) as raised:
        trace_run(workspace, "20261101T210000Z_simulation_noexiste")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    with pytest.raises(DomainError) as raised:
        trace_run(workspace, "../fuera")
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED


# --- corridas de una recepción de DEV00 -------------------------------------------------------


def test_a_reception_run_links_to_its_copy_of_the_originals(
    tmp_path: Path, sumo_binary: Path
) -> None:
    workspace = tmp_path / "datos"
    try:
        record = receive_case(
            DEMO, "demo.sumocfg", workspace, case_id="SYNTHETIC_DEMO", sumo=sumo_binary
        )
        trace = trace_run(workspace, record.base_run.run_id)
        assert [(link.kind, link.status) for link in trace.links] == [
            ("run", "verified"),
            ("snapshot", "verified"),
        ]
        snapshot = workspace / str(trace.links[1].path)
        tamper(next(p for p in snapshot.iterdir() if p.suffix == ".xml"))
        assert statuses(trace_run(workspace, record.base_run.run_id))["snapshot"] == "altered"
        remove_tree(snapshot)
        assert statuses(trace_run(workspace, record.base_run.run_id))["snapshot"] == "not_found"
    finally:
        remove_tree(workspace)


# --- revisión de todo el espacio de trabajo ---------------------------------------------------


def test_a_complete_workspace_is_reported_intact_family_by_family(
    tmp_path: Path, built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    run_once(workspace, inputs, sumo_binary)
    receive_case(DEMO, "demo.sumocfg", workspace, case_id="SYNTHETIC_DEMO", sumo=sumo_binary)
    report = verify_workspace(workspace, clock=clock)
    assert report.status == "intact"
    families = {item.family for item in report.items}
    assert families == {"runs", "receptions", "snapshots", "programs", "inputs"}
    assert all(item.status == "intact" for item in report.items)
    assert report.counts["intact"] == len(report.items) == 6  # 2 corridas y una de cada otra
    assert report.checked_at == clock()


@pytest.mark.parametrize("family", ["runs", "receptions", "snapshots", "programs", "inputs"])
def test_an_altered_folder_of_any_family_is_reported(
    built: tuple[Path, Path], sumo_binary: Path, family: str
) -> None:
    workspace, inputs = built
    run_once(workspace, inputs, sumo_binary)
    receive_case(DEMO, "demo.sumocfg", workspace, case_id="SYNTHETIC_DEMO", sumo=sumo_binary)
    before = verify_workspace(workspace, clock=clock)
    target = next(item for item in before.items if item.family == family)
    folder = workspace / target.path
    victim = sorted(p for p in folder.rglob("*") if p.is_file())[-1]
    tamper(victim)
    report = verify_workspace(workspace, clock=clock)
    assert report.status == "altered"
    (altered,) = [item for item in report.items if item.status == "altered"]
    if family == "runs":  # una recepción comprueba también su corrida base
        assert altered.path == target.path or altered.family in {"runs", "receptions"}
    else:
        assert (altered.family, altered.path) == (family, target.path)
    assert altered.detail is not None


def test_checking_the_workspace_changes_nothing(
    built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    cancel = threading.Event()
    cancel.set()
    run_prepared(inputs, workspace, sumo=sumo_binary, cancel=cancel)
    (workspace / "ejecuciones" / ".tmp-abcd1234").mkdir()

    def tree() -> list[tuple[str, int]]:
        return sorted(
            (p.relative_to(workspace).as_posix(), p.stat().st_mtime_ns)
            for p in workspace.rglob("*")
        )

    snapshot = tree()
    verify_workspace(workspace, clock=clock)
    assert tree() == snapshot
