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
from semaforo.evaluacion.cohort import CohortDelay, DelaySummary
from semaforo.evaluacion.metrics import QueueSummary, StopsSummary, ZoneMetrics
from semaforo.evaluacion.run_metrics import RunMetrics
from semaforo.referencias.evaluation import (
    SearchOutcome,
    SearchSetup,
    run_search,
    search_identity,
)
from semaforo.referencias.search import CandidateSet, generate_candidates
from semaforo.referencias.selection import (
    SeedOutcome,
    failed_seed,
    score_candidate,
    seed_outcome,
    select,
)

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


# --- búsquedas terminadas sin SUMO (cifras de las corridas armadas a mano) ---------------------


def new_search(tmp_path: Path) -> Search:
    root = tmp_path / "busqueda"
    root.mkdir()
    return search_in(root)


def clean_metrics(seed: int, delay: float) -> RunMetrics:
    total = DelaySummary.model_construct(status="complete", mean_delay_s=delay)
    zone = ZoneMetrics.model_construct(
        queue=QueueSummary.model_construct(status="complete", mean_vehicles=5.0),
        stops=StopsSummary.model_construct(mean_stops=1.0),
    )
    return RunMetrics.model_construct(
        run_id=f"run-{seed}",
        sumo_seed=seed,
        cohort=CohortDelay.model_construct(total=total),
        zone=zone,
        teleports_total=0,
        collisions=0,
    )


def clean_outcomes(seeds: list[int]) -> list[SeedOutcome]:
    return [seed_outcome(seed, clean_metrics(seed, 100.0)) for seed in seeds]


def broken_outcomes(seeds: list[int]) -> list[SeedOutcome]:
    return [
        failed_seed(seed, None, "run_failed", "run_failed", "la corrida falló") for seed in seeds
    ]


def outcome_for(
    search: Search,
    *,
    search_clean: bool,
    finalists_clean: bool,
    index: int = 0,
    candidate_id: str | None = None,
) -> SearchOutcome:
    """Búsqueda terminada con un solo candidato evaluado (el ``index``): limpio o con todas sus
    corridas fallidas. ``candidate_id`` lo reemplaza por uno que no está entre los candidatos.
    """
    candidate = search.candidates.candidates[index]
    vector = tuple(candidate.ticks.values())
    name = candidate.candidate_id if candidate_id is None else candidate_id
    search_score = score_candidate(
        name,
        vector,
        "search",
        SEARCH_SEEDS,
        clean_outcomes(SEARCH_SEEDS) if search_clean else broken_outcomes(SEARCH_SEEDS),
    )
    finalist_score = score_candidate(
        name,
        vector,
        "finalists",
        FINALIST_SEEDS,
        clean_outcomes(FINALIST_SEEDS) if finalists_clean else broken_outcomes(FINALIST_SEEDS),
    )
    rules = search.setup.protocol
    finalist_scores = (finalist_score,) if search_clean else ()
    selection = select(
        [search_score], list(finalist_scores), rules.finalist_count, rules.tie_epsilon_s
    )
    return SearchOutcome(
        identity=search_identity(search.setup, search.candidates),
        candidates=search.candidates,
        search_scores=(search_score,),
        finalist_scores=finalist_scores,
        selection=selection,
        simulation_count=len(SEARCH_SEEDS) + len(FINALIST_SEEDS),
        interrupted=False,
    )


def reference_outcome(search: Search) -> SearchOutcome:
    return outcome_for(search, search_clean=True, finalists_clean=True)
