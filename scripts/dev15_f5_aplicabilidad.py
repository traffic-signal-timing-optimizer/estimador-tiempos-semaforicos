"""DEV15 F5: aplicabilidad de Webster y plan vigente en el caso real, con sensibilidad.

Para ``ESC-SINT-001`` y para un conjunto de escenarios sintéticos armado a partir de él calcula el
plan vigente (si cumple las reglas del caso) y el plan de Webster con la saturación de los
parámetros, y repite Webster con cada saturación de la lista de sensibilidad. Escribe todo en
``--salida`` (``aplicabilidad.json`` y ``aplicabilidad.md``); el conjunto de escenarios y sus
comparadores quedan en ``--salida/datos``. **No escribe en ``datos/``**, salvo con
``--publicar``: entonces publica también los comparadores de ``ESC-SINT-001`` en
``datos/derivados/comparadores/caso-001/`` (carpeta nueva, de solo lectura).

El conjunto sintético es un supuesto del equipo, no un aforo: tres familias (baja, media y alta)
que escalan cada flujo de ``ESC-SINT-001`` dentro de un rango, con su misma composición. Los
movimientos sin flujo siguen sin flujo.

Uso, desde la carpeta raíz del proyecto:

    .venv\\Scripts\\python.exe scripts\\dev15_f5_aplicabilidad.py --salida D:\\dev15-f5 [--publicar]

No usa SUMO. Tarda unos segundos.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semaforo.app.scenario_commands import generate_scenario_set  # noqa: E402
from semaforo.caso.case_validation import read_case  # noqa: E402
from semaforo.datos.scenario_set import read_scenario_set  # noqa: E402
from semaforo.dominio.adjust_order import parse_adjust_order  # noqa: E402
from semaforo.dominio.feasibility import PreparedCase, prepare  # noqa: E402
from semaforo.dominio.scenario import Scenario  # noqa: E402
from semaforo.referencias.baselines import WebsterParameters, WebsterPlan, read_parameters  # noqa: E402
from semaforo.referencias.comparators import (  # noqa: E402
    compute_comparators,
    publish_comparators,
    read_comparators,
    saturation_sensitivity,
)
from semaforo.simulacion.demand_inputs import read_scenario  # noqa: E402

CASE = "caso-001"
SCENARIO = "ESC-SINT-001"
PILOT_PROGRAM = "20261031T041338Z_63437585"
PARAMETERS = ROOT / "configs" / "webster" / "parametros-v2.json"
SET_SEED = 2026
# Factores sobre los flujos de ESC-SINT-001 (supuesto del equipo, no observado).
FAMILIES = {"BAJA": (0.55, 0.70), "MEDIA": (0.85, 1.00), "ALTA": (1.00, 1.15)}
VARIANTS = 3


def spec_from(scenario: Scenario) -> dict[str, Any]:
    """La especificación del conjunto sintético: tres familias alrededor de ``scenario``."""
    families = []
    for name, (low, high) in FAMILIES.items():
        families.append(
            {
                "family_id": f"FAM_{name}",
                "variants": VARIANTS,
                "seeds": 1,
                "demand": [
                    {
                        "movement_id": row.movement_id,
                        "flow_vph": {
                            "min": round(row.flow_vph * low),
                            "max": round(row.flow_vph * high),
                        },
                        "composition": None if row.composition is None else dict(row.composition),
                    }
                    for row in scenario.request.demand
                ],
            }
        )
    request = scenario.request
    return {
        "schema_version": "1.0.0",
        "spec_id": "SPEC_CASO001_DEV15_F5",
        "case_id": scenario.case_id,
        "case_version": scenario.case_version,
        "origin": "synthetic",
        "source_ids": ["SUPUESTO_EQUIPO_DEV15_F5"],
        "observation_start": request.observation_start,
        "observation_end": request.observation_end,
        "warmup_s": scenario.warmup_s,
        "measure_s": scenario.measure_s,
        "drain_max_s": scenario.drain_max_s,
        "families": families,
    }


def webster_row(saturation: float, webster: WebsterPlan, variable: list[str]) -> dict[str, Any]:
    path = webster.critical_path
    return {
        "saturation_veh_h_lane": saturation,
        "status": webster.status,
        "y": None if path is None else round(path.y, 6),
        "lost_time_s": None if path is None else path.lost_time_s,
        "webster_cycle_s": None
        if webster.webster_cycle_s is None
        else round(webster.webster_cycle_s, 2),
        "cycle_s": webster.cycle_s,
        "plan": None
        if webster.durations_s is None
        else {slot: webster.durations_s[slot] for slot in variable},
        "violated": list(webster.violated),
        "problems": [
            {"code": problem.code, "subject": problem.subject} for problem in webster.problems
        ],
    }


def scenario_report(
    prepared: PreparedCase,
    scenario: Scenario,
    parameters: WebsterParameters,
    program: Path,
    family: str,
) -> tuple[dict[str, Any], Any]:
    result = compute_comparators(prepared, scenario, parameters, program)
    variable = list(prepared.variable_ids)
    rows = [
        webster_row(row.saturation_veh_h_lane, row.webster, variable)
        for row in saturation_sensitivity(prepared, scenario, parameters)
    ]
    report = {
        "scenario_id": scenario.scenario_id,
        "family": family,
        "demand_origin": scenario.request.origin,
        "total_flow_vph": round(sum(row.flow_vph for row in scenario.request.demand), 1),
        "current_plan": {
            "plan": {slot: result.current.durations_s[slot] for slot in variable},
            "cycle_s": result.current.cycle_s,
            "feasible": result.current.feasible,
            "violated": list(result.current.violated),
        },
        "webster": webster_row(parameters.saturation_flow_veh_h_lane, result.webster, variable),
        "sensitivity": rows,
    }
    return report, result


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "Escrito para: el Product Owner y el equipo técnico (aplicabilidad de Webster en el caso).",
        "",
        "# DEV15 F5: aplicabilidad de Webster y plan vigente",
        "",
        f"- Caso: `{report['case_id']}` {report['case_version']} (origen del caso: "
        f"{report['case_origin']}).",
        f"- Parámetros: `{report['parameter_set']}`, **{report['parameter_status']}** "
        f"(saturación base {report['base_saturation']} veh/h por carril).",
        "- Toda la demanda es **sintética** (supuesto del equipo): ningún resultado es evidencia "
        "de campo.",
        f"- Ciclo admitido por el caso: de {report['cycle_bounds_s'][0]} a "
        f"{report['cycle_bounds_s'][1]} s.",
        "",
        "| Escenario | Familia | Flujo total (veh/h) | Saturación | Y | L (s) | C0 (s) | "
        "Webster | Motivo | Plan (s) | Ciclo (s) |",
        "|---|---|---:|---:|---:|---:|---:|---|---|---|---:|",
    ]
    for item in report["scenarios"]:
        for row in item["sensitivity"]:
            plan = row["plan"]
            lines.append(
                f"| {item['scenario_id']} | {item['family']} | {item['total_flow_vph']} | "
                f"{row['saturation_veh_h_lane']:g} | {row['y']} | {row['lost_time_s']} | "
                f"{row['webster_cycle_s']} | {row['status']} | "
                f"{', '.join(p['code'] for p in row['problems']) or '-'} | "
                f"{'-' if plan is None else '/'.join(f'{v:g}' for v in plan.values())} | "
                f"{'-' if row['cycle_s'] is None else f'{row["cycle_s"]:g}'} |"
            )
    lines += [
        "",
        "## Resumen por saturación",
        "",
        "| Saturación | Aplica | No aplica |",
        "|---:|---:|---:|",
    ]
    for saturation, counts in report["summary"].items():
        lines.append(f"| {saturation} | {counts['applicable']} | {counts['not_applicable']} |")
    current = report["scenarios"][0]["current_plan"]
    lines += [
        "",
        f"Plan vigente: {'/'.join(f'{v:g}' for v in current['plan'].values())} s, ciclo "
        f"{current['cycle_s']:g} s, {'cumple' if current['feasible'] else 'no cumple'} las reglas "
        "del caso (es el mismo en todos los escenarios: no cambia con la demanda).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", maxsplit=1)[0])
    parser.add_argument("--salida", type=Path, required=True, help="carpeta nueva del informe")
    parser.add_argument("--datos", type=Path, default=ROOT / "datos", help="carpeta de insumos")
    parser.add_argument(
        "--publicar", action="store_true", help=f"publicar los comparadores de {SCENARIO} en datos"
    )
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
    case = read_case(case_dir / "case.json")
    order = parse_adjust_order(
        json.loads((case_dir / "orden_de_ajuste.json").read_text(encoding="utf-8"))
    )
    prepared = prepare(case, order)
    program = data_root / "derivados" / "programas" / CASE / PILOT_PROGRAM
    parameters = read_parameters(PARAMETERS, case)
    base = read_scenario(data_root / "escenarios" / CASE / f"{SCENARIO}.json", case)

    spec_path = output / "spec.json"
    spec_path.write_bytes(
        (json.dumps(spec_from(base), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    workspace = output / "datos"
    generated = generate_scenario_set(workspace, case_dir / "case.json", spec_path, SET_SEED)
    scenario_set = read_scenario_set(workspace / generated.folder)
    families = {entry.scenario_id: entry.family_id for entry in scenario_set.manifest.scenarios}

    items: list[dict[str, Any]] = []
    item, result = scenario_report(prepared, base, parameters, program, "ESC-SINT-001")
    items.append(item)
    published: str | None = None
    if arguments.publicar:
        folder = publish_comparators(data_root, result)
        read_comparators(folder)
        published = folder.relative_to(data_root).as_posix()
    for scenario in scenario_set.scenarios:
        item, result = scenario_report(
            prepared, scenario, parameters, program, families[scenario.scenario_id]
        )
        items.append(item)
        read_comparators(publish_comparators(workspace, result))

    summary: dict[str, dict[str, int]] = {}
    for item in items:
        for row in item["sensitivity"]:
            counts = summary.setdefault(
                f"{row['saturation_veh_h_lane']:g}", {"applicable": 0, "not_applicable": 0}
            )
            counts[row["status"]] += 1
    bounds = case.cycle_s
    report: dict[str, Any] = {
        "case_id": case.case_id,
        "case_version": case.case_version,
        "case_origin": case.origin,
        "parameter_set": parameters.parameter_set,
        "parameter_status": parameters.status,
        "base_saturation": parameters.saturation_flow_veh_h_lane,
        "cycle_bounds_s": [bounds.min, bounds.max],
        "scenario_set": generated.folder,
        "scenario_set_seed": SET_SEED,
        "families": {name: list(factors) for name, factors in FAMILIES.items()},
        "published_comparators": published,
        "scenarios": items,
        "summary": summary,
    }
    (output / "aplicabilidad.json").write_bytes(
        (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )
    (output / "aplicabilidad.md").write_bytes(markdown(report).encode("utf-8"))
    print(f"{len(items)} escenarios; resumen por saturación: {summary}")
    if published is not None:
        print(f"comparadores de {SCENARIO} publicados en datos/{published}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
