"""MAE del ciclo y de cada verde entre planes (DEV19 F4; I5), con cifras calculadas a mano."""

import json
from pathlib import Path

import pytest

from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.plan_error import PlanPair, plan_mae

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
# El ejemplo: s1 y s4 son los verdes; s2, s3, s5 y s6 son fijos (3, 1, 3 y 1 s).
BASE = {"s1": 30.0, "s2": 3.0, "s3": 1.0, "s4": 22.0, "s5": 3.0, "s6": 1.0}


def case() -> Case:
    return parse_case(json.loads((FIXTURES / "case.json").read_text(encoding="utf-8")))


def plan(s1: float, s4: float) -> dict[str, float]:
    return {**BASE, "s1": s1, "s4": s4}


def groups() -> list[str]:
    return [group.id for group in case().green_groups]


def test_the_mae_of_the_cycle_and_of_each_green_matches_the_hand_calculation() -> None:
    pairs = [
        PlanPair("e1", plan(34.0, 22.0), plan(30.0, 22.0)),  # ciclo +4, s1 +4, s4 0
        PlanPair("e2", plan(30.0, 16.0), plan(30.0, 22.0)),  # ciclo -6, s1 0, s4 -6
    ]
    result = plan_mae(case(), pairs)
    assert (result.pairs, result.evaluated) == (2, 2)
    assert result.cycle_mae_s == pytest.approx(5.0)
    # Grupo NS = s1: errores 4 y 0 -> 2. Grupo EW = s4: errores 0 y 6 -> 3.
    assert result.green_mae_s == {"NS": pytest.approx(2.0), "EW": pytest.approx(3.0)}
    assert sorted(result.green_mae_s) == sorted(groups())
    same = plan_mae(case(), [PlanPair("x", plan(30.0, 22.0), plan(30.0, 22.0))])
    assert same.green_mae_s == {"NS": 0.0, "EW": 0.0}
    assert same.cycle_mae_s == 0.0


def test_the_cycle_counts_each_slot_once() -> None:
    """El ciclo es la suma de los slots (60 s en el ejemplo), no la suma de los grupos."""
    result = plan_mae(case(), [PlanPair("e", plan(40.0, 22.0), plan(30.0, 22.0))])
    assert result.cycle_mae_s == pytest.approx(10.0)


def test_missing_plans_are_counted_and_not_dropped() -> None:
    pairs = [
        PlanPair("ok", plan(32.0, 22.0), plan(30.0, 22.0)),
        PlanPair("rechazado", None, plan(30.0, 22.0)),
        PlanPair("sin-referencia", plan(30.0, 22.0), None),
        PlanPair("nada", None, None),
    ]
    result = plan_mae(case(), pairs)
    assert (result.pairs, result.evaluated) == (4, 1)
    assert (result.missing_prediction, result.missing_reference) == (1, 2)
    assert result.evaluated + result.missing_prediction + result.missing_reference == 4
    assert result.cycle_mae_s == pytest.approx(2.0)


def test_without_evaluated_pairs_there_is_no_mae() -> None:
    result = plan_mae(case(), [PlanPair("x", None, plan(30.0, 22.0))])
    assert result.cycle_mae_s is None
    assert all(value is None for value in result.green_mae_s.values())
    assert plan_mae(case(), []).pairs == 0


def test_the_order_of_the_keys_does_not_matter() -> None:
    shuffled = dict(reversed(list(plan(33.0, 20.0).items())))
    first = plan_mae(case(), [PlanPair("e", plan(33.0, 20.0), plan(30.0, 22.0))])
    second = plan_mae(case(), [PlanPair("e", shuffled, plan(30.0, 22.0))])
    assert first == second


@pytest.mark.parametrize(
    "broken",
    [
        {k: v for k, v in BASE.items() if k != "s4"},
        {**BASE, "zz": 1.0},
        {**BASE, "s1": float("nan")},
        {**BASE, "s1": -1.0},
    ],
)
@pytest.mark.parametrize("side", ["predicted", "reference"])
def test_a_plan_that_is_not_a_plan_of_the_case_is_refused(
    broken: dict[str, float], side: str
) -> None:
    pair = PlanPair("e", broken, BASE) if side == "predicted" else PlanPair("e", BASE, broken)
    with pytest.raises(EvaluacionError, match="no es un plan del caso") as raised:
        plan_mae(case(), [pair])
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == f"pairs[0].{side}"
