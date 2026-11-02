"""Pruebas de QA22 y de la cobertura de la corrección (DEV13, F4; HU11, D15).

QA22: predicciones fuera de límites, NaN y casos irreparables; corregir dos veces la misma entrada
da lo mismo; los aceptados cumplen todo; los rechazados cuentan en la cobertura. Datos sintéticos
(la réplica de caso-001 está en ``timing_tools``). Las cifras del conjunto de ejemplo se calcularon
a mano y se confirmaron con una ejecución.
"""

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest

from semaforo.dominio.feasibility import (
    Correction,
    Coverage,
    PreparedCase,
    check_plan,
    correct,
    summarize,
)
from timing_tools import (
    BASELINE_VARIABLE,
    CASE_ID,
    CASE_VERSION,
    VARIABLE_IDS,
    Change,
    prepared,
    priority_order,
)


def tight_group(data: dict[str, Any]) -> None:
    """El grupo «recto» (t1 + t2 + t3) pide entre 100 y 150 s: más estricto que sus tramos."""
    data["green_groups"][1]["min_s"] = 100
    data["green_groups"][1]["max_s"] = 150


def ready_case(change: Change | None = None) -> PreparedCase:
    return prepared(change, priority_order())


def run(ready: PreparedCase, proposal: object) -> Correction:
    return correct(ready, proposal, case_id=CASE_ID, case_version=CASE_VERSION)  # type: ignore[arg-type]


def base(**changes: object) -> dict[str, Any]:
    return {**BASELINE_VARIABLE, **changes}


# Diez propuestas con su resultado esperado en el caso de grupo estricto.
EXAMPLE: list[tuple[str, dict[str, Any], str]] = [
    ("la línea base", base(), "accepted"),
    ("t1 a medio segundo", base(t1=82.5), "corrected"),
    ("todo al mínimo de Javier Prado", base(t1=30.0, t3=15.0), "rejected"),
    ("Javier Prado al máximo", base(t1=110.0, t3=60.0), "rejected"),
    ("NaN", base(t1=float("nan")), "invalid_input"),
    ("un texto", base(t3="x"), "invalid_input"),
    ("t1 negativo", base(t1=-5.0), "rejected"),
    ("t1 en 60", base(t1=60.0), "accepted"),
    ("t1 en 61.2", base(t1=61.2), "corrected"),
    ("t5 enorme", base(t5=500.0), "corrected"),
]


def example_results(ready: PreparedCase | None = None) -> list[Correction]:
    target = ready_case(tight_group) if ready is None else ready
    return [run(target, proposal) for _, proposal, _ in EXAMPLE]


# ---------------------------------------------------------------------------
# QA22: fuera de límites, NaN e irreparables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "proposal", "status"), EXAMPLE, ids=[e[0] for e in EXAMPLE])
def test_qa22_each_prediction_ends_in_the_expected_state(
    label: str, proposal: dict[str, Any], status: str
) -> None:
    assert run(ready_case(tight_group), proposal).status == status, label


def test_qa22_correcting_twice_gives_the_same_record() -> None:
    ready = ready_case(tight_group)
    for _, proposal, _ in EXAMPLE:
        assert run(ready, proposal) == run(ready, proposal)
    assert summarize(example_results(ready)) == summarize(example_results(ready))


def test_qa22_the_corrected_plan_corrected_again_is_accepted_and_unchanged() -> None:
    ready = ready_case(tight_group)
    for result in example_results(ready):
        if result.status in ("corrected", "accepted"):
            assert result.final_s is not None
            again = run(ready, {slot_id: result.final_s[slot_id] for slot_id in VARIABLE_IDS})
            assert again.status == "accepted"
            assert again.final_s == result.final_s


def test_qa22_every_accepted_or_corrected_plan_satisfies_every_rule() -> None:
    ready = ready_case(tight_group)
    for result in example_results(ready):
        if result.admissible:
            assert result.final_s is not None
            checked = check_plan(ready, result.final_s)
            assert checked.feasible
            assert all(o.status == "satisfied" for o in checked.outcomes)


def test_qa22_a_rejected_plan_is_never_admissible_and_says_which_rule_fails() -> None:
    for result, (_, _, status) in zip(example_results(), EXAMPLE, strict=True):
        if status == "rejected":
            assert not result.admissible
            assert result.plan is None
            assert result.check is not None
            assert result.check.violated == ("PLAN-05",)
            assert "jp_oeste_este_recto" in result.check.issues[0].message


# ---------------------------------------------------------------------------
# Cobertura
# ---------------------------------------------------------------------------


def test_the_example_counts_every_state() -> None:
    summary = summarize(example_results())
    assert (summary.total, summary.accepted, summary.corrected) == (10, 2, 3)
    assert (summary.rejected, summary.invalid_input) == (3, 2)
    assert (summary.admissible, summary.evaluated) == (5, 8)


def test_the_rejected_plans_count_in_the_denominator() -> None:
    summary = summarize(example_results())
    assert summary.coverage == 5 / 8
    assert summary.coverage != 5 / 5
    assert summary.coverage != 5 / 10


def test_the_invalid_inputs_are_counted_apart_and_do_not_enter_the_coverage() -> None:
    results = example_results()
    without_invalid = [r for r in results if r.status != "invalid_input"]
    assert summarize(results).coverage == summarize(without_invalid).coverage


def test_the_restriction_report_says_which_rules_reject_and_which_slots_move() -> None:
    summary = summarize(example_results())
    assert dict(summary.rejected_by_rule) == {"PLAN-05": 3}
    assert dict(summary.corrected_by_slot) == {"t1": 2, "t5": 1}
    assert dict(summary.largest_change_s) == {"t1": 0.5, "t5": 430.0}


def test_only_the_corrected_plans_feed_the_slot_report() -> None:
    results = example_results()
    only_rejected = [r for r in results if r.status == "rejected"]
    summary = summarize(only_rejected)
    assert dict(summary.corrected_by_slot) == {}
    assert dict(summary.largest_change_s) == {}
    assert dict(summary.rejected_by_rule) == {"PLAN-05": 3}


def test_the_rules_version_is_the_one_of_the_corrections() -> None:
    ready = ready_case(tight_group)
    assert summarize(example_results(ready)).rules_version == ready.rules_version


def test_an_empty_set_has_no_coverage_instead_of_a_hundred_percent() -> None:
    summary = summarize([])
    assert (summary.total, summary.evaluated, summary.admissible) == (0, 0, 0)
    assert summary.coverage is None
    assert summary.rules_version is None
    assert dict(summary.rejected_by_rule) == {}


def test_a_set_of_only_invalid_inputs_has_no_coverage() -> None:
    ready = ready_case()
    results = [run(ready, {"t1": float("nan")}), run(ready, None)]
    summary = summarize(results)
    assert (summary.total, summary.invalid_input, summary.evaluated) == (2, 2, 0)
    assert summary.coverage is None


def test_a_set_with_no_rejection_has_full_coverage() -> None:
    ready = ready_case()
    results = [run(ready, BASELINE_VARIABLE), run(ready, base(t1=500.0))]
    summary = summarize(results)
    assert summary.coverage == 1.0
    assert summary.rejected == 0


def test_a_set_of_only_rejections_has_zero_coverage() -> None:
    ready = ready_case(tight_group)
    summary = summarize([run(ready, base(t1=30.0, t3=15.0)), run(ready, base(t1=-5.0))])
    assert summary.coverage == 0.0
    assert summary.rejected == 2


def test_corrections_made_with_different_rules_are_not_summarized_together() -> None:
    first = run(ready_case(), BASELINE_VARIABLE)
    second = run(ready_case(tight_group), BASELINE_VARIABLE)
    assert first.rules_version != second.rules_version
    with pytest.raises(ValueError, match="reglas distintas"):
        summarize([first, second])
    with pytest.raises(ValueError, match="reglas distintas"):
        summarize([second, first])


def test_two_preparations_of_the_same_case_give_comparable_corrections() -> None:
    first = run(ready_case(), BASELINE_VARIABLE)
    second = run(ready_case(), base(t1=500.0))
    assert summarize([first, second]).total == 2


def test_the_summary_accepts_a_generator_and_reads_it_once() -> None:
    ready = ready_case(tight_group)
    produced = 0

    def stream() -> Iterator[Correction]:
        nonlocal produced
        for _, proposal, _ in EXAMPLE:
            produced += 1
            yield run(ready, proposal)

    summary = summarize(stream())
    assert produced == 10
    assert summary.total == 10


def test_the_summary_cannot_be_modified_and_its_reports_are_sorted() -> None:
    summary = summarize(example_results())
    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.accepted = 0  # type: ignore[misc]
    with pytest.raises(TypeError):
        summary.rejected_by_rule["PLAN-05"] = 0  # type: ignore[index]
    with pytest.raises(TypeError):
        summary.corrected_by_slot["t1"] = 0  # type: ignore[index]
    with pytest.raises(TypeError):
        summary.largest_change_s["t1"] = 0.0  # type: ignore[index]
    assert list(summary.corrected_by_slot) == sorted(summary.corrected_by_slot)
    assert isinstance(summary, Coverage)


def test_the_slot_report_counts_only_real_changes_against_what_was_proposed() -> None:
    ready = ready_case()
    # t1 se recorta de 500 a 110 (-390) en las dos; t3 se recorta de 100 a 60 (-40) solo en la
    # segunda. El ciclo queda en 234 y 240 s: no hace falta ajustarlo.
    results = [
        run(ready, base(t1=500.0)),
        run(ready, base(t1=500.0, t3=100.0, t5=41.0, t7=5.0)),
    ]
    summary = summarize(results)
    assert dict(summary.corrected_by_slot) == {"t1": 2, "t3": 1}
    assert dict(summary.largest_change_s) == {"t1": 390.0, "t3": 40.0}


def test_the_reports_are_sorted_by_name_whatever_the_order_of_the_corrections() -> None:
    ready = ready_case()
    results = [
        run(ready, base(t7=500.0)),
        run(ready, base(t5=500.0)),
        run(ready, base(t3=500.0)),
        run(ready, base(t1=500.0)),
    ]
    summary = summarize(results)
    assert list(summary.corrected_by_slot) == ["t1", "t3", "t5", "t7"]
    assert list(summary.largest_change_s) == ["t1", "t3", "t5", "t7"]


def test_the_rejection_report_is_sorted_by_rule() -> None:
    def two_groups(data: dict[str, Any]) -> None:
        tight_group(data)
        data["green_groups"][3]["min_s"] = 60

    ready = ready_case(two_groups)
    results = [run(ready, base(t5=45.0, t1=30.0, t3=15.0)), run(ready, base(t1=30.0, t3=15.0))]
    summary = summarize(results)
    assert dict(summary.rejected_by_rule) == {"PLAN-05": 2}
    assert list(summary.rejected_by_rule) == sorted(summary.rejected_by_rule)


# ---------------------------------------------------------------------------
# Denominadores del indicador I4 del plan de pruebas
# ---------------------------------------------------------------------------


def test_i4_the_three_denominators_are_explicit() -> None:
    summary = summarize(example_results())
    # 2 aceptadas, 3 corregidas, 3 rechazadas y 2 de entrada inválida.
    assert summary.feasibility_before == 2 / 8
    assert summary.feasibility_after == 5 / 8
    assert summary.coverage == summary.feasibility_after
    assert summary.coverage_with_invalid == 5 / 10


def test_i4_the_three_figures_differ_so_that_a_hundred_percent_cannot_hide_failures() -> None:
    summary = summarize(example_results())
    figures = {
        summary.feasibility_before,
        summary.feasibility_after,
        summary.coverage_with_invalid,
    }
    assert len(figures) == 3


def test_i4_a_set_without_rejections_or_invalid_inputs_gives_the_same_after_and_with_invalid() -> (
    None
):
    ready = ready_case()
    summary = summarize([run(ready, BASELINE_VARIABLE), run(ready, base(t1=500.0))])
    assert summary.feasibility_before == 0.5
    assert summary.feasibility_after == 1.0
    assert summary.coverage_with_invalid == 1.0


def test_i4_invalid_inputs_lower_only_the_coverage_that_counts_them() -> None:
    ready = ready_case()
    results = [run(ready, BASELINE_VARIABLE), run(ready, {"t1": float("nan")})]
    summary = summarize(results)
    assert summary.feasibility_after == 1.0
    assert summary.coverage_with_invalid == 0.5


def test_i4_without_evaluated_proposals_the_prediction_figures_are_none() -> None:
    ready = ready_case()
    summary = summarize([run(ready, None), run(ready, {"t1": float("nan")})])
    assert summary.feasibility_before is None
    assert summary.feasibility_after is None
    assert summary.coverage is None
    assert summary.coverage_with_invalid == 0.0


def test_i4_an_empty_set_has_no_figures_at_all() -> None:
    summary = summarize([])
    assert summary.feasibility_before is None
    assert summary.feasibility_after is None
    assert summary.coverage_with_invalid is None
