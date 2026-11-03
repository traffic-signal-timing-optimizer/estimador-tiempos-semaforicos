"""Bitácora de la búsqueda y entradas de ``run_search`` (DEV14 F2): todo se rechaza antes de
correr SUMO. Datos sintéticos: red de demostración (``search_tools``).
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from search_tools import Search, search_in
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.referencias import evaluation
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.evaluation import (
    free_memory_gate,
    run_search,
    search_identity,
)
from semaforo.referencias.selection import SeedOutcome


@pytest.fixture
def search(tmp_path: Path) -> Search:
    return search_in(tmp_path)


def header(search: Search) -> dict[str, Any]:
    return {"type": "header", "identity": search_identity(search.setup, search.candidates)}


def write(search: Search, *records: dict[str, Any], tail: bytes = b"") -> None:
    search.journal.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False).encode("utf-8") for record in records]
    search.journal.write_bytes(b"".join(line + bytes([10]) for line in lines) + tail)


def outcome(seed: int = 101, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    data = SeedOutcome(101, "run-1", "succeeded", 100.0, 5.0, 1.0, 0, 0, ()).to_json()
    data["seed"] = seed
    data.update(changes)
    return data


def seed_record(search: Search, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    record: dict[str, Any] = {
        "type": "seed",
        "stage": "search",
        "candidate_id": search.candidates.candidates[0].candidate_id,
        "seed": 101,
        "inputs_dir": "x",
        "outcome": outcome(),
    }
    record.update(changes)
    return record


def rejected(search: Search) -> ReferenciasError:
    with pytest.raises(ReferenciasError) as caught:
        run_search(search.setup, search.candidates, search.journal)
    assert caught.value.field == "journal"
    assert not search.setup.runs_root.exists()
    return caught.value


def test_a_new_search_writes_its_identity_first(search: Search) -> None:
    identity = search_identity(search.setup, search.candidates)
    assert identity["scenario_id"] == search.setup.scenario.scenario_id
    assert identity["seeds_search"] == [101, 102]
    assert identity["seeds_finalists"] == [201, 202]
    assert "seeds_final" not in identity
    assert len(str(identity["candidates_sha256"])) == 64


def test_the_identity_changes_with_the_candidates_or_the_protocol(search: Search) -> None:
    base = search_identity(search.setup, search.candidates)
    fewer = replace(search.candidates, candidates=search.candidates.candidates[:-1])
    assert search_identity(search.setup, fewer) != base
    other = replace(
        search.setup, protocol=search.setup.protocol.model_copy(update={"tie_epsilon_s": 1.0})
    )
    assert search_identity(other, search.candidates) != base


def test_a_journal_without_identity_is_rejected(search: Search) -> None:
    write(search, seed_record(search))
    assert "identidad" in rejected(search).message


def test_an_empty_journal_is_rejected(search: Search) -> None:
    write(search)
    rejected(search)


def test_a_journal_of_another_search_is_rejected(search: Search) -> None:
    record = header(search)
    record["identity"] = {**record["identity"], "scenario_id": "OTRO"}
    write(search, record)
    assert "otra búsqueda" in rejected(search).message


def test_a_broken_line_in_the_middle_is_rejected(search: Search) -> None:
    write(search, header(search), tail=b"{no es json" + bytes([10]))
    assert "línea 2" in rejected(search).message


@pytest.mark.parametrize("folder", ["../fuera", "/absoluta", "C:/absoluta", "a/../../b"])
def test_a_program_outside_its_folder_is_rejected(search: Search, folder: str) -> None:
    record = {"type": "program", "candidate_id": "cand-x", "program_dir": folder}
    write(search, header(search), record)
    assert "fuera" in rejected(search).message


def test_inputs_outside_their_folder_are_rejected(search: Search) -> None:
    record = {
        "type": "inputs",
        "stage": "search",
        "candidate_id": "cand-x",
        "seed": 101,
        "inputs_dir": "../../x",
    }
    write(search, header(search), record)
    assert "fuera" in rejected(search).message


def test_inputs_recorded_twice_are_rejected(search: Search) -> None:
    record = {
        "type": "inputs",
        "stage": "search",
        "candidate_id": "cand-x",
        "seed": 101,
        "inputs_dir": "ESC/x",
    }
    write(search, header(search), record, record)
    assert "dos veces" in rejected(search).message


def test_a_program_that_does_not_exist_is_rejected(search: Search) -> None:
    record = {"type": "program", "candidate_id": "cand-x", "program_dir": "DEMO/no-existe"}
    write(search, header(search), record)
    with pytest.raises(DomainError):
        run_search(search.setup, search.candidates, search.journal)
    assert not search.setup.runs_root.exists()


def test_a_result_recorded_twice_is_rejected(search: Search) -> None:
    write(search, header(search), seed_record(search), seed_record(search))
    assert "dos veces" in rejected(search).message


def test_a_result_of_another_seed_is_rejected(search: Search) -> None:
    write(search, header(search), seed_record(search, outcome=outcome(102)))
    assert "semilla" in rejected(search).message


@pytest.mark.parametrize(
    "changes",
    [
        {"mean_delay_s": "100"},
        {"problems": ["otro"]},
        {"extra": 1},
        {"teleports": 1.5},
    ],
)
def test_a_result_with_the_wrong_shape_is_rejected(search: Search, changes: dict[str, Any]) -> None:
    write(search, header(search), seed_record(search, outcome=outcome(**changes)))
    rejected(search)


@pytest.mark.parametrize(
    "record",
    [
        {"type": "seed", "candidate_id": "cand-x", "seed": 101},
        {"type": "program", "candidate_id": "cand-x"},
        {"type": "header", "identity": {}},
        {"type": "otro"},
        {"type": "seed", "stage": "final", "candidate_id": "c", "seed": 1},
    ],
)
def test_an_incomplete_or_unknown_record_is_rejected(
    search: Search, record: dict[str, Any]
) -> None:
    write(search, header(search), record)
    rejected(search)


def test_a_journal_too_big_is_rejected(search: Search, monkeypatch: pytest.MonkeyPatch) -> None:
    write(search, header(search))
    monkeypatch.setattr(evaluation, "MAX_JOURNAL_BYTES", 10)
    assert "supera" in rejected(search).message


def test_a_journal_that_is_a_folder_is_rejected(search: Search) -> None:
    search.journal.mkdir(parents=True)
    rejected(search)


@pytest.mark.parametrize("workers", [0, -1, True, 2.0])
def test_an_invalid_number_of_workers_is_rejected(search: Search, workers: Any) -> None:  # noqa: ANN401
    with pytest.raises(ReferenciasError) as caught:
        run_search(search.setup, search.candidates, search.journal, workers=workers)
    assert caught.value.field == "workers"
    assert not search.journal.exists()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"scenario_id": "OTRO"}, "escenario"),
        ({"attempt_limit": 99}, "intentos"),
        ({"seed": 7}, "semilla"),
    ],
)
def test_candidates_that_do_not_match_the_protocol_are_rejected(
    search: Search, changes: dict[str, Any], message: str
) -> None:
    candidates = replace(search.candidates, **changes)
    with pytest.raises(ReferenciasError) as caught:
        run_search(search.setup, candidates, search.journal)
    assert caught.value.code == ErrorCode.INPUT_SCHEMA
    assert message in caught.value.message
    assert not search.journal.exists()


def test_a_protocol_with_another_censoring_is_rejected(search: Search) -> None:
    rules = search.setup.protocol.model_copy(update={"censoring_policy": "approved_alternative"})
    with pytest.raises(DomainError) as caught:
        run_search(replace(search.setup, protocol=rules), search.candidates, search.journal)
    assert caught.value.field == "censoring_policy"


def test_the_memory_gate_waits_below_the_minimum() -> None:
    gate = free_memory_gate(1_500, lambda: 1_499)
    assert not gate()
    assert free_memory_gate(1_500, lambda: 1_500)()
    assert free_memory_gate(1_500, lambda: None)()
