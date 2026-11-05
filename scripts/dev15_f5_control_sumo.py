"""DEV15 F5: control en SUMO del plan de Webster de ESC-SINT-001 (saturación 1 500).

Comprueba que el plan de Webster, cuando aplica, **corre** en SUMO: lo compila, prepara las
entradas y simula con 3 semillas, y mide cada corrida con el protocolo del piloto de DEV14. Para
dar contexto pone al lado lo que midió el piloto con el plan vigente y esas mismas semillas.

**No es la comparación de DEV20**: tres semillas no alcanzan para decir qué plan es mejor, la
saturación de 1 500 es provisional (DEC08) y la demanda es un supuesto del equipo.

Escribe todo en ``--salida`` (programa, entradas, corridas y ``control.json``); de ``datos/`` solo
lee. Unas 3 corridas de medio minuto cada una, una por vez.

Uso, desde la carpeta raíz del proyecto:

    .venv\\Scripts\\python.exe scripts\\dev15_f5_control_sumo.py --salida D:\\dev15-f5-sumo
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semaforo.caso.case_validation import read_case  # noqa: E402
from semaforo.caso.network_map import build_network_map  # noqa: E402
from semaforo.dominio.adjust_order import parse_adjust_order  # noqa: E402
from semaforo.dominio.feasibility import prepare  # noqa: E402
from semaforo.dominio.protocol import parse_protocol  # noqa: E402
from semaforo.evaluacion.run_metrics import evaluate_run  # noqa: E402
from semaforo.referencias.baselines import read_parameters  # noqa: E402
from semaforo.referencias.comparators import compute_comparators  # noqa: E402
from semaforo.referencias.selection import failed_seed, seed_outcome  # noqa: E402
from semaforo.simulacion.compiler import compile_program, publish_program  # noqa: E402
from semaforo.simulacion.demand_inputs import (  # noqa: E402
    read_routes,
    read_scenario,
    read_vehicle_types,
)
from semaforo.simulacion.prepare import PreparationRequest, publish_inputs  # noqa: E402
from semaforo.simulacion.run_inputs import run_inputs  # noqa: E402
from semaforo.simulacion.runner import find_sumo, sumo_version  # noqa: E402

CASE = "caso-001"
SCENARIO = "ESC-SINT-001"
PILOT_PROGRAM = "20261031T041338Z_63437585"
PILOT_PROTOCOL = "borrador-dev14-piloto.json"
PILOT_JOURNAL = Path("evidencia") / "piloto-dev14-v1" / "bitacora.jsonl"
PILOT_TRACE = Path("derivados") / "referencias" / CASE / "20261103T163554Z_decb039e" / "traza.json"
PARAMETERS = ROOT / "configs" / "webster" / "parametros-v2.json"
SATURATION = 1500.0
SEEDS = (1001, 1002, 1003)
SUMO_OPTIONS = {"lateral-resolution": 0.8, "collision.check-junctions": True}


def pilot_current_plan(journal: Path, trace: Path) -> dict[int, dict[str, Any]]:
    """Lo que midió el piloto con el plan vigente en la etapa de búsqueda, por semilla."""
    if not journal.exists() or not trace.exists():
        return {}
    candidates = json.loads(trace.read_text(encoding="utf-8"))["candidates"]["candidates"]
    current = {c["candidate_id"] for c in candidates if c.get("origin") == "current_plan"}
    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    return {
        r["outcome"]["seed"]: r["outcome"]
        for r in records
        if r.get("type") == "seed" and r.get("stage") == "search" and r["candidate_id"] in current
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", maxsplit=1)[0])
    parser.add_argument("--salida", type=Path, required=True, help="carpeta nueva del control")
    parser.add_argument("--datos", type=Path, default=ROOT / "datos", help="carpeta de insumos")
    arguments = parser.parse_args()

    data_root = arguments.datos.resolve()
    output: Path = arguments.salida
    resolved = output.resolve()
    if resolved == data_root or data_root in resolved.parents:
        raise SystemExit("--salida no puede estar dentro de --datos")
    if output.exists():
        raise SystemExit(f"{output} ya existe: use otra --salida")
    output.mkdir(parents=True)

    case_dir = data_root / "casos" / CASE
    scenarios = data_root / "escenarios" / CASE
    case = read_case(case_dir / "case.json")
    order = parse_adjust_order(
        json.loads((case_dir / "orden_de_ajuste.json").read_text(encoding="utf-8"))
    )
    prepared = prepare(case, order)
    scenario = read_scenario(scenarios / f"{SCENARIO}.json", case)
    parameters = read_parameters(PARAMETERS, case).model_copy(
        update={"saturation_flow_veh_h_lane": SATURATION}
    )
    program_folder = data_root / "derivados" / "programas" / CASE / PILOT_PROGRAM
    webster = compute_comparators(prepared, scenario, parameters, program_folder).webster
    if webster.status != "applicable" or webster.durations_s is None:
        raise SystemExit(f"Webster no aplica con {SATURATION:g}: no hay plan que controlar")
    protocol = parse_protocol(
        json.loads(
            (data_root / "derivados" / "protocolos" / CASE / PILOT_PROTOCOL).read_text("utf-8")
        )
    )

    binary = find_sumo()
    program = compile_program(
        case, build_network_map(case_dir / "osm.net.xml.gz", case), webster.durations_s
    )
    program_dir = publish_program(output / "programas", case, program)
    pilot = pilot_current_plan(data_root / PILOT_JOURNAL, data_root / PILOT_TRACE)
    rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        request = PreparationRequest(
            case=case,
            case_dir=case_dir,
            scenario=scenario,
            routes=read_routes(scenarios / "rutas.json"),
            vehicle_types=read_vehicle_types(scenarios / "tipos.json"),
            program_dir=program_dir,
            sumo_seed=seed,
            sumo_options=SUMO_OPTIONS,
        )
        inputs = publish_inputs(output / "entradas", request)
        result = run_inputs(inputs, output / "ejecuciones", sumo=binary)
        manifest = result.manifest
        if manifest.status != "succeeded":
            outcome = failed_seed(
                seed, manifest.run_id, manifest.status, "run_failed", "la corrida no terminó bien"
            )
        else:
            metrics = evaluate_run(
                inputs, output / "ejecuciones", manifest.run_id, case, protocol, scenario=scenario
            )
            outcome = seed_outcome(seed, metrics)
        row = {"webster": outcome.to_json(), "current_plan_in_pilot": pilot.get(seed)}
        rows.append(row)
        print(
            f"semilla {seed}: {manifest.status}; demora {outcome.mean_delay_s}; "
            f"problemas {list(outcome.problems)}",
            flush=True,
        )

    report = {
        "scenario_id": scenario.scenario_id,
        "demand_origin": scenario.request.origin,
        "saturation_veh_h_lane": SATURATION,
        "parameter_set": parameters.parameter_set,
        "parameter_status": parameters.status,
        "webster_plan_s": dict(webster.durations_s),
        "webster_cycle_s": webster.cycle_s,
        "protocol_id": protocol.protocol_id,
        "sumo": sumo_version(binary),
        "seeds": list(SEEDS),
        "runs": rows,
        "warning": "control de que el plan corre; no es una comparación (DEV20)",
    }
    (output / "control.json").write_bytes(
        (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
