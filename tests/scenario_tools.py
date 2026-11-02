"""Ayudas de las pruebas de escenarios controlados (DEV11): caso, especificación y generación."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from semaforo.datos.scenario_set import PublishedSet, publish_scenario_set
from semaforo.datos.scenarios import GeneratedScenario, generate_scenarios
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.scenario import Scenario
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


def write_inputs(folder: Path, spec: dict[str, Any] | None = None) -> tuple[Path, Path]:
    """Escribe el caso de ejemplo y la especificación (o ``spec``) en ``folder``; devuelve ambos."""
    folder.mkdir(parents=True, exist_ok=True)
    case_path = folder / "case.json"
    case_path.write_bytes((FIXTURES / "case.json").read_bytes())
    spec_path = folder / "spec.json"
    spec_path.write_text(json.dumps(spec_data() if spec is None else spec), encoding="utf-8")
    return case_path, spec_path


def families_spec(count: int, variants: int = 2, seeds: int = 2) -> dict[str, Any]:
    """La especificación de ejemplo con ``count`` familias iguales a FAM_PUNTA (FAM_01...)."""
    data = spec_data()
    template = data["families"][0]
    data["families"] = [
        {
            **copy.deepcopy(template),
            "family_id": f"FAM_{n:02d}",
            "variants": variants,
            "seeds": seeds,
        }
        for n in range(1, count + 1)
    ]
    return data


def scenarios_of(count: int, variants: int = 2, seeds: int = 2) -> list[Scenario]:
    """Los escenarios de ``count`` familias (``variants`` x ``seeds`` escenarios cada una)."""
    return [m.scenario for m in generated(families_spec(count, variants, seeds))]


def publish_set(workspace: Path, families: int = 5, seed: int = SEED) -> PublishedSet:
    """Publica en ``workspace`` un conjunto de ``families`` familias (4 escenarios cada una)."""
    return publish_scenario_set(
        workspace,
        the_case(),
        parse_spec(families_spec(families)),
        seed,
        clock=lambda: datetime(2026, 11, 2, 14, 0, 7, tzinfo=UTC),
    )
