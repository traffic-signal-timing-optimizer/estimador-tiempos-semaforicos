"""Pruebas de la comprobación de duraciones frente a los límites del caso (DEV03, F2)."""

import copy
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from semaforo.dominio.case import Case, CaseIssue, parse_case
from semaforo.dominio.case_plan import plan_issues

DEMO_CASE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "case.json").read_text(encoding="utf-8")
)
# Plan de ejemplo de response.json: 30, 3, 1, 22, 3 y 1 s (ciclo de 60 s).
VALID = {"s1": 30.0, "s2": 3.0, "s3": 1.0, "s4": 22.0, "s5": 3.0, "s6": 1.0}


def make_case(change: Callable[[dict[str, Any]], None] | None = None) -> Case:
    data = copy.deepcopy(DEMO_CASE)
    if change is not None:
        change(data)
    return parse_case(data)


def rules_and_fields(issues: list[CaseIssue]) -> list[tuple[str, str | None]]:
    return [(issue.rule_id, issue.field) for issue in issues]


def test_the_example_plan_has_no_issues() -> None:
    assert plan_issues(make_case(), VALID) == []


def test_a_missing_and_an_unknown_slot_are_reported() -> None:
    durations = {key: value for key, value in VALID.items() if key != "s4"}
    durations["extra"] = 5.0
    assert rules_and_fields(plan_issues(make_case(), durations)) == [
        ("PLAN-01", "durations[extra]"),
        ("PLAN-01", "durations[s4]"),
    ]


def test_a_duration_that_is_not_finite_is_reported() -> None:
    for bad in (math.nan, math.inf, -math.inf):
        issues = plan_issues(make_case(), {**VALID, "s1": bad})
        assert rules_and_fields(issues) == [("PLAN-01", "durations[s1]")]


def test_a_duration_below_or_above_its_slot_limits_is_reported() -> None:
    for value in (9.0, 51.0):
        issues = plan_issues(make_case(), {**VALID, "s1": value})
        assert ("PLAN-02", "durations[s1]") in rules_and_fields(issues)


def test_the_limits_of_a_slot_are_inclusive() -> None:
    assert plan_issues(make_case(), {**VALID, "s1": 10.0, "s4": 30.0}) == []
    assert plan_issues(make_case(), {**VALID, "s1": 50.0}) == []


def test_a_fixed_slot_cannot_change() -> None:
    issues = plan_issues(make_case(), {**VALID, "s2": 4.0})
    assert ("PLAN-02", "durations[s2]") in rules_and_fields(issues)


def test_a_duration_must_be_a_multiple_of_the_tick() -> None:
    issues = plan_issues(make_case(), {**VALID, "s1": 30.5})
    assert rules_and_fields(issues) == [("PLAN-03", "durations[s1]")]


def test_a_half_second_tick_accepts_half_seconds() -> None:
    def half_tick(data: dict[str, Any]) -> None:
        data["tick_s"] = 0.5

    assert plan_issues(make_case(half_tick), {**VALID, "s1": 30.5}) == []


def test_a_cycle_outside_the_case_range_is_reported() -> None:
    issues = plan_issues(make_case(), {**VALID, "s1": 10.0, "s4": 10.0})
    assert rules_and_fields(issues) == [("PLAN-04", "durations")]
    assert "28 s" in issues[0].message


def test_a_green_outside_its_group_limits_is_reported() -> None:
    def tighter_group(data: dict[str, Any]) -> None:
        data["green_groups"][0]["min_s"] = 20
        data["green_groups"][0]["max_s"] = 40

    issues = plan_issues(make_case(tighter_group), {**VALID, "s1": 12.0, "s4": 40.0})
    assert rules_and_fields(issues) == [("PLAN-05", "green_groups[0]")]


def test_sums_are_not_evaluated_when_a_slot_is_invalid() -> None:
    issues = plan_issues(make_case(), {**VALID, "s1": 1.0})
    assert {issue.rule_id for issue in issues} == {"PLAN-02"}
