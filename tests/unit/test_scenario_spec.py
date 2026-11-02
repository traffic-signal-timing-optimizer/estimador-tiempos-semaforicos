"""Especificación de escenarios (DEV11 F1): estructura SPEC-S y consistencia SPEC-C con el caso."""

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from semaforo.dominio.case import MAX_ISSUES, Case, CaseIssue, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario_spec import (
    MAX_SCENARIOS,
    MAX_SEEDS,
    MAX_VARIANTS,
    ScenarioSpec,
    SpecInvalidError,
    accept_spec,
    parse_spec,
    scenario_count,
    spec_issues,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def good() -> dict[str, Any]:
    """Copia de la especificación de ejemplo, lista para estropear."""
    return copy.deepcopy(load("scenario_spec.json"))


def the_case() -> Case:
    return parse_case(copy.deepcopy(load("case.json")))


def issues_of(data: dict[str, Any]) -> list[CaseIssue]:
    return spec_issues(parse_spec(data), the_case())


def only_issue(data: dict[str, Any]) -> CaseIssue:
    issues = issues_of(data)
    assert len(issues) == 1, issues
    return issues[0]


def structure_issues(data: object) -> list[CaseIssue]:
    with pytest.raises(SpecInvalidError) as raised:
        parse_spec(data)
    return list(raised.value.issues)


def row(data: dict[str, Any], family: int, position: int) -> dict[str, Any]:
    return data["families"][family]["demand"][position]


# --- la especificación de ejemplo -------------------------------------------------------------


def test_the_reference_spec_is_accepted() -> None:
    spec = accept_spec(good(), the_case())
    assert isinstance(spec, ScenarioSpec)
    assert (spec.spec_id, spec.case_id, spec.origin) == ("SPEC_DEMO", "SYNTHETIC_DEMO", "synthetic")
    assert [family.family_id for family in spec.families] == ["FAM_PUNTA", "FAM_VALLE"]


def test_the_reference_spec_has_its_values() -> None:
    spec = parse_spec(good())
    punta = spec.families[0]
    assert (punta.variants, punta.seeds) == (3, 2)
    assert (punta.demand[0].flow_vph.min, punta.demand[0].flow_vph.max) == (400, 600)
    assert punta.demand[0].composition == {"car": 0.9, "bus": 0.1}
    assert spec.families[1].demand[1].composition is None
    assert (spec.warmup_s, spec.measure_s, spec.drain_max_s) == (0, 900, 900)


def test_the_scenario_count_is_variants_times_seeds_per_family() -> None:
    assert scenario_count(parse_spec(good())) == 3 * 2 + 2 * 2


def test_the_limits_are_the_documented_ones() -> None:
    assert (MAX_VARIANTS, MAX_SEEDS, MAX_SCENARIOS) == (200, 100, 2000)


# --- estructura (SPEC-S01 a SPEC-S03) ---------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "spec_id",
        "case_id",
        "case_version",
        "origin",
        "source_ids",
        "observation_start",
        "observation_end",
        "warmup_s",
        "measure_s",
        "drain_max_s",
        "families",
    ],
)
def test_a_missing_top_level_field_is_reported(field: str) -> None:
    data = good()
    del data[field]
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S01", field)
    assert "falta" in issue.message


@pytest.mark.parametrize("field", ["family_id", "variants", "seeds", "demand"])
def test_a_missing_family_field_is_reported(field: str) -> None:
    data = good()
    del data["families"][0][field]
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S01", f"families[0].{field}")


@pytest.mark.parametrize("field", ["movement_id", "flow_vph", "composition"])
def test_a_missing_row_field_is_reported(field: str) -> None:
    data = good()
    del row(data, 0, 1)[field]
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S01", f"families[0].demand[1].{field}")


@pytest.mark.parametrize("field", ["min", "max"])
def test_a_missing_range_bound_is_reported(field: str) -> None:
    data = good()
    del row(data, 1, 0)["flow_vph"][field]
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S01", f"families[1].demand[0].flow_vph.{field}")


def test_an_unknown_field_is_rejected_at_every_level() -> None:
    places: list[Callable[[dict[str, Any]], dict[str, Any]]] = [
        lambda d: d,
        lambda d: d["families"][0],
        lambda d: row(d, 0, 0),
        lambda d: row(d, 0, 0)["flow_vph"],
    ]
    for place in places:
        data = good()
        place(data)["extra"] = 1
        [issue] = structure_issues(data)
        assert issue.rule_id == "SPEC-S01"
        assert issue.field is not None
        assert issue.field.endswith("extra")
        assert "desconocido" in issue.message


def test_the_schema_version_must_be_the_published_one() -> None:
    data = good()
    data["schema_version"] = "2.0.0"
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S01", "schema_version")


def test_the_data_must_be_an_object() -> None:
    [issue] = structure_issues([])
    assert (issue.rule_id, issue.field) == ("SPEC-S01", None)
    assert "objeto" in issue.message


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("variants", True),
        ("variants", 2.0),
        ("variants", "2"),
        ("variants", 0),
        ("seeds", 0),
        ("seeds", -1),
    ],
)
def test_the_counts_must_be_exact_positive_integers(path: str, value: object) -> None:
    data = good()
    data["families"][0][path] = value
    assert structure_issues(data)[0].field == f"families[0].{path}"


@pytest.mark.parametrize("name", ["warmup_s", "measure_s", "drain_max_s"])
@pytest.mark.parametrize("value", ["900", None, True, float("nan"), float("inf")])
def test_the_times_must_be_finite_numbers(name: str, value: object) -> None:
    data = good()
    data[name] = value
    issues = structure_issues(data)
    assert [issue.field for issue in issues] == [name]


def test_the_measure_must_be_positive_and_the_others_not_negative() -> None:
    data = good()
    data["measure_s"] = 0
    data["warmup_s"] = -1
    data["drain_max_s"] = -1
    fields = {issue.field for issue in structure_issues(data)}
    assert fields == {"measure_s", "warmup_s", "drain_max_s"}


def test_the_range_bounds_cannot_be_negative_or_not_finite() -> None:
    data = good()
    row(data, 0, 0)["flow_vph"] = {"min": -1, "max": float("nan")}
    fields = {issue.field for issue in structure_issues(data)}
    assert fields == {"families[0].demand[0].flow_vph.min", "families[0].demand[0].flow_vph.max"}


@pytest.mark.parametrize("name", ["source_ids", "families"])
def test_the_lists_cannot_be_empty(name: str) -> None:
    data = good()
    data[name] = []
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S01", name)
    assert "al menos" in issue.message


def test_a_family_needs_at_least_one_demand_row() -> None:
    data = good()
    data["families"][0]["demand"] = []
    [issue] = structure_issues(data)
    assert issue.field == "families[0].demand"


def test_the_origin_must_be_a_known_value() -> None:
    data = good()
    data["origin"] = "field"
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S01", "origin")
    assert "synthetic" in issue.message


@pytest.mark.parametrize("version", ["1.0", "01.0.0", "1.0.0-beta", "", "v1.0.0"])
def test_the_case_version_needs_the_major_minor_patch_format(version: str) -> None:
    data = good()
    data["case_version"] = version
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S03", "case_version")


@pytest.mark.parametrize("identifier", ["", " X", "X ", "A\tB", "A\N{ZERO WIDTH SPACE}"])
def test_a_case_identifier_cannot_be_empty_padded_or_invisible(identifier: str) -> None:
    data = good()
    data["case_id"] = identifier
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S02", "case_id")


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "-A",
        "_A",
        "A B",
        "A/B",
        "../X",
        "A.B",
        "Ñ",
        "A\n",
        "A\N{ZERO WIDTH SPACE}",
        "A" * 33,
    ],
)
@pytest.mark.parametrize("where", ["spec", "family"])
def test_the_names_that_become_files_are_safe(identifier: str, where: str) -> None:
    data = good()
    if where == "spec":
        data["spec_id"] = identifier
        field = "spec_id"
    else:
        data["families"][0]["family_id"] = identifier
        field = "families[0].family_id"
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S02", field)
    assert "letras, números, guion bajo y guion" in issue.message


@pytest.mark.parametrize("identifier", ["A", "a1", "A_b-9", "X" * 32, "9"])
def test_a_safe_name_is_accepted(identifier: str) -> None:
    data = good()
    data["spec_id"] = identifier
    data["families"][0]["family_id"] = identifier
    assert parse_spec(data).spec_id == identifier


def test_a_movement_id_with_hidden_characters_is_a_structure_problem() -> None:
    data = good()
    row(data, 0, 0)["movement_id"] = "N_S\N{ZERO WIDTH SPACE}"
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S02", "families[0].demand[0].movement_id")


def test_all_the_structure_problems_come_together() -> None:
    data = good()
    del data["spec_id"]
    data["origin"] = "otro"
    row(data, 1, 0)["flow_vph"]["min"] = -5
    fields = [issue.field for issue in structure_issues(data)]
    assert sorted(fields, key=str) == sorted(
        ["spec_id", "origin", "families[1].demand[0].flow_vph.min"]
    )


# --- consistencia con el caso (SPEC-C01 a SPEC-C05) -------------------------------------------


def test_the_spec_must_be_for_the_case() -> None:
    data = good()
    data["case_id"] = "OTHER"
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C01", "case_id")
    assert "«SYNTHETIC_DEMO»" in issue.message
    assert "«OTHER»" in issue.message


def test_the_spec_must_be_for_the_case_version() -> None:
    data = good()
    data["case_version"] = "2.0.0"
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C01", "case_version")
    assert "versión del caso" in issue.message


def test_a_repeated_family_is_reported_at_its_second_appearance() -> None:
    data = good()
    data["families"][1]["family_id"] = "FAM_PUNTA"
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-S02", "families[1].family_id")
    assert "«FAM_PUNTA» está repetida" in issue.message


def test_a_movement_the_case_does_not_have_is_reported() -> None:
    data = good()
    row(data, 0, 1)["movement_id"] = "X_Y"
    issues = issues_of(data)
    assert [(i.rule_id, i.field) for i in issues] == [
        ("SPEC-C02", "families[0].demand[1].movement_id"),
        ("SPEC-C02", "families[0].demand"),
    ]
    assert "el caso no tiene el movimiento «X_Y»" in issues[0].message
    assert "falta el rango del movimiento «E_W»" in issues[1].message


def test_a_repeated_movement_is_reported() -> None:
    data = good()
    data["families"][0]["demand"].append(copy.deepcopy(row(data, 0, 0)))
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C02", "families[0].demand[2].movement_id")
    assert "«N_S» está repetido" in issue.message


def test_a_missing_movement_is_not_a_zero() -> None:
    data = good()
    del data["families"][1]["demand"][1]
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C02", "families[1].demand")
    assert "una fila ausente no es un cero" in issue.message


def test_an_inverted_range_is_rejected_with_its_reason() -> None:
    data = good()
    row(data, 0, 0)["flow_vph"] = {"min": 600, "max": 400}
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C03", "families[0].demand[0].flow_vph")
    assert issue.message == "el mínimo 600 es mayor que el máximo 400"


def test_a_range_above_the_movement_domain_is_rejected() -> None:
    data = good()
    row(data, 0, 0)["flow_vph"]["max"] = 1300
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C03", "families[0].demand[0].flow_vph")
    assert issue.message == (
        "el rango de 400 a 1300 veh/h sale del dominio del movimiento «N_S»: de 0 a 1200 veh/h"
    )


def test_the_domain_edges_are_inside() -> None:
    data = good()
    row(data, 0, 0)["flow_vph"] = {"min": 0, "max": 1200}
    assert not issues_of(data)


def test_a_range_below_the_movement_domain_is_rejected() -> None:
    case_data = copy.deepcopy(load("case.json"))
    case_data["movements"][0]["flow_domain_vph"] = {"min": 450, "max": 1200}
    spec = parse_spec(good())
    issues = spec_issues(spec, parse_case(case_data))
    assert [(i.rule_id, i.field) for i in issues] == [
        ("SPEC-C03", "families[0].demand[0].flow_vph"),
        ("SPEC-C03", "families[1].demand[0].flow_vph"),
    ]
    assert "de 450 a 1200 veh/h" in issues[0].message


def test_an_inverted_range_outside_the_domain_gives_both_reasons() -> None:
    data = good()
    row(data, 0, 0)["flow_vph"] = {"min": 1300, "max": 1250}
    messages = [issue.message for issue in issues_of(data)]
    assert len(messages) == 2
    assert messages[0].startswith("el mínimo 1300 es mayor")
    assert messages[1].startswith("el rango de 1300 a 1250")


def test_a_zero_to_zero_range_needs_no_composition() -> None:
    data = good()
    assert row(data, 1, 1)["composition"] is None
    assert not issues_of(data)


def test_a_range_that_can_be_positive_needs_a_composition() -> None:
    data = good()
    row(data, 0, 1)["composition"] = None
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C04", "families[0].demand[1].composition")
    assert "falta la composición del movimiento «E_W»" in issue.message
    assert "300 veh/h" in issue.message


def test_a_composition_with_a_class_the_case_lacks_is_rejected() -> None:
    data = good()
    row(data, 0, 0)["composition"] = {"car": 0.9, "bus": 0.05, "tuk": 0.05}
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C04", "families[0].demand[0].composition")
    assert "no tiene la clase de vehículo «tuk»" in issue.message


@pytest.mark.parametrize("share", [-0.1, 1.1])
def test_a_share_outside_zero_one_is_rejected(share: float) -> None:
    data = good()
    row(data, 0, 0)["composition"] = {"car": share, "bus": 1 - share}
    issues = issues_of(data)
    # La clase que falta para sumar 1 también queda fuera de 0 a 1: se informan las dos.
    assert [(i.rule_id, i.field) for i in issues] == [
        ("SPEC-C04", "families[0].demand[0].composition.car"),
        ("SPEC-C04", "families[0].demand[0].composition.bus"),
    ]
    assert all("debe estar entre 0 y 1" in issue.message for issue in issues)


def test_the_shares_must_add_up_to_one() -> None:
    data = good()
    row(data, 0, 0)["composition"] = {"car": 0.5, "bus": 0.1}
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C04", "families[0].demand[0].composition")
    assert issue.message == "las proporciones suman 0.6 y deben sumar 1"


def test_shares_a_hair_outside_zero_one_are_accepted() -> None:
    data = good()
    row(data, 0, 0)["composition"] = {"car": 1 + 1e-10, "bus": -1e-10}
    assert not issues_of(data)


def test_the_shares_may_miss_a_class_that_is_zero() -> None:
    data = good()
    row(data, 0, 0)["composition"] = {"car": 1.0}
    assert not issues_of(data)


def test_a_float_sum_error_inside_the_tolerance_is_accepted() -> None:
    data = good()
    row(data, 0, 0)["composition"] = {"car": 0.1 + 0.2, "bus": 0.7}
    assert not issues_of(data)


def test_too_many_variants_are_rejected() -> None:
    data = good()
    data["families"][0]["variants"] = MAX_VARIANTS + 1
    data["families"][0]["seeds"] = 1
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C05", "families[0].variants")
    assert issue.message == "pide 201 perturbaciones y el máximo es 200"


def test_too_many_seeds_are_rejected() -> None:
    data = good()
    data["families"][0]["variants"] = 1
    data["families"][0]["seeds"] = MAX_SEEDS + 1
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C05", "families[0].seeds")
    assert issue.message == "pide 101 semillas y el máximo es 100"


def test_the_limits_themselves_are_allowed() -> None:
    data = good()
    data["families"] = data["families"][:1]
    data["families"][0]["variants"] = 20
    data["families"][0]["seeds"] = MAX_SEEDS
    assert scenario_count(parse_spec(data)) == MAX_SCENARIOS
    assert not issues_of(data)


def test_the_variants_limit_itself_is_allowed() -> None:
    data = good()
    data["families"] = data["families"][:1]
    data["families"][0]["variants"] = MAX_VARIANTS
    data["families"][0]["seeds"] = 1
    assert not issues_of(data)


def test_too_many_scenarios_in_total_are_rejected() -> None:
    data = good()
    data["families"] = data["families"][:1]
    data["families"][0]["variants"] = 21
    data["families"][0]["seeds"] = MAX_SEEDS
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SPEC-C05", "families")
    assert issue.message == "la especificación genera 2100 escenarios y el máximo es 2000"


def test_the_observation_end_must_follow_the_start() -> None:
    data = good()
    data["observation_end"] = data["observation_start"]
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C05", "observation_end")
    assert "posterior a su inicio" in issue.message


@pytest.mark.parametrize("moment", ["2026-10-18T08:00:00", "ayer", "2026-10-18"])
def test_the_observation_start_needs_an_iso_instant_with_zone(moment: str) -> None:
    data = good()
    data["observation_start"] = moment
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C05", "observation_start")
    assert "ISO 8601 con zona horaria" in issue.message


@pytest.mark.parametrize("name", ["warmup_s", "measure_s", "drain_max_s"])
def test_the_times_must_be_multiples_of_the_case_tick(name: str) -> None:
    data = good()
    data[name] = 10.5
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C05", name)
    assert "no es múltiplo del tick del caso (1 s)" in issue.message


def test_the_problems_come_together_and_in_a_fixed_order() -> None:
    data = good()
    data["case_version"] = "2.0.0"
    data["families"][1]["family_id"] = "FAM_PUNTA"
    row(data, 0, 0)["flow_vph"] = {"min": 600, "max": 400}
    row(data, 0, 1)["composition"] = {"car": 0.5, "bus": 0.1}
    data["families"][0]["variants"] = MAX_VARIANTS + 1
    data["observation_end"] = data["observation_start"]
    assert [issue.rule_id for issue in issues_of(data)] == [
        "SPEC-C01",
        "SPEC-S02",
        "SPEC-C03",
        "SPEC-C04",
        "SPEC-C05",
        "SCEN-C05",
    ]


def test_the_issues_are_in_family_order() -> None:
    data = good()
    row(data, 1, 0)["flow_vph"] = {"min": 5, "max": 1}
    row(data, 0, 0)["flow_vph"] = {"min": 5, "max": 1}
    assert [issue.field for issue in issues_of(data)] == [
        "families[0].demand[0].flow_vph",
        "families[1].demand[0].flow_vph",
    ]


# --- aceptar y errores ------------------------------------------------------------------------


def test_accept_spec_raises_with_all_the_problems() -> None:
    data = good()
    data["case_id"] = "OTHER"
    row(data, 0, 0)["flow_vph"] = {"min": 600, "max": 400}
    with pytest.raises(SpecInvalidError) as raised:
        accept_spec(data, the_case())
    error = raised.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert error.field == "case_id"
    assert error.message.startswith("la especificación no es válida: SPEC-C01 en case_id: ")
    assert error.message.endswith("(y 1 más)")
    assert [issue.rule_id for issue in error.issues] == ["SPEC-C01", "SPEC-C03"]


def test_a_single_problem_has_no_extra_note() -> None:
    data = good()
    data["case_id"] = "OTHER"
    with pytest.raises(SpecInvalidError) as raised:
        accept_spec(data, the_case())
    assert "más" not in raised.value.message


def test_accept_spec_reports_a_structure_problem_without_a_field() -> None:
    with pytest.raises(SpecInvalidError) as raised:
        accept_spec([], the_case())
    assert raised.value.field is None
    assert "SPEC-S01: " in raised.value.message
    assert " en " not in raised.value.message.split("SPEC-S01")[1].split(":")[0]


def test_a_spec_error_without_problems_is_a_bug() -> None:
    with pytest.raises(ValueError, match="al menos un problema"):
        SpecInvalidError([])


def test_a_huge_number_of_problems_is_capped() -> None:
    data = good()
    data["families"][0]["demand"] = [
        {"movement_id": f"M{n}", "flow_vph": {"min": 0, "max": 0}, "composition": None}
        for n in range(MAX_ISSUES + 50)
    ]
    with pytest.raises(SpecInvalidError) as raised:
        accept_spec(data, the_case())
    issues = raised.value.issues
    assert len(issues) == MAX_ISSUES + 1
    assert "sin mostrar" in issues[-1].message


def test_the_case_is_not_changed_by_checking() -> None:
    case = the_case()
    before = case.model_dump_json()
    spec_issues(parse_spec(good()), case)
    assert case.model_dump_json() == before
