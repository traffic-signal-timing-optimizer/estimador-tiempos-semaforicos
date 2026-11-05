"""Bitácora de la búsqueda y entradas de ``run_search`` (DEV14 F2): todo se rechaza antes de
correr SUMO. Datos sintéticos: red de demostración (``search_tools``).
"""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from search_tools import SUMO_VERSION, Search, search_in
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.referencias import evaluation
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.evaluation import (
    JOURNAL_VERSION,
    SearchSetup,
    free_memory_gate,
    identity_digest,
    run_search,
    search_identity,
)
from semaforo.referencias.selection import SeedOutcome
from semaforo.simulacion.demand_inputs import VehicleTypes


def fake_binary() -> Path:
    return Path("sumo")


def fake_version(_binary: Path) -> str:
    return SUMO_VERSION


@pytest.fixture(autouse=True)
def without_sumo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Estas pruebas no corren SUMO: la versión se fija a mano."""
    monkeypatch.setattr(evaluation, "find_sumo", fake_binary)
    monkeypatch.setattr(evaluation, "sumo_version", fake_version)


@pytest.fixture
def search(tmp_path: Path) -> Search:
    return search_in(tmp_path)


def header(search: Search) -> dict[str, Any]:
    identity = search_identity(search.setup, search.candidates, SUMO_VERSION)
    return {"type": "header", "identity": identity}


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
    identity = search_identity(search.setup, search.candidates, SUMO_VERSION)
    assert identity["scenario_id"] == search.setup.scenario.scenario_id
    assert identity["seeds_search"] == [101, 102]
    assert identity["seeds_finalists"] == [201, 202]
    assert "seeds_final" not in identity
    assert len(str(identity["candidates_sha256"])) == 64


def test_the_identity_changes_with_the_candidates_or_the_protocol(search: Search) -> None:
    base = search_identity(search.setup, search.candidates, SUMO_VERSION)
    fewer = replace(search.candidates, candidates=search.candidates.candidates[:-1])
    assert search_identity(search.setup, fewer, SUMO_VERSION) != base
    other = replace(
        search.setup, protocol=search.setup.protocol.model_copy(update={"tie_epsilon_s": 1.0})
    )
    assert search_identity(other, search.candidates, SUMO_VERSION) != base


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


# --- la identidad cubre el contenido de los insumos (auditoría A01) ----------------------------


def inputs_of(identity: dict[str, object]) -> dict[str, object]:
    inputs = identity["inputs"]
    assert isinstance(inputs, dict)
    return cast("dict[str, object]", inputs)


def with_flow(setup: SearchSetup) -> SearchSetup:
    request = setup.scenario.request
    first = request.demand[0].model_copy(update={"flow_vph": request.demand[0].flow_vph + 100})
    changed = request.model_copy(update={"demand": [first, *request.demand[1:]]})
    return replace(setup, scenario=setup.scenario.model_copy(update={"request": changed}))


def with_scenario(**changes: Any) -> Callable[[SearchSetup], SearchSetup]:  # noqa: ANN401
    def change(setup: SearchSetup) -> SearchSetup:
        values = {name: getattr(setup.scenario, name) + delta for name, delta in changes.items()}
        return replace(setup, scenario=setup.scenario.model_copy(update=values))

    return change


def with_routes(setup: SearchSetup) -> SearchSetup:
    routes = {**setup.routes.routes, "N_S": [*setup.routes.routes["N_S"], "extra"]}
    return replace(setup, routes=setup.routes.model_copy(update={"routes": routes}))


def with_vehicle_types(setup: SearchSetup) -> SearchSetup:
    data = setup.vehicle_types.model_dump(mode="json")
    data["types"]["car"]["attributes"]["length"] = 6.5
    return replace(setup, vehicle_types=VehicleTypes.model_validate(data))


def with_case(setup: SearchSetup) -> SearchSetup:
    return replace(setup, case=setup.case.model_copy(update={"description": "otra descripción"}))


def with_network(setup: SearchSetup) -> SearchSetup:
    assert setup.case.network is not None
    network = setup.case.network.model_copy(update={"sha256": "0" * 64})
    return replace(setup, case=setup.case.model_copy(update={"network": network}))


def with_queue_threshold(setup: SearchSetup) -> SearchSetup:
    protocol = setup.protocol.model_copy(update={"queue_speed_threshold_mps": 0.2})
    return replace(setup, protocol=protocol)


def with_zone(setup: SearchSetup) -> SearchSetup:
    protocol = setup.protocol.model_copy(update={"zone_lane_ids": ["demo_N_0"]})
    return replace(setup, protocol=protocol)


CHANGES: list[tuple[str, Callable[[SearchSetup], SearchSetup], set[str]]] = [
    ("flujo-de-un-movimiento", with_flow, {"scenario_sha256"}),
    ("semilla-de-llegadas", with_scenario(demand_seed=1), {"scenario_sha256"}),
    ("calentamiento", with_scenario(warmup_s=10.0), {"scenario_sha256"}),
    ("medicion", with_scenario(measure_s=10.0), {"scenario_sha256"}),
    ("vaciado", with_scenario(drain_max_s=10.0), {"scenario_sha256"}),
    ("rutas", with_routes, {"routes_sha256"}),
    ("tipos-de-vehiculo", with_vehicle_types, {"vehicle_types_sha256"}),
    ("caso", with_case, {"case_sha256"}),
    ("red", with_network, {"case_sha256", "network_sha256"}),
    ("umbral-de-cola", with_queue_threshold, {"protocol_sha256"}),
    ("zona-de-medicion", with_zone, {"protocol_sha256"}),
]


@pytest.mark.parametrize(
    ("change", "keys"), [(c, k) for _, c, k in CHANGES], ids=[name for name, _, _ in CHANGES]
)
def test_changing_an_input_changes_the_identity_in_its_own_fingerprint(
    search: Search, change: Callable[[SearchSetup], SearchSetup], keys: set[str]
) -> None:
    base = search_identity(search.setup, search.candidates, SUMO_VERSION)
    changed = search_identity(change(search.setup), search.candidates, SUMO_VERSION)
    assert changed != base
    assert identity_digest(changed) != identity_digest(base)
    before, after = inputs_of(base), inputs_of(changed)
    assert {name for name in before if before[name] != after[name]} == keys


def test_another_version_of_sumo_changes_the_identity(search: Search) -> None:
    base = search_identity(search.setup, search.candidates, "1.27.1")
    other = search_identity(search.setup, search.candidates, "1.28.0")
    assert other != base
    assert other["inputs"] != base["inputs"]


def test_the_same_inputs_give_the_same_identity_and_full_fingerprints(search: Search) -> None:
    first = search_identity(search.setup, search.candidates, SUMO_VERSION)
    second = search_identity(search.setup, search.candidates, SUMO_VERSION)
    assert first == second
    assert identity_digest(first) == identity_digest(second)
    inputs = inputs_of(first)
    for name in (
        "case_sha256",
        "network_sha256",
        "scenario_sha256",
        "routes_sha256",
        "vehicle_types_sha256",
        "protocol_sha256",
    ):
        assert len(str(inputs[name])) == 64
    assert inputs["sumo_version"] == SUMO_VERSION
    assert first["journal_version"] == JOURNAL_VERSION


def test_a_journal_cannot_be_reused_after_the_demand_changes(search: Search) -> None:
    # La auditoría cambió un flujo conservando el identificador del escenario: se aceptaba.
    write(search, header(search))
    changed = with_flow(search.setup)
    with pytest.raises(ReferenciasError) as caught:
        run_search(changed, search.candidates, search.journal)
    assert caught.value.field == "journal"
    assert "otra búsqueda" in caught.value.message
    assert not search.setup.runs_root.exists()


def test_a_journal_cannot_be_reused_after_the_measurement_changes(search: Search) -> None:
    write(search, header(search))
    changed = with_queue_threshold(search.setup)
    with pytest.raises(ReferenciasError) as caught:
        run_search(changed, search.candidates, search.journal)
    assert "otra búsqueda" in caught.value.message
    assert not search.setup.runs_root.exists()


def test_a_journal_of_an_older_version_is_rejected_with_a_clear_message(search: Search) -> None:
    old = {key: value for key, value in header(search)["identity"].items() if key != "inputs"} | {
        "journal_version": "1.0.0"
    }
    write(search, {"type": "header", "identity": old})
    message = rejected(search).message
    assert "versión anterior (1.0.0)" in message
    assert "huella de sus insumos" in message


def test_a_journal_without_a_version_is_rejected_as_an_older_one(search: Search) -> None:
    old = {k: v for k, v in header(search)["identity"].items() if k != "journal_version"}
    write(search, {"type": "header", "identity": old})
    assert "versión anterior" in rejected(search).message
