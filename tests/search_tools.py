"""Ayudas de prueba para la búsqueda de referencias de DEV14 (red de demostración).

4 candidatos (el plan vigente y 3 de la muestra), 2 semillas de búsqueda y 2 finalistas con 2
semillas: 12 corridas por búsqueda completa. Datos sintéticos.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prepared_inputs import DURATIONS, FIXTURES, request_for
from semaforo.caso.network_map import build_network_map
from semaforo.dominio.feasibility import prepare
from semaforo.dominio.protocol import Protocol, parse_protocol
from semaforo.referencias.evaluation import SearchOutcome, SearchSetup, run_search
from semaforo.referencias.search import CandidateSet, generate_candidates

SEARCH_SEEDS = [101, 102]
FINALIST_SEEDS = [201, 202]
FINAL_SEEDS = [301, 302]


def protocol(**changes: object) -> Protocol:
    data: dict[str, Any] = json.loads((FIXTURES / "protocol.json").read_text(encoding="utf-8"))
    data.update(
        search_budget=3,
        sampling_attempt_limit=100,
        finalist_count=2,
        tie_epsilon_s=0.5,
        seeds={"search": SEARCH_SEEDS, "finalists": FINALIST_SEEDS, "final": FINAL_SEEDS},
    )
    data.update(changes)
    return parse_protocol(data)


@dataclass(frozen=True)
class Search:
    setup: SearchSetup
    candidates: CandidateSet
    journal: Path


def search_in(
    root: Path, scenario_change: Callable[[dict[str, Any]], None] | None = None
) -> Search:
    request = request_for(root, scenario_change=scenario_change)
    case = request.case
    rules = protocol()
    setup = SearchSetup(
        case=case,
        case_dir=request.case_dir,
        network_map=build_network_map(request.case_dir / "demo.net.xml", case),
        scenario=request.scenario,
        routes=request.routes,
        vehicle_types=request.vehicle_types,
        protocol=rules,
        programs_root=root / "programas",
        inputs_root=root / "entradas",
        runs_root=root / "ejecuciones",
        sumo_options={},
    )
    candidates = generate_candidates(
        prepare(case),
        scenario_id=request.scenario.scenario_id,
        budget=rules.search_budget,
        attempt_limit=rules.sampling_attempt_limit,
        seed=rules.seeds.search[0],
        current_plan=DURATIONS,
    )
    return Search(setup, candidates, root / "busqueda" / "bitacora.jsonl")


def run(search: Search, **options: Any) -> SearchOutcome:  # noqa: ANN401
    return run_search(search.setup, search.candidates, search.journal, workers=2, **options)


def run_folders(search: Search) -> int:
    root = search.setup.runs_root
    return len(list(root.iterdir())) if root.exists() else 0


def journal_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
