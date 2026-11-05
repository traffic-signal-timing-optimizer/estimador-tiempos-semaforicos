"""Búsqueda de referencias con SUMO real (DEV14 F2, HU08, QA16 y QA18 de integración).

Red de demostración de dos movimientos (``prepared_inputs``): 4 candidatos (el plan vigente y 3 de
la muestra), 2 semillas de búsqueda y 2 finalistas con 2 semillas: 12 corridas por búsqueda.
"""

import json
import shutil
import stat
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from search_tools import (
    FINAL_SEEDS,
    FINALIST_SEEDS,
    SEARCH_SEEDS,
    Search,
    protocol,
    run,
    run_folders,
    search_in,
)
from search_tools import journal_lines as read_lines
from semaforo.dominio.errors import ErrorCode
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.evaluation import (
    MAX_RUN_MANIFEST_BYTES,
    SearchOutcome,
    SearchSetup,
    identity_digest,
    run_search,
)
from semaforo.referencias.evidence import EvidenceReport, reexpress_identity, verify_search_evidence
from semaforo.referencias.label import publish_label, read_label
from semaforo.simulacion.prepare import PreparationRequest, publish_inputs
from semaforo.simulacion.run_inputs import verify_inputs
from semaforo.simulacion.runner import RunLimits
from semaforo.trazabilidad.hashing import sha256_bytes

pytestmark = pytest.mark.sumo


def journal_lines(search: Search) -> list[dict[str, Any]]:
    return read_lines(search.journal)


def summary(outcome: SearchOutcome) -> object:
    """Lo que debe repetirse entre búsquedas iguales (sin identificadores de corrida)."""
    data: dict[str, Any] = json.loads(json.dumps(outcome.to_json()))
    for stage in ("search_scores", "finalist_scores"):
        for score in data[stage]:
            for seed in score["seeds"]:
                seed.pop("run_id")
    return data


@pytest.fixture(scope="module")
def finished(tmp_path_factory: pytest.TempPathFactory) -> tuple[Search, SearchOutcome]:
    search = search_in(tmp_path_factory.mktemp("completa"))
    return search, run(search)


def test_qa16_a_search_evaluates_every_candidate_and_chooses_a_reference(
    finished: tuple[Search, SearchOutcome],
) -> None:
    search, outcome = finished
    assert not outcome.interrupted
    assert outcome.selection is not None
    assert outcome.selection.status == "reference"
    assert len(outcome.search_scores) == 4
    assert all(score.eligible for score in outcome.search_scores)
    assert outcome.simulation_count == 4 * 2 + 2 * 2 == run_folders(search)
    winner = outcome.selection.winner
    assert winner is not None
    assert winner.candidate_id in outcome.selection.finalists
    assert winner.stage == "finalists"
    assert [o.seed for o in winner.outcomes] == FINALIST_SEEDS


def test_qa18_each_stage_uses_only_its_seeds_and_the_final_ones_are_never_run(
    finished: tuple[Search, SearchOutcome],
) -> None:
    search, outcome = finished
    seeds = [line for line in journal_lines(search) if line["type"] == "seed"]
    assert {line["seed"] for line in seeds if line["stage"] == "search"} == set(SEARCH_SEEDS)
    assert {line["seed"] for line in seeds if line["stage"] == "finalists"} == set(FINALIST_SEEDS)
    assert not {line["seed"] for line in seeds} & set(FINAL_SEEDS)
    finalists = {line["candidate_id"] for line in seeds if line["stage"] == "finalists"}
    assert outcome.selection is not None
    assert finalists == set(outcome.selection.finalists)


def test_the_journal_records_every_program_and_run(finished: tuple[Search, SearchOutcome]) -> None:
    search, outcome = finished
    lines = journal_lines(search)
    assert lines[0]["type"] == "header"
    assert lines[0]["identity"] == json.loads(json.dumps(dict(outcome.identity)))
    assert [line["type"] for line in lines[1:]].count("program") == 4
    assert [line["type"] for line in lines[1:]].count("seed") == 12
    for line in lines:
        if line["type"] == "seed":
            assert (search.setup.inputs_root / line["inputs_dir"]).is_dir()
            assert (search.setup.runs_root / line["outcome"]["run_id"]).is_dir()


def test_qa16_repeating_with_the_same_journal_runs_nothing_and_gives_the_same_result(
    finished: tuple[Search, SearchOutcome],
) -> None:
    search, outcome = finished
    before = run_folders(search)
    again = run(search)
    assert run_folders(search) == before
    assert again.to_json() == outcome.to_json()


def test_qa16_the_same_search_from_scratch_gives_the_same_reference(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    _, outcome = finished
    other = search_in(tmp_path)
    assert summary(run(other)) == summary(outcome)


def test_a_cancelled_search_is_interrupted_and_resumes_where_it_stopped(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    _, complete = finished
    search = search_in(tmp_path)
    cancel = threading.Event()
    allowed = 5

    def can_start() -> bool:
        nonlocal allowed
        allowed -= 1
        if allowed < 0:
            cancel.set()
        return True

    partial = run(search, can_start=can_start, cancel=cancel)
    assert partial.interrupted
    assert partial.selection is None
    done = [line for line in journal_lines(search) if line["type"] == "seed"]
    assert 0 < len(done) < 12
    resumed = run(search)
    assert not resumed.interrupted
    assert resumed.simulation_count == 12
    assert summary(resumed) == summary(complete)


def test_a_search_waits_while_it_may_not_start(tmp_path: Path) -> None:
    search = search_in(tmp_path)
    refusals = 3
    calls = 0

    def can_start() -> bool:
        nonlocal refusals, calls
        calls += 1
        if refusals > 0:
            refusals -= 1
            return False
        return True

    outcome = run(search, can_start=can_start, wait_s=0.01)
    assert outcome.simulation_count == 12
    assert calls >= 12 + 3


def test_a_saturated_scenario_has_no_eligible_candidate(tmp_path: Path) -> None:
    def saturate(scenario: dict[str, Any]) -> None:
        scenario["request"]["demand"][0]["flow_vph"] = 1200
        scenario["drain_max_s"] = 0

    search = search_in(tmp_path, saturate)
    outcome = run(search)
    assert outcome.selection is not None
    assert outcome.selection.status == "no_reference"
    assert outcome.selection.reason == "no_eligible_candidate"
    assert outcome.selection.ineligible_search["cohort_incomplete"] == 4
    assert outcome.finalist_scores == ()
    assert outcome.simulation_count == 8


def test_a_journal_of_another_search_is_rejected_before_running(
    finished: tuple[Search, SearchOutcome],
) -> None:
    search, _ = finished
    before = run_folders(search)
    other = replace(search, setup=replace(search.setup, sumo_options={"step-length": 0.5}))
    with pytest.raises(ReferenciasError) as caught:
        run(other)
    assert caught.value.field == "journal"
    assert run_folders(search) == before


def test_candidates_made_with_another_budget_are_rejected(tmp_path: Path) -> None:
    search = search_in(tmp_path)
    setup = replace(search.setup, protocol=protocol(search_budget=5))
    with pytest.raises(ReferenciasError) as caught:
        run_search(setup, search.candidates, search.journal)
    assert caught.value.code == ErrorCode.INPUT_SCHEMA
    assert caught.value.field == "candidates"
    assert not search.journal.exists()


def test_a_line_cut_by_a_crash_is_ignored_and_removed(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    copy = tmp_path / "bitacora.jsonl"
    shutil.copyfile(search.journal, copy)
    complete = copy.read_bytes()
    copy.write_bytes(complete + b'{"type": "seed", "stage": "sea')
    before = run_folders(search)
    again = run_search(search.setup, search.candidates, copy, workers=2)
    assert run_folders(search) == before
    assert again.to_json() == outcome.to_json()
    assert copy.read_bytes() == complete


def test_a_run_that_fails_is_recorded_and_its_candidate_cannot_win(tmp_path: Path) -> None:
    search = search_in(tmp_path)
    tight = replace(search.setup, limits=RunLimits(max_output_bytes=1_000))
    outcome = run(replace(search, setup=tight))
    assert outcome.selection is not None
    assert outcome.selection.reason == "no_eligible_candidate"
    assert outcome.selection.ineligible_search == {"run_failed": 4}
    seeds = [line for line in journal_lines(search) if line["type"] == "seed"]
    assert len(seeds) == outcome.simulation_count == 8
    for line in seeds:
        assert line["outcome"]["run_status"] == "failed"
        assert line["outcome"]["problems"] == ["run_failed"]
        assert (search.setup.runs_root / line["outcome"]["run_id"]).is_dir()


def test_a_run_that_cannot_be_measured_is_recorded_as_such(tmp_path: Path) -> None:
    search = search_in(tmp_path)
    other_zone = replace(search.setup, protocol=protocol(zone_lane_ids=["demo_N_0", "fuera_0"]))
    outcome = run(replace(search, setup=other_zone))
    assert outcome.selection is not None
    assert outcome.selection.ineligible_search == {"evaluation_failed": 4}
    seeds = [line["outcome"] for line in journal_lines(search) if line["type"] == "seed"]
    assert {seed["run_status"] for seed in seeds} == {"succeeded"}
    assert all("zona" in seed["message"] for seed in seeds)


def test_f3_the_label_of_a_real_search_is_published_and_read_back(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    folder = publish_label(
        tmp_path / "datos", search.setup, outcome, now=datetime(2026, 11, 3, tzinfo=UTC)
    )
    stored = read_label(folder)
    assert stored.label.status == "reference"
    assert stored.label.simulation_count == outcome.simulation_count
    assert stored.label.plan is not None
    assert stored.label.plan.cycle_s > 0
    root = search.setup.runs_root.parent
    needles = {str(root), root.as_posix(), json.dumps(str(root))[1:-1]}
    for path in folder.iterdir():
        text = path.read_text(encoding="utf-8")
        assert not any(needle in text for needle in needles), path.name


# --- identidad y vínculos de la bitácora (auditoría A01) ----------------------------------------


def seed_lines(search: Search) -> list[dict[str, Any]]:
    return [line for line in journal_lines(search) if line["type"] == "seed"]


def input_lines(search: Search) -> list[dict[str, Any]]:
    return [line for line in journal_lines(search) if line["type"] == "inputs"]


def rewritten(
    search: Search, tmp_path: Path, change: Callable[[list[dict[str, Any]]], None]
) -> Search:
    """La misma búsqueda con una copia de su bitácora cambiada por ``change``."""
    lines = journal_lines(search)
    change(lines)
    path = tmp_path / "bitacora-cambiada.jsonl"
    path.write_bytes(b"".join(json.dumps(line).encode("utf-8") + bytes([10]) for line in lines))
    return replace(search, journal=path)


def rejected_before_running(search: Search, original: Search) -> ReferenciasError:
    before = run_folders(original)
    with pytest.raises(ReferenciasError) as caught:
        run(search)
    assert caught.value.field == "journal"
    assert run_folders(original) == before
    return caught.value


def test_the_identity_fingerprints_are_the_ones_the_inputs_manifests_record(
    finished: tuple[Search, SearchOutcome],
) -> None:
    search, outcome = finished
    inputs = cast("dict[str, object]", outcome.identity["inputs"])
    folders = {search.setup.inputs_root / line["inputs_dir"] for line in input_lines(search)}
    assert len(folders) == 12
    for folder in folders:
        manifest = verify_inputs(folder)
        assert manifest.case_sha256 == inputs["case_sha256"]
        assert manifest.network.sha256 == inputs["network_sha256"]
        assert manifest.scenario_sha256 == inputs["scenario_sha256"]
        assert manifest.routes_sha256 == inputs["routes_sha256"]
        assert manifest.vehicle_types_sha256 == inputs["vehicle_types_sha256"]
        assert manifest.schema_version == inputs["inputs_schema_version"]
    assert str(inputs["sumo_version"])[0].isdigit()


def test_a_journal_cannot_be_reused_after_the_demand_changes(
    finished: tuple[Search, SearchOutcome],
) -> None:
    search, _ = finished
    request = search.setup.scenario.request
    first = request.demand[0].model_copy(update={"flow_vph": request.demand[0].flow_vph + 100})
    scenario = search.setup.scenario.model_copy(
        update={"request": request.model_copy(update={"demand": [first, *request.demand[1:]]})}
    )
    other = replace(search, setup=replace(search.setup, scenario=scenario))
    error = rejected_before_running(other, search)
    assert "otra búsqueda" in error.message


def test_a_journal_pointing_to_the_inputs_of_another_seed_is_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished

    def swap(lines: list[dict[str, Any]]) -> None:
        first, second = two_inputs_with_other_seeds(lines)
        first["inputs_dir"], second["inputs_dir"] = second["inputs_dir"], first["inputs_dir"]

    error = rejected_before_running(rewritten(search, tmp_path, swap), search)
    assert "no corresponde a esta búsqueda" in error.message
    assert "sumo_seed" in error.message


def test_inputs_altered_after_they_were_recorded_are_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished
    copy = tmp_path / "entradas"
    shutil.copytree(search.setup.inputs_root, copy)
    folder = copy / input_lines(search)[0]["inputs_dir"]
    target = folder / "cohorte.csv"
    target.chmod(stat.S_IWRITE)
    target.write_bytes(target.read_bytes() + b"x")
    other = replace(search, setup=replace(search.setup, inputs_root=copy))
    error = rejected_before_running(other, search)
    assert "no se puede verificar" in error.message


def test_a_journal_pointing_to_the_run_of_another_seed_is_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished

    def swap(lines: list[dict[str, Any]]) -> None:
        seeds = [line for line in lines if line["type"] == "seed"]
        first, second = seeds[0]["outcome"], seeds[1]["outcome"]
        first["run_id"], second["run_id"] = second["run_id"], first["run_id"]

    error = rejected_before_running(rewritten(search, tmp_path, swap), search)
    assert "no salió de las entradas anotadas" in error.message


def test_a_journal_pointing_to_a_run_that_does_not_exist_is_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished

    def lose(lines: list[dict[str, Any]]) -> None:
        next(line for line in lines if line["type"] == "seed")["outcome"]["run_id"] = "no-existe"

    error = rejected_before_running(rewritten(search, tmp_path, lose), search)
    assert "no se puede leer" in error.message


def test_a_journal_pointing_to_a_run_outside_its_folder_is_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished

    def escape(lines: list[dict[str, Any]]) -> None:
        next(line for line in lines if line["type"] == "seed")["outcome"]["run_id"] = "../fuera"

    error = rejected_before_running(rewritten(search, tmp_path, escape), search)
    assert "fuera" in error.message


def test_a_result_without_its_inputs_record_is_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished

    def drop(lines: list[dict[str, Any]]) -> None:
        lines.remove(next(line for line in lines if line["type"] == "inputs"))

    error = rejected_before_running(rewritten(search, tmp_path, drop), search)
    assert "no tiene su carpeta de entradas" in error.message


# --- evidencia de una búsqueda publicada (auditoría A01) ----------------------------------------


MOMENT = datetime(2026, 11, 4, tzinfo=UTC)


def evidence(
    search: Search,
    outcome: SearchOutcome,
    tmp_path: Path,
    **changes: Any,  # noqa: ANN401
) -> EvidenceReport:
    label = publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    arguments: dict[str, Any] = {
        "journal": search.journal,
        "inputs_root": search.setup.inputs_root,
        "runs_root": search.setup.runs_root,
        "case": search.setup.case,
        "protocol": search.setup.protocol,
    }
    arguments.update(changes)
    return verify_search_evidence(label, **arguments)


def test_the_evidence_of_a_search_checks_out_and_its_ids_come_from_its_identity(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    report = evidence(search, outcome, tmp_path)
    assert report.ok, report.problems
    assert report.runs == report.input_folders == 12
    assert report.identity_version == "2.0.0"
    assert report.stored_ids_match is True
    assert report.expected_search_run_id == report.search_run_id
    assert report.expected_label_id == report.label_id
    assert dict(report.fingerprints) == dict(cast("dict[str, Any]", outcome.identity["inputs"]))
    assert report.sumo_version == dict(report.fingerprints)["sumo_version"]


def test_the_evidence_recomputes_every_measurement(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    report = evidence(search, outcome, tmp_path, recompute=True)
    assert report.ok, report.problems
    assert report.recomputed == 12


def test_a_version_1_identity_is_reexpressed_as_the_one_a_new_search_would_have(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    report = evidence(search, outcome, tmp_path)
    old = {k: v for k, v in outcome.identity.items() if k != "inputs"} | {
        "journal_version": "1.0.0"
    }
    again = reexpress_identity(old, report.fingerprints)
    assert again == dict(outcome.identity)
    assert identity_digest(again) == identity_digest(outcome.identity)
    assert f"search-{identity_digest(again)}" == report.search_run_id


def test_the_evidence_notices_a_protocol_that_is_not_the_one_used(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    other = search.setup.protocol.model_copy(update={"queue_speed_threshold_mps": 5.0})
    report = evidence(search, outcome, tmp_path, protocol=other, recompute=True)
    assert not report.ok
    assert any("volver a medir" in problem for problem in report.problems)
    assert any("huellas de la identidad" in problem for problem in report.problems)


def test_the_evidence_notices_a_case_that_is_not_the_one_used(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    other = search.setup.case.model_copy(update={"description": "otra descripción"})
    report = evidence(search, outcome, tmp_path, case=other)
    assert any("el caso dado no es el de las corridas" in problem for problem in report.problems)


def test_the_evidence_notices_a_journal_of_another_search(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    lines = journal_lines(search)
    lines[0]["identity"]["scenario_id"] = "OTRO"
    path = tmp_path / "otra-bitacora.jsonl"
    path.write_bytes(b"".join(json.dumps(line).encode("utf-8") + bytes([10]) for line in lines))
    report = evidence(search, outcome, tmp_path, journal=path)
    assert any("la bitácora no es la de esta etiqueta" in problem for problem in report.problems)


def test_the_evidence_notices_inputs_altered_after_the_search(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    copy = tmp_path / "entradas"
    shutil.copytree(search.setup.inputs_root, copy)
    target = copy / input_lines(search)[0]["inputs_dir"] / "cohorte.csv"
    target.chmod(stat.S_IWRITE)
    target.write_bytes(target.read_bytes() + b"x")
    report = evidence(search, outcome, tmp_path, inputs_root=copy)
    assert not report.ok
    assert any(problem.startswith("entradas ") for problem in report.problems)


def test_the_evidence_notices_a_run_taken_from_another_seed(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    lines = journal_lines(search)
    seeds = [line for line in lines if line["type"] == "seed"]
    first, second = seeds[0]["outcome"], seeds[1]["outcome"]
    first["run_id"], second["run_id"] = second["run_id"], first["run_id"]
    path = tmp_path / "bitacora-cruzada.jsonl"
    path.write_bytes(b"".join(json.dumps(line).encode("utf-8") + bytes([10]) for line in lines))
    report = evidence(search, outcome, tmp_path, journal=path)
    assert any("no salió de las entradas anotadas" in problem for problem in report.problems)


def test_a_journal_that_is_not_a_file_is_refused(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    with pytest.raises(ReferenciasError) as caught:
        evidence(search, outcome, tmp_path, journal=tmp_path)
    assert caught.value.field == "journal"


@pytest.mark.parametrize("record", ["inputs", "seed"])
def test_a_journal_record_without_its_key_is_refused_with_a_clear_error(
    finished: tuple[Search, SearchOutcome], tmp_path: Path, record: str
) -> None:
    search, outcome = finished
    lines = journal_lines(search)
    del next(line for line in lines if line["type"] == record)["seed"]
    path = tmp_path / "bitacora-incompleta.jsonl"
    path.write_bytes(b"".join(json.dumps(line).encode("utf-8") + bytes([10]) for line in lines))
    with pytest.raises(ReferenciasError) as caught:
        evidence(search, outcome, tmp_path, journal=path)
    assert caught.value.field == "journal"


def test_a_seed_record_without_its_result_is_refused(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    lines = journal_lines(search)
    next(line for line in lines if line["type"] == "seed")["outcome"] = "nada"
    path = tmp_path / "bitacora-sin-resultado.jsonl"
    path.write_bytes(b"".join(json.dumps(line).encode("utf-8") + bytes([10]) for line in lines))
    with pytest.raises(ReferenciasError) as caught:
        evidence(search, outcome, tmp_path, journal=path)
    assert caught.value.field == "journal"


# --- ayudas para fabricar evidencia ajena -------------------------------------------------------


def two_inputs_with_other_seeds(
    lines: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dos registros de entradas del mismo candidato con semillas distintas."""
    records = [line for line in lines if line["type"] == "inputs"]
    first = records[0]
    other = next(
        line
        for line in records
        if line["candidate_id"] == first["candidate_id"] and line["seed"] != first["seed"]
    )
    return first, other


def same_seed_in_two_candidates(
    lines: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dos resultados de la misma etapa y semilla, de candidatos distintos."""
    seeds = [line for line in lines if line["type"] == "seed"]
    first = seeds[0]
    other = next(
        line
        for line in seeds
        if line["stage"] == first["stage"]
        and line["seed"] == first["seed"]
        and line["candidate_id"] != first["candidate_id"]
    )
    return first, other


def forged_runs(
    search: Search, tmp_path: Path, change: Callable[[dict[str, Any]], None]
) -> tuple[Path, str]:
    """Una copia de las corridas con el manifiesto de la primera cambiado por ``change``."""
    root = tmp_path / "corridas"
    shutil.copytree(search.setup.runs_root, root)
    run_id = str(seed_lines(search)[0]["outcome"]["run_id"])
    path = root / run_id / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.chmod(stat.S_IWRITE)
    path.write_text(json.dumps(data), encoding="utf-8")
    return root, run_id


def foreign_inputs(
    search: Search, tmp_path: Path, change: Callable[[SearchSetup], SearchSetup]
) -> tuple[Path, str]:
    """Una copia de las entradas con una carpeta más, válida pero hecha con otros insumos.

    Es la del primer trabajo de la bitácora. Devuelve la raíz nueva y la ruta de la carpeta.
    """
    root = tmp_path / "entradas-ajenas"
    shutil.copytree(search.setup.inputs_root, root)
    first = input_lines(search)[0]
    program = next(
        line
        for line in journal_lines(search)
        if line["type"] == "program" and line["candidate_id"] == first["candidate_id"]
    )
    setup = change(search.setup)
    request = PreparationRequest(
        case=setup.case,
        case_dir=setup.case_dir,
        scenario=setup.scenario,
        routes=setup.routes,
        vehicle_types=setup.vehicle_types,
        program_dir=search.setup.programs_root / program["program_dir"],
        sumo_seed=first["seed"],
        sumo_options=setup.sumo_options,
    )
    folder = publish_inputs(root, request)
    return root, folder.relative_to(root).as_posix()


def with_options(setup: SearchSetup) -> SearchSetup:
    return replace(setup, sumo_options={"lateral-resolution": 0.8})


def with_other_flow(setup: SearchSetup) -> SearchSetup:
    request = setup.scenario.request
    first = request.demand[0].model_copy(update={"flow_vph": request.demand[0].flow_vph + 100})
    changed = request.model_copy(update={"demand": [first, *request.demand[1:]]})
    return replace(setup, scenario=setup.scenario.model_copy(update={"request": changed}))


def with_other_types(setup: SearchSetup) -> SearchSetup:
    data = setup.vehicle_types.model_dump(mode="json")
    data["types"]["car"]["attributes"]["length"] = 6.5
    return replace(setup, vehicle_types=type(setup.vehicle_types).model_validate(data))


FOREIGN = [
    ("opciones-de-sumo", with_options, "sumo_options"),
    ("demanda", with_other_flow, "scenario_sha256"),
    ("tipos-de-vehiculo", with_other_types, "vehicle_types_sha256"),
]


@pytest.mark.parametrize(
    ("change", "field"), [(c, f) for _, c, f in FOREIGN], ids=[n for n, _, _ in FOREIGN]
)
def test_valid_inputs_made_with_other_inputs_are_rejected_naming_the_difference(
    finished: tuple[Search, SearchOutcome],
    tmp_path: Path,
    change: Callable[[SearchSetup], SearchSetup],
    field: str,
) -> None:
    search, _ = finished
    root, relative = foreign_inputs(search, tmp_path, change)

    def point(lines: list[dict[str, Any]]) -> None:
        next(line for line in lines if line["type"] == "inputs")["inputs_dir"] = relative

    other = rewritten(search, tmp_path, point)
    other = replace(other, setup=replace(search.setup, inputs_root=root))
    error = rejected_before_running(other, search)
    assert "no corresponde a esta búsqueda" in error.message
    assert field in error.message


def test_programs_swapped_between_candidates_are_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished

    def swap(lines: list[dict[str, Any]]) -> None:
        first, second = [line for line in lines if line["type"] == "program"][:2]
        first["program_dir"], second["program_dir"] = second["program_dir"], first["program_dir"]

    error = rejected_before_running(rewritten(search, tmp_path, swap), search)
    assert "no usan el programa anotado" in error.message


def test_runs_of_the_same_seed_swapped_between_candidates_are_rejected(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished

    def swap(lines: list[dict[str, Any]]) -> None:
        first, second = same_seed_in_two_candidates(lines)
        first["outcome"]["run_id"], second["outcome"]["run_id"] = (
            second["outcome"]["run_id"],
            first["outcome"]["run_id"],
        )

    error = rejected_before_running(rewritten(search, tmp_path, swap), search)
    assert "no salió de las entradas anotadas" in error.message


def test_a_run_manifest_over_the_size_limit_is_rejected_before_parsing(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, _ = finished
    root, run_id = forged_runs(search, tmp_path, lambda _data: None)
    path = root / run_id / "manifest.json"
    path.write_bytes(b" " * (MAX_RUN_MANIFEST_BYTES + 1))
    other = replace(search, setup=replace(search.setup, runs_root=root))
    error = rejected_before_running(other, search)
    assert "demasiado grande" in error.message


# --- la evidencia detecta lo mismo --------------------------------------------------------------


def test_the_evidence_notices_inputs_taken_from_another_seed(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    lines = journal_lines(search)
    first, second = two_inputs_with_other_seeds(lines)
    first["inputs_dir"], second["inputs_dir"] = second["inputs_dir"], first["inputs_dir"]
    path = tmp_path / "bitacora-cruzada.jsonl"
    path.write_bytes(b"".join(json.dumps(line).encode("utf-8") + bytes([10]) for line in lines))
    report = evidence(search, outcome, tmp_path, journal=path)
    assert any("su semilla no es la anotada" in problem for problem in report.problems)


def test_the_evidence_notices_runs_of_the_same_seed_swapped_between_candidates(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    lines = journal_lines(search)
    first, second = same_seed_in_two_candidates(lines)
    first["outcome"]["run_id"], second["outcome"]["run_id"] = (
        second["outcome"]["run_id"],
        first["outcome"]["run_id"],
    )
    path = tmp_path / "bitacora-cruzada.jsonl"
    path.write_bytes(b"".join(json.dumps(line).encode("utf-8") + bytes([10]) for line in lines))
    report = evidence(search, outcome, tmp_path, journal=path)
    assert any("no salió de las entradas anotadas" in problem for problem in report.problems)


def test_the_evidence_notices_runs_made_with_more_than_one_version_of_sumo(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished

    def other_version(data: dict[str, Any]) -> None:
        data["environment"]["sumo"] = "0.0.1"

    root, _ = forged_runs(search, tmp_path, other_version)
    report = evidence(search, outcome, tmp_path, runs_root=root)
    assert any("más de una versión de SUMO" in problem for problem in report.problems)


def test_the_evidence_notices_inputs_that_do_not_share_their_options(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    root, relative = foreign_inputs(search, tmp_path, with_options)

    def point(lines: list[dict[str, Any]]) -> None:
        next(line for line in lines if line["type"] == "inputs")["inputs_dir"] = relative

    path = rewritten(search, tmp_path, point).journal
    report = evidence(search, outcome, tmp_path, journal=path, inputs_root=root)
    assert any("no comparten sumo_options" in problem for problem in report.problems)


def test_the_evidence_notices_a_protocol_with_another_name(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    other = search.setup.protocol.model_copy(update={"protocol_id": "OTRO"})
    report = evidence(search, outcome, tmp_path, protocol=other)
    assert any("no es el de la etiqueta" in problem for problem in report.problems)


def test_the_evidence_notices_a_trace_whose_identity_does_not_give_the_label_ids(
    finished: tuple[Search, SearchOutcome], tmp_path: Path
) -> None:
    search, outcome = finished
    label = publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    trace_path = label / "traza.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["identity"]["seeds_search"] = [999]
    forged = json.dumps(trace).encode("utf-8")
    trace_path.chmod(stat.S_IWRITE)
    trace_path.write_bytes(forged)
    manifest_path = label / "manifiesto.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["traza.json"] = sha256_bytes(forged)
    manifest_path.chmod(stat.S_IWRITE)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = verify_search_evidence(
        label,
        journal=search.journal,
        inputs_root=search.setup.inputs_root,
        runs_root=search.setup.runs_root,
        case=search.setup.case,
        protocol=search.setup.protocol,
    )
    assert any("no salen de su identidad" in problem for problem in report.problems)
