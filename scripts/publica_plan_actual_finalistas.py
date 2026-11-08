"""Publica el plan vigente con las semillas de los finalistas (2001 a 2013) en datos/.

Hace lo que hace un finalista, para el plan vigente y sin búsqueda: entradas con la semilla, corrida
de SUMO, métricas con el protocolo del piloto de DEV14 (el mismo de los finalistas) y publicación en
``datos/ejecuciones`` y ``datos/derivados/metricas``. No cambia ninguna corrida ni búsqueda
existente.

Después hay que cargar la base: ``bd cargar --preliminar --sueltas`` (las corridas quedan como
diagnóstico con su protocolo de métricas; el panel las separa por protocolo y semilla).

Uso, desde la carpeta raíz del proyecto (tarda unos 3 minutos):

    .venv\\Scripts\\python.exe scripts\\publica_plan_actual_finalistas.py

Se niega si ya hay entradas de este plan con estas semillas, para no duplicarlas.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semaforo.caso.case_validation import read_case  # noqa: E402
from semaforo.dominio.protocol import Protocol, parse_protocol  # noqa: E402
from semaforo.evaluacion.published_metrics import publish_run_metrics  # noqa: E402
from semaforo.evaluacion.run_metrics import evaluate_run  # noqa: E402
from semaforo.referencias.selection import seed_outcome  # noqa: E402
from semaforo.simulacion.demand_inputs import (  # noqa: E402
    read_routes,
    read_scenario,
    read_vehicle_types,
)
from semaforo.simulacion.prepare import PreparationRequest, publish_inputs  # noqa: E402
from semaforo.simulacion.run_inputs import run_inputs  # noqa: E402
from semaforo.simulacion.runner import find_sumo  # noqa: E402

DATOS = ROOT / "datos"
CASE = "caso-001"
SCENARIO = "ESC-SINT-001"
PROGRAM = DATOS / "derivados" / "programas" / CASE / "20261031T041338Z_63437585"
SUMO_OPTIONS = {"lateral-resolution": 0.8, "collision.check-junctions": True}
SEEDS = list(range(2001, 2014))
PROGRAM_SHA256 = "63437585947e06d035833d8e7f915a335a7309ade21b0e2febb6f5cbcce2164a"


def protocol() -> Protocol:
    """El protocolo del piloto de DEV14, el mismo con que se midieron los finalistas."""
    base = json.loads(
        (DATOS / "derivados" / "protocolos" / CASE / "borrador-dev19-aproximacion.json").read_text(
            encoding="utf-8"
        )
    )
    data = dict(base)
    data["metric_definition"] = base["metric_definition"].replace(
        "(DEV19)", "(DEV14 F4, piloto; misma métrica que DEV19)", 1
    )
    data.update(
        protocol_id="CASO001_DEV14_PILOTO",
        search_budget=20,
        sampling_attempt_limit=2000,
        finalist_count=3,
        tie_epsilon_s=2.0,
        seeds={
            "search": [1001, 1002, 1003],
            "finalists": SEEDS,
            "final": list(range(3001, 3014)),
        },
    )
    return parse_protocol(data)


def already_published() -> list[str]:
    """Las entradas que ya usan este plan con estas semillas: si existen, no se duplica nada.

    Se mira el programa (no solo la semilla): los finalistas de la búsqueda también usan semillas
    2001 a 2013, pero con otros planes.
    """
    found = []
    for path in (DATOS / "derivados" / "entradas" / SCENARIO).glob("*/manifiesto.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        same_plan = manifest["program"]["sha256"] == PROGRAM_SHA256
        if same_plan and manifest["seeds"]["sumo_seed"] in SEEDS:
            found.append(path.parent.name)
    return found


def main() -> int:
    existing = already_published()
    if existing:
        print(f"ALTO: ya hay {len(existing)} entradas de este plan con estas semillas")
        return 1
    case_dir = DATOS / "casos" / CASE
    scenarios = DATOS / "escenarios" / CASE
    case = read_case(case_dir / "case.json")
    scenario = read_scenario(scenarios / f"{SCENARIO}.json", case)
    routes = read_routes(scenarios / "rutas.json")
    vehicles = read_vehicle_types(scenarios / "tipos.json")
    rules = protocol()
    binary = find_sumo()
    results = []
    for seed in SEEDS:
        request = PreparationRequest(
            case=case,
            case_dir=case_dir,
            scenario=scenario,
            routes=routes,
            vehicle_types=vehicles,
            program_dir=PROGRAM,
            sumo_seed=seed,
            sumo_options=SUMO_OPTIONS,
        )
        inputs = publish_inputs(DATOS / "derivados" / "entradas", request)
        manifest = run_inputs(inputs, DATOS / "ejecuciones", sumo=binary).manifest
        row = {"seed": seed, "run_id": manifest.run_id, "status": manifest.status}
        if manifest.status == "succeeded":
            metrics = evaluate_run(
                inputs, DATOS / "ejecuciones", manifest.run_id, case, rules, scenario=scenario
            )
            publish_run_metrics(DATOS, metrics)
            outcome = seed_outcome(seed, metrics)
            row.update(
                delay_s=outcome.mean_delay_s,
                queue_veh=outcome.mean_queue_veh,
                teleports=outcome.teleports,
                collisions=outcome.collisions,
                problems=list(outcome.problems),
            )
        print(json.dumps(row, ensure_ascii=False), flush=True)
        results.append(row)
    print(f"publicadas {len(results)} corridas; cargar con: bd cargar --preliminar --sueltas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
