"""Ayudas de las pruebas de escenarios controlados (DEV11): caso, especificación y generación."""

import copy
import json
from pathlib import Path
from typing import Any

from semaforo.datos.scenarios import GeneratedScenario, generate_scenarios
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.scenario_spec import ScenarioSpec, parse_spec

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEED = 7


def spec_data() -> dict[str, Any]:
    """Copia de la especificación de ejemplo (dos familias), lista para estropear."""
    return copy.deepcopy(json.loads((FIXTURES / "scenario_spec.json").read_text(encoding="utf-8")))


def the_case() -> Case:
    """El caso de ejemplo (SYNTHETIC_DEMO: movimientos N_S y E_W, clases car y bus)."""
    return parse_case(json.loads((FIXTURES / "case.json").read_text(encoding="utf-8")))


def the_spec(data: dict[str, Any] | None = None) -> ScenarioSpec:
    return parse_spec(spec_data() if data is None else data)


def generated(
    data: dict[str, Any] | None = None, seed: int = SEED
) -> tuple[GeneratedScenario, ...]:
    """Los escenarios de la especificación (o de ``data``) sobre el caso de ejemplo."""
    return generate_scenarios(the_spec(data), the_case(), seed)
