"""Ayudas de prueba para los comparadores de DEV15 (caso de demostración, datos sintéticos).

Los parámetros salen del archivo ``configs/webster/parametros-v2.json`` adaptados al caso de
demostración; la solicitud se arma con los flujos que pida cada prueba.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from prepared_inputs import DURATIONS, json_of
from semaforo.dominio.case import Case
from semaforo.dominio.scenario import Request
from semaforo.referencias.baselines import WebsterParameters

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "webster" / "parametros-v2.json"


def parameters_data(**changes: Any) -> dict[str, Any]:  # noqa: ANN401 - campos del archivo
    data: dict[str, Any] = json.loads(CONFIG.read_text(encoding="utf-8"))
    data.update(
        case_id="SYNTHETIC_DEMO",
        case_version="1.0.0",
        vehicle_equivalence={"car": 1.0, "bus": 2.0},
    )
    data["current_plan"] = {**data["current_plan"], "cycle_s": sum(DURATIONS.values())}
    data.update(changes)
    return data


def parameters(**changes: Any) -> WebsterParameters:  # noqa: ANN401 - campos del archivo
    return WebsterParameters.model_validate(parameters_data(**changes))


def request_with(
    case: Case, flows: Mapping[str, float], composition: dict[str, float] | None = None
) -> Request:
    """Solicitud con esos flujos; por defecto, todos autos."""
    data = json_of("request.json")
    data.update(case_id=case.case_id, case_version=case.case_version)
    mix = {"car": 1.0, "bus": 0.0} if composition is None else composition
    data["demand"] = [
        {"movement_id": movement_id, "flow_vph": flow, "composition": mix if flow > 0 else None}
        for movement_id, flow in flows.items()
    ]
    return Request.model_validate(data)
