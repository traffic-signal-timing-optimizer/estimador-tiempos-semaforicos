"""El ejemplo de dos movimientos sobre la red de demostración, para las pruebas de DEV06.

Arma el caso, su red, el programa derivado y el escenario del ejemplo, con los cambios que pida
cada prueba. Lo usan las pruebas de las entradas (F2) y de la conciliación y las corridas (F3).
"""

import gzip
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from semaforo.caso.network_map import build_network_map
from semaforo.dominio.case import parse_case
from semaforo.dominio.scenario import parse_scenario
from semaforo.simulacion.compiler import compile_program, publish_program
from semaforo.simulacion.demand_inputs import RouteTable, VehicleTypes
from semaforo.simulacion.prepare import PreparationRequest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DEMO_NET = FIXTURES / "sumo" / "demo" / "demo.net.xml"
DURATIONS = {"s1": 30.0, "s2": 3.0, "s3": 1.0, "s4": 22.0, "s5": 3.0, "s6": 1.0}
MOMENT = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)
ROUTES: dict[str, Any] = {"routes": {"N_S": ["demo_N", "demo_S"], "E_W": ["demo_E", "demo_W"]}}
TYPES: dict[str, Any] = {
    "types": {
        "car": {"vclass": "passenger", "attributes": {"length": 5.0, "accel": 2.6}},
        "bus": {"vclass": "bus", "attributes": {"length": 12.0}, "gui_shape": "bus"},
    }
}
Change = Callable[[dict[str, Any]], None]


def json_of(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def request_for(  # noqa: PLR0913 - cada argumento cambia una pieza del ejemplo
    tmp_path: Path,
    *,
    net: Callable[[str], str] | None = None,
    case_change: Change | None = None,
    scenario_change: Change | None = None,
    routes: dict[str, Any] | None = None,
    compressed: bool = False,
    **options: Any,  # noqa: ANN401 - campos de PreparationRequest
) -> PreparationRequest:
    """El ejemplo de dos movimientos sobre la red de demostración, con los cambios pedidos."""
    case_dir = tmp_path / "caso"
    case_dir.mkdir(exist_ok=True)
    text = DEMO_NET.read_text(encoding="utf-8")
    data = (net(text) if net else text).encode("utf-8")
    name = "demo.net.xml.gz" if compressed else "demo.net.xml"
    (case_dir / name).write_bytes(gzip.compress(data, mtime=0) if compressed else data)
    case_data = json_of("case.json")
    case_data["network"] = {
        "artifact_id": "red",
        "path": name,
        "sha256": hashlib.sha256((case_dir / name).read_bytes()).hexdigest(),
    }
    if case_change:
        case_change(case_data)
    case = parse_case(case_data)
    original = parse_case({**json_of("case.json"), "network": case_data["network"]})
    program = compile_program(original, build_network_map(case_dir / name, original), DURATIONS)
    programs = tmp_path / "programas"
    folder = programs / case.case_id
    existing = sorted(folder.iterdir()) if folder.exists() else []
    program_dir = existing[0] if existing else publish_program(programs, case, program, MOMENT)
    scenario_data = json_of("scenario.json")
    scenario_data["warmup_s"] = 60
    if scenario_change:
        scenario_change(scenario_data)
    return PreparationRequest(
        case=case,
        case_dir=case_dir,
        scenario=parse_scenario(scenario_data),
        routes=RouteTable.model_validate(routes or ROUTES),
        vehicle_types=VehicleTypes.model_validate(TYPES),
        program_dir=program_dir,
        **options,
    )
