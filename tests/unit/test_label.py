"""Etiqueta publicada y verificable de una búsqueda (DEV14 F3, HU08; sin SUMO).

Datos sintéticos: la búsqueda se arma con la red de demostración y las cifras de las corridas a
mano. Las corridas reales están en ``tests/integration/test_search_sumo.py``.
"""

import json
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from prepared_inputs import FIXTURES
from search_tools import (
    FINALIST_SEEDS,
    SEARCH_SEEDS,
    Search,
    new_search,
    outcome_for,
    protocol,
    reference_outcome,
)
from semaforo.app.integrity import verify_workspace
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import prepare
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.evaluation import SearchOutcome, search_identity
from semaforo.referencias.label import (
    COVERAGE_FILE,
    LABEL_FILE,
    LABELS,
    MANIFEST_FILE,
    TRACE_FILE,
    Label,
    Plan,
    publish_label,
    read_label,
)
from semaforo.referencias.search import generate_candidates
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import TrazabilidadError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "label.schema.json"
DOCUMENTATION_KEYS = frozenset({"description", "title", "$schema"})
MOMENT = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)

type Json = dict[str, Json] | list[Json] | str | int | float | bool | None


def without_documentation(node: Json) -> Json:
    if isinstance(node, dict):
        return {
            key: without_documentation(value)
            for key, value in node.items()
            if key not in DOCUMENTATION_KEYS
        }
    if isinstance(node, list):
        return [without_documentation(item) for item in node]
    return node


def tamper(path: Path, data: dict[str, Any]) -> None:
    path.chmod(stat.S_IWRITE)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- contrato ---------------------------------------------------------------------------------


def test_the_model_has_the_published_contract_structure() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert without_documentation(Label.model_json_schema()) == without_documentation(published)


def test_the_reference_fixture_is_accepted_by_the_model() -> None:
    label = Label.model_validate_json((FIXTURES / "label.json").read_bytes())
    assert label.status == "reference"
    assert label.plan is not None


def test_a_reference_needs_its_plan() -> None:
    with pytest.raises(ValidationError):
        Label(
            label_id="label-x",
            scenario_id="S",
            case_version="1.0.0",
            status="reference",
            plan=None,
            search_run_id="search-x",
            protocol_id="P",
            candidate_count=1,
            simulation_count=1,
            evidence_status="fixture_only",
            reason=None,
        )


def test_a_no_reference_needs_its_reason_and_no_plan() -> None:
    base: dict[str, Any] = {
        "label_id": "label-x",
        "scenario_id": "S",
        "case_version": "1.0.0",
        "status": "no_reference",
        "search_run_id": "search-x",
        "protocol_id": "P",
        "candidate_count": 1,
        "simulation_count": 1,
        "evidence_status": "fixture_only",
    }
    with pytest.raises(ValidationError):
        Label(**base, plan=None, reason=None)
    with pytest.raises(ValidationError):
        Label(**base, plan=Plan(slot_durations_s={}, cycle_s=1, greens_s={}), reason="x")


def test_a_cycle_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Label(
            label_id="label-x",
            scenario_id="S",
            case_version="1.0.0",
            status="reference",
            plan=Plan(slot_durations_s={"s1": 1}, cycle_s=0, greens_s={}),
            search_run_id="search-x",
            protocol_id="P",
            candidate_count=1,
            simulation_count=1,
            evidence_status="fixture_only",
            reason=None,
        )


# --- publicar y leer ----------------------------------------------------------------------------


def test_a_reference_is_published_and_read_back(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    workspace = tmp_path / "datos"
    folder = publish_label(workspace, search.setup, reference_outcome(search), now=MOMENT)

    assert folder.parent == workspace / LABELS / search.setup.case.case_id
    assert folder.name.startswith("20261103T120000Z_")
    stored = read_label(folder)
    label = stored.label
    assert label.status == "reference"
    assert label.reason is None
    assert label.scenario_id == search.setup.scenario.scenario_id
    assert label.protocol_id == search.setup.protocol.protocol_id
    assert label.candidate_count == len(search.candidates.candidates)
    assert label.simulation_count == len(SEARCH_SEEDS) + len(FINALIST_SEEDS)
    assert label.evidence_status == "fixture_only"


def test_the_plan_is_the_winner_with_its_cycle_and_greens(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    folder = publish_label(tmp_path / "datos", search.setup, reference_outcome(search), now=MOMENT)
    plan = read_label(folder).label.plan
    assert plan is not None
    winner = search.candidates.candidates[0]
    assert plan.slot_durations_s == pytest.approx(dict(winner.durations_s))
    assert plan.cycle_s == pytest.approx(sum(winner.durations_s.values()))
    assert set(plan.greens_s) == {group.id for group in search.setup.case.green_groups}


def test_the_folder_holds_label_trace_coverage_and_manifest(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    folder = publish_label(tmp_path / "datos", search.setup, reference_outcome(search), now=MOMENT)
    names = {path.name for path in folder.iterdir()}
    assert names == {LABEL_FILE, TRACE_FILE, COVERAGE_FILE, MANIFEST_FILE}
    stored = read_label(folder)
    assert set(stored.manifest.files) == {LABEL_FILE, TRACE_FILE, COVERAGE_FILE}
    trace = json.loads((folder / TRACE_FILE).read_text(encoding="utf-8"))
    assert trace["selection"]["status"] == "reference"
    coverage = json.loads((folder / COVERAGE_FILE).read_text(encoding="utf-8"))
    assert coverage["finalists"]["eligible"] == 1


def test_a_search_without_eligible_finalist_is_a_no_reference_label(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    outcome = outcome_for(search, search_clean=True, finalists_clean=False)
    folder = publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    label = read_label(folder).label
    assert label.status == "no_reference"
    assert label.plan is None
    assert label.reason == "no_eligible_finalist"


def test_a_search_without_eligible_candidate_is_a_no_reference_label(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    outcome = outcome_for(search, search_clean=False, finalists_clean=False)
    folder = publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    label = read_label(folder).label
    assert label.status == "no_reference"
    assert label.reason == "no_eligible_candidate"


def test_a_search_without_a_selection_is_not_published(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    outcome = replace(reference_outcome(search), selection=None)
    with pytest.raises(ReferenciasError) as error:
        publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_an_unfinished_search_is_not_published(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    unfinished = SearchOutcome(
        identity=search_identity(search.setup, search.candidates),
        candidates=search.candidates,
        search_scores=(),
        finalist_scores=(),
        selection=None,
        simulation_count=0,
        interrupted=True,
    )
    with pytest.raises(ReferenciasError) as error:
        publish_label(tmp_path / "datos", search.setup, unfinished, now=MOMENT)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_a_search_of_another_protocol_is_refused(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    outcome = reference_outcome(search)
    other = dict(outcome.identity) | {"search_budget": 99}
    changed = SearchOutcome(
        identity=other,
        candidates=outcome.candidates,
        search_scores=outcome.search_scores,
        finalist_scores=outcome.finalist_scores,
        selection=outcome.selection,
        simulation_count=outcome.simulation_count,
        interrupted=False,
    )
    with pytest.raises(ReferenciasError) as error:
        publish_label(tmp_path / "datos", search.setup, changed, now=MOMENT)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_the_same_label_cannot_be_published_twice_in_the_same_instant(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    workspace = tmp_path / "datos"
    publish_label(workspace, search.setup, reference_outcome(search), now=MOMENT)
    with pytest.raises(ReferenciasError) as error:
        publish_label(workspace, search.setup, reference_outcome(search), now=MOMENT)
    assert error.value.code == ErrorCode.RUN_EXISTS


def test_the_folder_is_named_in_utc_even_from_lima_time(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    lima = datetime(2026, 11, 3, 7, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    folder = publish_label(tmp_path / "datos", search.setup, reference_outcome(search), now=lima)
    assert folder.name.startswith("20261103T120000Z_")
    assert read_label(folder).manifest.created_at == MOMENT


def test_the_winner_need_not_be_the_first_candidate(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    outcome = outcome_for(search, search_clean=True, finalists_clean=True, index=2)
    plan = read_label(
        publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    ).label.plan
    third = dict(search.candidates.candidates[2].durations_s)
    assert third != dict(search.candidates.candidates[0].durations_s)
    assert plan is not None
    assert plan.slot_durations_s == pytest.approx(third)


def test_a_winner_that_is_not_a_candidate_is_refused(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    outcome = outcome_for(search, search_clean=True, finalists_clean=True, candidate_id="cand-x")
    with pytest.raises(ReferenciasError) as error:
        publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    assert error.value.code == ErrorCode.OUTPUT_INVALID
    assert not (tmp_path / "datos").exists()


def test_a_search_marked_interrupted_is_not_published_even_with_a_selection(
    tmp_path: Path,
) -> None:
    search = new_search(tmp_path)
    outcome = replace(reference_outcome(search), interrupted=True)
    with pytest.raises(ReferenciasError) as error:
        publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_only_a_main_experiment_label_is_evaluated(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    main = search.setup.protocol.model_copy(update={"purpose": "main_experiment"})
    other = Search(replace(search.setup, protocol=main), search.candidates, search.journal)
    folder = publish_label(tmp_path / "datos", other.setup, reference_outcome(other), now=MOMENT)
    assert read_label(folder).label.evidence_status == "evaluated"


def test_the_identifiers_come_from_the_search_not_from_the_clock(tmp_path: Path) -> None:
    labels: list[Label] = []
    for name, moment in (("a", MOMENT), ("b", MOMENT + timedelta(hours=1))):
        (tmp_path / name).mkdir()
        search = new_search(tmp_path / name)
        folder = publish_label(tmp_path / "datos", search.setup, reference_outcome(search), moment)
        labels.append(read_label(folder).label)
    first, second = labels
    assert first.label_id == second.label_id
    assert first.search_run_id == second.search_run_id
    assert first.label_id.startswith("label-")
    assert first.search_run_id.startswith("search-")
    assert first.label_id.removeprefix("label-") == first.search_run_id.removeprefix("search-")


def test_the_manifest_records_the_case_and_its_network(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    folder = publish_label(tmp_path / "datos", search.setup, reference_outcome(search), now=MOMENT)
    manifest = read_label(folder).manifest
    case = search.setup.case
    assert case.network is not None
    assert manifest.network_sha256 == case.network.sha256
    assert manifest.case_id == case.case_id


def test_the_coverage_tells_the_budget_apart_from_what_was_used(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    rules = protocol(search_budget=1000)
    candidates = generate_candidates(
        prepare(search.setup.case),
        scenario_id=search.setup.scenario.scenario_id,
        budget=rules.search_budget,
        attempt_limit=rules.sampling_attempt_limit,
        seed=rules.seeds.search[0],
    )
    big = Search(replace(search.setup, protocol=rules), candidates, search.journal)
    folder = publish_label(tmp_path / "datos", big.setup, reference_outcome(big), now=MOMENT)
    coverage = json.loads((folder / COVERAGE_FILE).read_text(encoding="utf-8"))
    assert coverage["budget"] == 1000
    assert coverage["budget_used"] == candidates.budget_used
    assert candidates.budget_used < 1000


def test_the_coverage_of_a_no_reference_says_why(tmp_path: Path) -> None:
    search = new_search(tmp_path)
    outcome = outcome_for(search, search_clean=True, finalists_clean=False)
    folder = publish_label(tmp_path / "datos", search.setup, outcome, now=MOMENT)
    coverage = json.loads((folder / COVERAGE_FILE).read_text(encoding="utf-8"))
    assert coverage["search"] == {"evaluated": 1, "eligible": 1, "ineligible": {}}
    assert coverage["finalists"] == {
        "evaluated": 1,
        "eligible": 0,
        "ineligible": {"run_failed": 1},
    }
    assert coverage["simulations"] == len(SEARCH_SEEDS) + len(FINALIST_SEEDS)
    assert coverage["budget"] == search.candidates.budget
    assert coverage["budget_used"] == search.candidates.budget_used


# --- verificar ----------------------------------------------------------------------------------


def published(tmp_path: Path) -> Path:
    search = new_search(tmp_path)
    return publish_label(tmp_path / "datos", search.setup, reference_outcome(search), now=MOMENT)


def test_a_changed_label_is_detected(tmp_path: Path) -> None:
    folder = published(tmp_path)
    path = folder / LABEL_FILE
    path.chmod(stat.S_IWRITE)
    path.write_text(path.read_text(encoding="utf-8").replace("reference", "no_reference", 1))
    with pytest.raises(TrazabilidadError) as error:
        read_label(folder)
    assert error.value.code == ErrorCode.HASH_MISMATCH


def test_an_extra_file_is_detected(tmp_path: Path) -> None:
    folder = published(tmp_path)
    (folder / "NOTAS.txt").write_text("x", encoding="utf-8")
    with pytest.raises(TrazabilidadError) as error:
        read_label(folder)
    assert error.value.code == ErrorCode.HASH_MISMATCH


def test_a_label_that_contradicts_its_manifest_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    label = json.loads((folder / LABEL_FILE).read_text(encoding="utf-8"))
    label["label_id"] = "label-otra"
    new_bytes = (json.dumps(label, indent=2) + "\n").encode("utf-8")
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][LABEL_FILE] = sha256_bytes(new_bytes)
    (folder / LABEL_FILE).chmod(stat.S_IWRITE)
    (folder / LABEL_FILE).write_bytes(new_bytes)
    tamper(manifest_path, manifest)
    with pytest.raises(TrazabilidadError) as error:
        read_label(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label_id", "label-otra"),
        ("scenario_id", "OTRO"),
        ("case_version", "9.9.9"),
        ("status", "no_reference"),
        ("search_run_id", "search-otra"),
        ("protocol_id", "OTRO"),
        ("evidence_status", "evaluated"),
    ],
)
def test_a_manifest_that_contradicts_its_label_is_refused(
    tmp_path: Path, field: str, value: str
) -> None:
    folder = published(tmp_path)
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    tamper(manifest_path, manifest)
    with pytest.raises(TrazabilidadError) as error:
        read_label(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_a_manifest_that_lists_only_the_label_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    for name in (TRACE_FILE, COVERAGE_FILE):
        (folder / name).chmod(stat.S_IWRITE)
        (folder / name).unlink()
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {LABEL_FILE: manifest["files"][LABEL_FILE]}
    tamper(manifest_path, manifest)
    with pytest.raises(TrazabilidadError) as error:
        read_label(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def label_statuses(workspace: Path) -> list[str]:
    return [item.status for item in verify_workspace(workspace).items if item.family == "labels"]


def test_the_workspace_check_reports_labels(tmp_path: Path) -> None:
    folder = published(tmp_path)
    workspace = tmp_path / "datos"
    assert label_statuses(workspace) == ["intact"]
    (folder / LABEL_FILE).chmod(stat.S_IWRITE)
    (folder / LABEL_FILE).write_text("{}", encoding="utf-8")
    assert label_statuses(workspace) == ["altered"]
