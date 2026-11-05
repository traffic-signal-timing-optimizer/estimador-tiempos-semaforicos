"""Mutaciones de la corrección A03: el origen de la evidencia sale del caso y de la demanda.

Cada daño cambia una regla de ``evidence_origin`` (dominio), de las métricas de una corrida, de los
comparadores o de la verificación de evidencia. Uso:
``python scripts\\mutaciones\\mutar.py scripts\\mutaciones\\a03.py``.
"""

S = "src/semaforo/dominio/scenario.py"
R = "src/semaforo/evaluacion/run_metrics.py"
C = "src/semaforo/referencias/comparators.py"
V = "src/semaforo/referencias/evidence.py"
MIXED = 'return "field" if (case_origin, demand_origin) == ("field", "field") else "synthetic"'
VALID = "if self.evidence_origin != evidence_origin(self.case_origin, self.demand_origin):"
SCENARIO_NEW = "test_the_evidence_notices_a_scenario_that_is_not_the_one_used"
TESTS = [
    "tests/unit/test_scenario.py",
    "tests/unit/test_comparators.py",
    "tests/integration/test_run_metrics_sumo.py",
    f"tests/integration/test_search_sumo.py::{SCENARIO_NEW}",
]
MUTATIONS = [
    (
        S,
        MIXED,
        'return "field" if "field" in (case_origin, demand_origin) else "synthetic"',
        "campo si lo es cualquiera",
    ),
    (S, MIXED, 'return "synthetic"', "nunca campo"),
    (
        S,
        MIXED,
        'return "field" if case_origin == "field" else "synthetic"',
        "solo importa el caso (el defecto original)",
    ),
    (
        S,
        MIXED,
        'return "field" if demand_origin == "field" else "synthetic"',
        "solo importa la demanda",
    ),
    (
        R,
        '    if canonical_json_sha256(scenario.model_dump(mode="json")) != manifest.scenario_sha256:',
        "    if False:",
        "escenario ajeno aceptado en las métricas",
    ),
    (
        R,
        "    demand_origin = scenario.request.origin\n",
        "    demand_origin = case.origin\n",
        "demanda con el origen del caso",
    ),
    (
        R,
        "        case_origin=case.origin,\n",
        "        case_origin=demand_origin,\n",
        "caso con el origen de la demanda",
    ),
    (
        R,
        "        evidence_origin=evidence_origin(case.origin, demand_origin),",
        "        evidence_origin=case.origin,",
        "evidencia con el origen del caso",
    ),
    (R, f"        {VALID}", "        if False:", "métricas incoherentes aceptadas"),
    (C, f"        {VALID}", "        if False:", "comparadores incoherentes aceptados"),
    (
        C,
        "        demand_origin=result.demand_origin,\n",
        "        demand_origin=result.case.origin,\n",
        "comparadores con la demanda del caso",
    ),
    (
        C,
        "        case_origin=result.case.origin,\n",
        "        case_origin=result.demand_origin,\n",
        "comparadores con el caso de la demanda",
    ),
    (
        C,
        "        evidence_origin=evidence_origin(result.case.origin, result.demand_origin),",
        "        evidence_origin=result.case.origin,",
        "comparadores con la evidencia del caso",
    ),
    (
        C,
        "case, scenario.scenario_id, current, webster, parameters, scenario.request.origin",
        "case, scenario.scenario_id, current, webster, parameters, case.origin",
        "origen de la demanda tomado del caso",
    ),
    (
        C,
        "        evidence_origin=content.evidence_origin,\n",
        '        evidence_origin="synthetic",\n',
        "manifiesto con otra evidencia",
    ),
    (
        C,
        "        and (content.case_origin, content.demand_origin, content.evidence_origin)\n        == (manifest.case_origin, manifest.demand_origin, manifest.evidence_origin)\n",
        "",
        "orígenes del manifiesto sin cotejar",
    ),
    (
        V,
        '        if canonical_json_sha256(scenario.model_dump(mode="json")) != base.scenario_sha256:',
        "        if False:",
        "escenario ajeno aceptado en la evidencia",
    ),
]
