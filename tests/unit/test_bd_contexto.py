"""El contexto con que se miden y se concilian las corridas (DEV31 F4c, C1.1 y C1.2; B05).

Un escenario generado (DEV11) está en un conjunto de ``derivados/escenarios``, no en
``escenarios/``. El contexto lo tiene que ver; si algo no se puede leer, queda registrado con su
motivo y no detiene al resto.
"""

from datetime import UTC, datetime
from pathlib import Path

from scenario_tools import SEED, the_case, the_spec
from semaforo.bd.carga.fuentes import discover
from semaforo.bd.metricas import load_context
from semaforo.datos.scenario_set import publish_scenario_set
from workspace_tools import tamper

CLOCK = datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)


def _publish(workspace: Path) -> list[str]:
    published = publish_scenario_set(workspace, the_case(), the_spec(), SEED, clock=lambda: CLOCK)
    return sorted(p.stem for p in (published.folder / "escenarios").glob("*.json"))


def test_the_generated_scenarios_of_a_published_set_are_in_the_context(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    ids = _publish(workspace)
    context = load_context(workspace)
    case = the_case()
    assert ids
    assert sorted(key[2] for key in context.scenarios) == ids
    assert all(key[:2] == (case.case_id, case.case_version) for key in context.scenarios)
    assert context.problems == {}


def test_the_catalog_and_the_context_see_the_same_set(tmp_path: Path) -> None:
    workspace = tmp_path / "datos"
    _publish(workspace)
    sources = discover(workspace)
    assert len(sources.of("scenario_set")) == 1
    assert len(load_context(workspace, sources).scenarios) == len(load_context(workspace).scenarios)


def test_an_unreadable_set_is_recorded_with_its_reason_and_does_not_stop_the_rest(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "datos"
    _publish(workspace)
    manifest = next((workspace / "derivados" / "escenarios").rglob("manifiesto.json"))
    tamper(manifest)
    context = load_context(workspace)
    assert context.scenarios == {}
    (key,) = context.problems
    assert key.startswith("conjunto:derivados/escenarios/")
