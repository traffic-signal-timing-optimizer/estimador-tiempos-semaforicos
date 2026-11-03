"""Búsqueda de referencias con SUMO real (DEV14 F2, HU08, QA16 y QA18 de integración).

Red de demostración de dos movimientos (``prepared_inputs``): 4 candidatos (el plan vigente y 3 de
la muestra), 2 semillas de búsqueda y 2 finalistas con 2 semillas: 12 corridas por búsqueda.
"""

import json
import shutil
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from semaforo.referencias.evaluation import SearchOutcome, run_search
from semaforo.referencias.label import publish_label, read_label
from semaforo.simulacion.runner import RunLimits

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
