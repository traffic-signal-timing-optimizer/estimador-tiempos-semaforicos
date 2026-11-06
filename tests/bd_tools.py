"""Ayudas de las pruebas de la base de datos (DEV31 F3).

``loadable_workspace`` arma un ``datos/`` sintético y completo sobre la red de demostración:
caso, programa derivado, escenario, protocolo, cuatro corridas reales de SUMO (dos semillas de
búsqueda y dos de finalistas) con sus métricas publicadas, y una búsqueda con su etiqueta que usa
esas corridas. Es lo mismo que publica el proyecto, en las mismas carpetas.
"""

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prepared_inputs import DURATIONS, MOMENT, request_for
from search_tools import FINALIST_SEEDS, SEARCH_SEEDS, SUMO_VERSION, protocol
from semaforo.bd.carga.insercion import Catalog, write_rows
from semaforo.bd.conexion import ADMIN, CARGA, LECTURA, Connection, connect
from semaforo.caso.network_map import build_network_map
from semaforo.dominio.feasibility import prepare
from semaforo.evaluacion.published_metrics import publish_run_metrics
from semaforo.evaluacion.run_metrics import RunMetrics, evaluate_run
from semaforo.referencias.evaluation import SearchOutcome, SearchSetup, search_identity
from semaforo.referencias.label import publish_label
from semaforo.referencias.search import generate_candidates
from semaforo.referencias.selection import score_candidate, seed_outcome, select
from semaforo.simulacion.prepare import publish_inputs
from semaforo.simulacion.run_inputs import run_inputs
from semaforo.trazabilidad.fs import make_read_only
from workspace_tools import build_workspace

__all__ = [
    "Loadable",
    "copy_workspace",
    "insert",
    "loadable_workspace",
    "rows_of",
    "scalar",
]


@dataclass(frozen=True)
class Loadable:
    """El espacio de trabajo armado y lo que tiene."""

    workspace: Path
    case_id: str
    scenario_id: str
    protocol_id: str
    runs: dict[int, str]
    label_folder: str
    vehicles_per_run: int


def loadable_workspace(tmp_path: Path, sumo: Path) -> Loadable:
    """El ``datos/`` completo descrito arriba (tarda unos segundos: corre SUMO cuatro veces)."""
    workspace, _ = build_workspace(tmp_path)
    request = request_for(tmp_path)
    case, scenario = request.case, request.scenario
    rules = protocol()
    scenarios = workspace / "escenarios" / case.case_id
    scenarios.mkdir(parents=True)
    (scenarios / f"{scenario.scenario_id}.json").write_text(
        scenario.model_dump_json(indent=2), encoding="utf-8"
    )
    protocols = workspace / "derivados" / "protocolos" / case.case_id
    protocols.mkdir(parents=True)
    (protocols / "protocolo.json").write_text(rules.model_dump_json(indent=2), encoding="utf-8")
    runs_root = workspace / "ejecuciones"
    runs: dict[int, str] = {}
    metrics: dict[int, RunMetrics] = {}
    vehicles = 0
    for seed in [*SEARCH_SEEDS, *FINALIST_SEEDS]:
        seeded = request_for(tmp_path, sumo_seed=seed)
        inputs = publish_inputs(workspace / "derivados" / "entradas", seeded, MOMENT)
        run = run_inputs(inputs, runs_root, sumo=sumo)
        run_id = run.manifest.run_id
        measured = evaluate_run(inputs, runs_root, run_id, case, rules, scenario=scenario)
        publish_run_metrics(workspace, measured)
        runs[seed] = run_id
        metrics[seed] = measured
        manifest = json.loads((inputs / "manifiesto.json").read_text(encoding="utf-8"))
        vehicles = int(manifest["vehicles"]["total"])
    setup = SearchSetup(
        case=case,
        case_dir=request.case_dir,
        network_map=build_network_map(request.case_dir / "demo.net.xml", case),
        scenario=scenario,
        routes=request.routes,
        vehicle_types=request.vehicle_types,
        protocol=rules,
        programs_root=tmp_path / "programas",
        inputs_root=workspace / "derivados" / "entradas",
        runs_root=runs_root,
        sumo_options={},
    )
    candidates = generate_candidates(
        prepare(case),
        scenario_id=scenario.scenario_id,
        budget=rules.search_budget,
        attempt_limit=rules.sampling_attempt_limit,
        seed=rules.seeds.search[0],
        current_plan=DURATIONS,
    )
    current = next(c for c in candidates.candidates if c.origin == "current_plan")
    vector = tuple(current.ticks.values())
    search_score = score_candidate(
        current.candidate_id,
        vector,
        "search",
        SEARCH_SEEDS,
        [seed_outcome(seed, metrics[seed]) for seed in SEARCH_SEEDS],
    )
    finalist_score = score_candidate(
        current.candidate_id,
        vector,
        "finalists",
        FINALIST_SEEDS,
        [seed_outcome(seed, metrics[seed]) for seed in FINALIST_SEEDS],
    )
    selection = select([search_score], [finalist_score], rules.finalist_count, rules.tie_epsilon_s)
    outcome = SearchOutcome(
        identity=search_identity(setup, candidates, SUMO_VERSION),
        candidates=candidates,
        search_scores=(search_score,),
        finalist_scores=(finalist_score,),
        selection=selection,
        simulation_count=len(runs),
        interrupted=False,
    )
    label = publish_label(workspace, setup, outcome, MOMENT)
    return Loadable(
        workspace=workspace,
        case_id=case.case_id,
        scenario_id=scenario.scenario_id,
        protocol_id=rules.protocol_id,
        runs=runs,
        label_folder=label.relative_to(workspace).as_posix(),
        vehicles_per_run=vehicles,
    )


def copy_workspace(source: Path, target: Path) -> Path:
    """Una copia de ``source`` para alterarla sin tocar la original (archivos de solo lectura)."""
    shutil.copytree(source, target, copy_function=shutil.copyfile)
    for path in target.rglob("*"):
        if path.is_file():
            path.chmod(0o666)
    return target


def scalar(database: str, query: str, params: tuple[Any, ...] = (), role: str = CARGA) -> object:
    """El primer valor de ``query`` en ``database``, con el usuario ``role``."""
    with connect(role, database=database) as connection:
        row = connection.execute(query.encode(), params).fetchone()
    return None if row is None else row[0]


def rows_of(database: str, query: str, role: str = LECTURA) -> list[tuple[Any, ...]]:
    """Las filas de ``query`` en ``database``, con el usuario ``role`` (lectura por defecto)."""
    with connect(role, database=database) as connection:
        return [tuple(row) for row in connection.execute(query.encode())]


def insert(
    database: str,
    rows: dict[str, list[dict[str, object]]],
    *,
    role: str = ADMIN,
    then: Callable[[Connection], None] | None = None,
) -> None:
    """Escribe ``rows`` (por tabla) en una transacción, con una carga de prueba como origen."""
    with connect(role, database=database, autocommit=True) as connection:
        catalog = Catalog.load(connection)
        with connection.transaction():
            connection.execute(
                "INSERT INTO control.cargas (carga_id, inicio, estado, comando, version_paquete, "
                "version_postgres, version_esquema) VALUES ('prueba', now(), 'running', "
                "'{}'::jsonb, 'prueba', 'prueba', 'prueba') ON CONFLICT DO NOTHING"
            )
            result = write_rows(connection, catalog, rows, "prueba")
            assert not result.conflicts, result.conflicts
            if then is not None:
                then(connection)


def read_only(path: Path) -> None:
    make_read_only(path)
