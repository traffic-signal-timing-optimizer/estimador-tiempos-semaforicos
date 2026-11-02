"""Concordancia entre las reglas temporales de DEV13 y el compilador de SUMO de DEV03 (F4).

Todo plan que el validador o el corrector declaran admisible tiene que compilar a un programa de
SUMO; todo plan que incumple una regla no debe compilar. Si no, el estimador entregaría planes que
SUMO no acepta, o rechazaría planes que sí se pueden simular. Se usa la red de demostración y su
caso (``tests/fixtures``): datos sintéticos.
"""

import copy
import itertools
import json
from pathlib import Path

import pytest

from semaforo.caso.network_map import NetworkMap, build_network_map
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.feasibility import PreparedCase, check_plan, correct, prepare
from semaforo.simulacion.compiler import CompilationError, compile_program

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_NET = FIXTURES / "sumo" / "demo" / "demo.net.xml"
DEMO_CASE = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
FIXED = {"s2": 3.0, "s3": 1.0, "s5": 3.0, "s6": 1.0}
VALUES = [-1.0, 0.0, 5.0, 9.0, 9.5, 10.0, 10.0000001, 25.0, 25.5, 49.0, 50.0, 50.5, 51.0, 1e6]


def demo_case() -> Case:
    return parse_case(copy.deepcopy(DEMO_CASE))


def complete_map(case: Case) -> NetworkMap:
    network_map = build_network_map(DEMO_NET, case)
    assert network_map.is_complete
    return network_map


def compiles(case: Case, network_map: NetworkMap, plan: dict[str, float]) -> bool:
    try:
        compile_program(case, network_map, plan)
    except CompilationError:
        return False
    return True


def full(s1: float, s4: float, **fixed: float) -> dict[str, float]:
    return {"s1": s1, "s4": s4, **FIXED, **fixed}


def ready() -> tuple[Case, NetworkMap, PreparedCase]:
    case = demo_case()
    return case, complete_map(case), prepare(case)


def test_a_plan_is_feasible_exactly_when_the_compiler_accepts_it() -> None:
    case, network_map, prepared = ready()
    seen = {True: 0, False: 0}
    for s1, s4 in itertools.product(VALUES, VALUES):
        plan = full(s1, s4)
        feasible = check_plan(prepared, plan).feasible
        assert feasible == compiles(case, network_map, plan), plan
        seen[feasible] += 1
    assert seen[True] > 10
    assert seen[False] > 10


def test_a_changed_fixed_slot_is_rejected_by_both() -> None:
    case, network_map, prepared = ready()
    for fixed in ("s2", "s3", "s5", "s6"):
        for value in (0.0, FIXED[fixed] - 1, FIXED[fixed] + 1):
            plan = full(30.0, 22.0, **{fixed: value})
            assert not check_plan(prepared, plan).feasible
            assert not compiles(case, network_map, plan)


def test_the_cycle_limits_agree() -> None:
    case, network_map, prepared = ready()
    # El ciclo del caso va de 40 a 100 s y los fijos suman 8 s.
    for s1, s4, ok in [(16, 16, True), (15, 16, False), (46, 46, True), (46, 47, False)]:
        plan = full(float(s1), float(s4))
        assert check_plan(prepared, plan).feasible is ok
        assert compiles(case, network_map, plan) is ok


@pytest.mark.parametrize(
    "bad", [float("nan"), float("inf"), True, "30", None, [30.0], 10**400], ids=repr
)
def test_a_value_that_is_not_a_finite_number_is_rejected_by_both_without_breaking(
    bad: object,
) -> None:
    case, network_map, prepared = ready()
    plan = full(30.0, 22.0)
    plan["s1"] = bad  # type: ignore[assignment]
    assert not check_plan(prepared, plan).feasible
    assert not compiles(case, network_map, plan)


def test_every_corrected_plan_compiles_to_the_same_durations() -> None:
    case, network_map, prepared = ready()
    admissible = 0
    for s1, s4 in itertools.product(VALUES, VALUES):
        result = correct(
            prepared, {"s1": s1, "s4": s4}, case_id=case.case_id, case_version=case.case_version
        )
        assert result.status in ("accepted", "corrected")
        assert result.final_s is not None
        program = compile_program(case, network_map, dict(result.final_s))
        assert {phase.slot_id: phase.duration_s for phase in program.phases} == dict(result.final_s)
        admissible += 1
    assert admissible == len(VALUES) ** 2


def test_a_correction_of_a_non_numeric_proposal_never_reaches_the_compiler() -> None:
    case, _, prepared = ready()
    result = correct(
        prepared,
        {"s1": float("nan"), "s4": 22.0},
        case_id=case.case_id,
        case_version=case.case_version,
    )
    assert result.status == "invalid_input"
    assert result.final_s is None


def test_the_corrected_plan_is_a_multiple_of_the_tick_of_the_case_and_inside_the_cycle() -> None:
    case, network_map, prepared = ready()
    for s1, s4 in [(12.5, 33.3), (49.9, 49.9), (-3.0, 1000.0)]:
        result = correct(
            prepared, {"s1": s1, "s4": s4}, case_id=case.case_id, case_version=case.case_version
        )
        assert result.final_s is not None
        program = compile_program(case, network_map, dict(result.final_s))
        assert all(phase.duration_s == int(phase.duration_s) for phase in program.phases)
        assert (
            case.cycle_s.min
            <= sum(phase.duration_s for phase in program.phases)
            <= case.cycle_s.max
        )
