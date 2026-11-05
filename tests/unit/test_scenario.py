"""Modelo del escenario (DEV06 F1): contrato, estructura SCEN-S y consistencia SCEN-C."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from semaforo.dominio.case import MAX_ISSUES, Case, CaseIssue, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import (
    Scenario,
    ScenarioInvalidError,
    accept_scenario,
    evidence_origin,
    parse_scenario,
    scenario_issues,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
SCHEMA = ROOT / "schemas" / "scenario.schema.json"
DOCUMENTATION_KEYS = frozenset({"description", "title", "$schema"})

type Json = dict[str, Json] | list[Json] | str | int | float | bool | None


def without_documentation(node: Json) -> Json:
    """El esquema sin textos de documentación; el resto se compara tal cual."""
    if isinstance(node, dict):
        return {
            key: without_documentation(value)
            for key, value in node.items()
            if key not in DOCUMENTATION_KEYS
        }
    if isinstance(node, list):
        return [without_documentation(item) for item in node]
    return node


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def good() -> dict[str, Any]:
    """Copia del escenario de ejemplo, lista para estropear."""
    return copy.deepcopy(load("scenario.json"))


def case_data() -> dict[str, Any]:
    return copy.deepcopy(load("case.json"))


def the_case() -> Case:
    return parse_case(case_data())


def issues_of(data: dict[str, Any], case: Case | None = None) -> list[CaseIssue]:
    return scenario_issues(parse_scenario(data), case or the_case())


def only_issue(data: dict[str, Any], case: Case | None = None) -> CaseIssue:
    issues = issues_of(data, case)
    assert len(issues) == 1, issues
    return issues[0]


def structure_issues(data: object) -> list[CaseIssue]:
    with pytest.raises(ScenarioInvalidError) as raised:
        parse_scenario(data)
    return list(raised.value.issues)


# --- contrato -------------------------------------------------------------------------------


def test_the_model_has_the_published_contract_structure() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert without_documentation(Scenario.model_json_schema()) == without_documentation(published)


def test_the_published_contract_names_the_same_required_fields() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(Scenario.model_json_schema()["required"]) == set(published["required"])


@pytest.mark.parametrize(
    "name", ["scenario.json", "scenario_test.json", "scenario_validation.json"]
)
def test_the_reference_scenarios_are_accepted(name: str) -> None:
    scenario = accept_scenario(load(name), the_case())
    assert scenario.case_id == "SYNTHETIC_DEMO"
    assert scenario.demand_artifact is None


# --- estructura -----------------------------------------------------------------------------


def test_the_reference_scenario_has_its_values() -> None:
    scenario = parse_scenario(good())
    assert (scenario.scenario_id, scenario.origin, scenario.demand_seed) == (
        "SCENARIO_DEMO_001",
        "synthetic",
        100,
    )
    assert (scenario.warmup_s, scenario.measure_s, scenario.drain_max_s) == (0, 900, 900)
    assert [row.movement_id for row in scenario.request.demand] == ["N_S", "E_W"]
    assert scenario.request.demand[0].composition == {"car": 0.9, "bus": 0.1}


@pytest.mark.parametrize(
    "field",
    [
        "scenario_id",
        "case_id",
        "request",
        "warmup_s",
        "measure_s",
        "demand_seed",
        "demand_artifact",
    ],
)
def test_a_missing_field_is_reported_with_its_name(field: str) -> None:
    data = good()
    del data[field]
    issues = structure_issues(data)
    assert [(issue.rule_id, issue.field) for issue in issues] == [("SCEN-S01", field)]
    assert "falta" in issues[0].message


def test_an_unknown_field_is_rejected() -> None:
    data = good()
    data["extra"] = 1
    assert [(issue.rule_id, issue.field) for issue in structure_issues(data)] == [
        ("SCEN-S01", "extra")
    ]


def test_an_unknown_field_inside_a_demand_row_is_rejected() -> None:
    data = good()
    data["request"]["demand"][0]["extra"] = 1
    assert [issue.field for issue in structure_issues(data)] == ["request.demand[0].extra"]


def test_a_flow_given_as_text_is_not_converted() -> None:
    data = good()
    data["request"]["demand"][0]["flow_vph"] = "400"
    assert [issue.field for issue in structure_issues(data)] == ["request.demand[0].flow_vph"]


def test_a_seed_with_decimals_is_rejected() -> None:
    data = good()
    data["demand_seed"] = 1.5
    assert [issue.field for issue in structure_issues(data)] == ["demand_seed"]


def test_a_boolean_is_not_a_seed() -> None:
    data = good()
    data["demand_seed"] = True
    assert [issue.field for issue in structure_issues(data)] == ["demand_seed"]


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_flow_that_is_not_finite_is_rejected(value: float) -> None:
    data = good()
    data["request"]["demand"][0]["flow_vph"] = value
    assert [issue.field for issue in structure_issues(data)] == ["request.demand[0].flow_vph"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("warmup_s", -1),
        ("measure_s", 0),
        ("measure_s", -5),
        ("drain_max_s", -1),
        ("demand_seed", -1),
    ],
)
def test_times_and_seed_outside_their_limits_are_rejected(field: str, value: float) -> None:
    data = good()
    data[field] = value
    assert [issue.field for issue in structure_issues(data)] == [field]


def test_a_negative_flow_is_rejected() -> None:
    data = good()
    data["request"]["demand"][1]["flow_vph"] = -1
    assert [issue.field for issue in structure_issues(data)] == ["request.demand[1].flow_vph"]


def test_zero_flow_and_zero_warmup_are_accepted() -> None:
    data = good()
    data["request"]["demand"][1]["flow_vph"] = 0
    data["request"]["demand"][1]["composition"] = None
    assert issues_of(data) == []


@pytest.mark.parametrize("field", ["source_ids", "demand"])
def test_the_request_needs_at_least_one_source_and_one_demand_row(field: str) -> None:
    data = good()
    data["request"][field] = []
    assert [issue.field for issue in structure_issues(data)] == [f"request.{field}"]


def test_the_scenario_may_have_no_sources() -> None:
    data = good()
    data["source_ids"] = []
    assert issues_of(data) == []


def test_an_empty_identifier_is_scen_s02() -> None:
    data = good()
    data["scenario_id"] = ""
    assert [(issue.rule_id, issue.field) for issue in structure_issues(data)] == [
        ("SCEN-S02", "scenario_id")
    ]


def test_an_identifier_with_spaces_at_the_ends_is_scen_s02() -> None:
    data = good()
    data["request"]["demand"][0]["movement_id"] = " N_S"
    assert [(issue.rule_id, issue.field) for issue in structure_issues(data)] == [
        ("SCEN-S02", "request.demand[0].movement_id")
    ]


def test_a_malformed_version_is_scen_s03() -> None:
    data = good()
    data["case_version"] = "1.0"
    assert [(issue.rule_id, issue.field) for issue in structure_issues(data)] == [
        ("SCEN-S03", "case_version")
    ]


def test_the_schema_version_is_fixed() -> None:
    data = good()
    data["schema_version"] = "2.0.0"
    assert [issue.field for issue in structure_issues(data)] == ["schema_version"]


def test_a_demand_artifact_needs_a_valid_hash() -> None:
    data = good()
    data["demand_artifact"] = {"artifact_id": "demanda", "path": "demanda.rou.xml", "sha256": "xyz"}
    assert [issue.field for issue in structure_issues(data)] == ["demand_artifact.sha256"]


def test_a_scenario_that_is_not_an_object_is_rejected() -> None:
    issues = structure_issues([1, 2])
    assert [(issue.rule_id, issue.field) for issue in issues] == [("SCEN-S01", None)]


def test_no_structure_rule_names_the_case_contract() -> None:
    data = good()
    data["scenario_id"] = ""
    data["case_version"] = "1"
    data["extra"] = 1
    assert {issue.rule_id for issue in structure_issues(data)} == {
        "SCEN-S01",
        "SCEN-S02",
        "SCEN-S03",
    }


# --- SCEN-C01 -------------------------------------------------------------------------------


def test_a_scenario_of_another_case_is_scen_c01() -> None:
    data = good()
    data["case_id"] = "OTHER"
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C01", "case_id")
    assert "«SYNTHETIC_DEMO»" in issue.message
    assert "«OTHER»" in issue.message


def test_a_scenario_of_another_case_version_is_scen_c01() -> None:
    data = good()
    data["case_version"] = "1.0.1"
    assert (only_issue(data).rule_id, only_issue(data).field) == ("SCEN-C01", "case_version")


def test_a_scenario_and_its_request_must_agree_on_the_origin() -> None:
    data = good()
    data["origin"] = "field_derived"
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C01", "request.origin")
    assert "«field_derived»" in issue.message
    assert "«synthetic»" in issue.message


def test_a_field_derived_scenario_agrees_with_a_field_request() -> None:
    data = good()
    data["origin"] = "field_derived"
    data["request"]["origin"] = "field"
    assert issues_of(data) == []


def test_a_synthetic_scenario_may_run_on_a_field_case() -> None:
    case = case_data()
    case["origin"] = "field"
    assert issues_of(good(), parse_case(case)) == []


def test_a_synthetic_scenario_request_must_not_say_field() -> None:
    data = good()
    data["request"]["origin"] = "field"
    assert only_issue(data).field == "request.origin"


def test_a_request_of_another_case_is_reported_on_the_request() -> None:
    data = good()
    data["request"]["case_id"] = "OTHER"
    data["request"]["case_version"] = "2.0.0"
    assert [(issue.rule_id, issue.field) for issue in issues_of(data)] == [
        ("SCEN-C01", "request.case_id"),
        ("SCEN-C01", "request.case_version"),
    ]


# --- SCEN-C02 -------------------------------------------------------------------------------


def test_a_missing_demand_row_is_not_a_zero() -> None:
    data = good()
    del data["request"]["demand"][1]
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C02", "request.demand")
    assert "«E_W»" in issue.message
    assert "no es un cero" in issue.message


def test_a_demand_row_of_an_unknown_movement_is_rejected() -> None:
    data = good()
    data["request"]["demand"].append(
        {"movement_id": "X_Y", "flow_vph": 10, "composition": {"car": 1.0}}
    )
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C02", "request.demand[2].movement_id")
    assert "«X_Y»" in issue.message


def test_a_repeated_demand_row_is_rejected_once() -> None:
    data = good()
    data["request"]["demand"].append(copy.deepcopy(data["request"]["demand"][0]))
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C02", "request.demand[2].movement_id")
    assert "repetido" in issue.message


def test_an_unknown_movement_does_not_hide_a_missing_one() -> None:
    data = good()
    data["request"]["demand"][1]["movement_id"] = "X_Y"
    assert [(issue.field, "«E_W»" in issue.message) for issue in issues_of(data)] == [
        ("request.demand[1].movement_id", False),
        ("request.demand", True),
    ]


# --- SCEN-C03 -------------------------------------------------------------------------------


def test_a_flow_without_composition_is_scen_c03() -> None:
    data = good()
    data["request"]["demand"][1]["composition"] = None
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C03", "request.demand[1].composition")
    assert "200" in issue.message


def test_a_zero_flow_may_have_no_composition() -> None:
    data = good()
    data["request"]["demand"][1].update(flow_vph=0, composition=None)
    assert issues_of(data) == []


def test_a_class_the_case_does_not_have_is_rejected() -> None:
    data = good()
    data["request"]["demand"][0]["composition"] = {"car": 0.9, "tram": 0.1}
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C03", "request.demand[0].composition")
    assert "«tram»" in issue.message


def test_a_share_above_one_is_rejected_with_its_field() -> None:
    data = good()
    data["request"]["demand"][0]["composition"] = {"car": 1.5, "bus": -0.5}
    assert [(issue.field, issue.rule_id) for issue in issues_of(data)] == [
        ("request.demand[0].composition.car", "SCEN-C03"),
        ("request.demand[0].composition.bus", "SCEN-C03"),
    ]


def test_shares_that_do_not_add_up_to_one_are_rejected() -> None:
    data = good()
    data["request"]["demand"][0]["composition"] = {"car": 0.8, "bus": 0.1}
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C03", "request.demand[0].composition")
    assert "0.9" in issue.message


def test_shares_that_add_up_to_one_within_rounding_are_accepted() -> None:
    data = good()
    data["request"]["demand"][0]["composition"] = {"car": 0.1 + 0.2, "bus": 0.7}
    assert issues_of(data) == []


def test_shares_that_miss_one_by_a_little_more_than_rounding_are_rejected() -> None:
    data = good()
    data["request"]["demand"][0]["composition"] = {"car": 0.9, "bus": 0.100001}
    assert only_issue(data).rule_id == "SCEN-C03"
    data["request"]["demand"][0]["composition"] = {"car": 0.9, "bus": 0.099999}
    assert only_issue(data).rule_id == "SCEN-C03"


def test_a_class_left_out_counts_as_zero() -> None:
    data = good()
    data["request"]["demand"][0]["composition"] = {"car": 1.0}
    assert issues_of(data) == []


def test_a_share_of_exactly_one_or_zero_is_accepted() -> None:
    data = good()
    data["request"]["demand"][0]["composition"] = {"car": 0.0, "bus": 1.0}
    assert issues_of(data) == []


# --- SCEN-C04 -------------------------------------------------------------------------------


def test_a_flow_above_the_movement_domain_is_scen_c04() -> None:
    data = good()
    data["request"]["demand"][0]["flow_vph"] = 1200.5
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C04", "request.demand[0].flow_vph")
    assert "«N_S»" in issue.message
    assert "1200" in issue.message


def test_a_flow_at_the_edge_of_the_domain_is_accepted() -> None:
    data = good()
    data["request"]["demand"][0]["flow_vph"] = 1200
    data["request"]["demand"][1]["flow_vph"] = 0
    data["request"]["demand"][1]["composition"] = None
    assert issues_of(data) == []


def test_a_flow_within_rounding_noise_of_the_domain_edge_is_accepted() -> None:
    case = case_data()
    case["movements"][0]["flow_domain_vph"] = {"min": 100, "max": 1200}
    data = good()
    data["request"]["demand"][0]["flow_vph"] = 100 - 1e-10
    assert issues_of(data, parse_case(case)) == []
    data["request"]["demand"][0]["flow_vph"] = 1200 + 1e-10
    assert issues_of(data, parse_case(case)) == []


def test_a_flow_below_the_domain_minimum_is_scen_c04() -> None:
    case = case_data()
    case["movements"][0]["flow_domain_vph"] = {"min": 100, "max": 1200}
    data = good()
    data["request"]["demand"][0]["flow_vph"] = 50
    issue = only_issue(data, parse_case(case))
    assert (issue.rule_id, issue.field) == ("SCEN-C04", "request.demand[0].flow_vph")


def test_the_flow_of_an_unknown_movement_is_not_checked_against_a_domain() -> None:
    data = good()
    data["request"]["demand"][1]["movement_id"] = "X_Y"
    data["request"]["demand"][1]["flow_vph"] = 99999
    assert {issue.rule_id for issue in issues_of(data)} == {"SCEN-C02"}


# --- SCEN-C05 -------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["observation_start", "observation_end"])
@pytest.mark.parametrize("text", ["ayer", "2026-10-18T08:00:00", "2026-10-18"])
def test_an_observation_instant_needs_iso_8601_with_a_time_zone(field: str, text: str) -> None:
    data = good()
    data["request"][field] = text
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C05", f"request.{field}")
    assert f"«{text}»" in issue.message


def test_an_observation_that_ends_before_it_starts_is_rejected() -> None:
    data = good()
    data["request"]["observation_end"] = "2026-10-18T07:00:00-05:00"
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C05", "request.observation_end")
    assert "posterior" in issue.message


def test_an_observation_with_the_same_start_and_end_is_rejected() -> None:
    data = good()
    data["request"]["observation_end"] = data["request"]["observation_start"]
    assert only_issue(data).rule_id == "SCEN-C05"


def test_observation_instants_in_different_zones_are_compared_as_instants() -> None:
    data = good()
    data["request"]["observation_start"] = "2026-10-18T08:00:00-05:00"
    data["request"]["observation_end"] = "2026-10-18T14:00:00+02:00"  # 07:00 en Lima
    assert only_issue(data).rule_id == "SCEN-C05"
    data["request"]["observation_end"] = "2026-10-18T13:15:00Z"  # 08:15 en Lima
    assert issues_of(data) == []


@pytest.mark.parametrize("field", ["warmup_s", "measure_s", "drain_max_s"])
def test_a_time_that_is_not_a_multiple_of_the_tick_is_scen_c05(field: str) -> None:
    case = case_data()
    case["tick_s"] = 2
    data = good()
    data["warmup_s"] = 100
    data["measure_s"] = 900
    data["drain_max_s"] = 900
    data[field] = 101
    issue = only_issue(data, parse_case(case))
    assert (issue.rule_id, issue.field) == ("SCEN-C05", field)
    assert "múltiplo del tick" in issue.message


def test_times_in_tenths_of_a_second_are_aligned_with_a_tick_of_a_tenth() -> None:
    case = case_data()
    case["tick_s"] = 0.1
    data = good()
    data["warmup_s"] = 0.3
    data["measure_s"] = 900.7
    assert issues_of(data, parse_case(case)) == []


# --- SCEN-C06 -------------------------------------------------------------------------------


def test_another_boundary_policy_is_scen_c06() -> None:
    data = good()
    data["boundary_policy_id"] = "OTRA"
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("SCEN-C06", "boundary_policy_id")
    assert "«DEMO_EMPTY_START_FIXED_ROUTES»" in issue.message
    assert "«OTRA»" in issue.message


# --- conjunto -------------------------------------------------------------------------------


def test_the_issues_come_in_a_fixed_order_by_rule() -> None:
    data = good()
    data["boundary_policy_id"] = "OTRA"
    data["measure_s"] = 900.5
    data["request"]["demand"][0]["flow_vph"] = 5000
    data["request"]["demand"][1]["composition"] = {"car": 0.5}
    data["case_id"] = "OTHER"
    assert [issue.rule_id for issue in issues_of(data)] == [
        "SCEN-C01",
        "SCEN-C03",
        "SCEN-C04",
        "SCEN-C05",
        "SCEN-C06",
    ]


def test_accepting_a_good_scenario_returns_it() -> None:
    scenario = accept_scenario(good(), the_case())
    assert isinstance(scenario, Scenario)


def test_accepting_a_scenario_with_a_structure_problem_reports_it() -> None:
    data = good()
    del data["request"]
    with pytest.raises(ScenarioInvalidError) as raised:
        accept_scenario(data, the_case())
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "request"
    assert str(raised.value).startswith("INPUT_SCHEMA: el escenario no es válido: SCEN-S01")


def test_accepting_an_inconsistent_scenario_reports_every_problem() -> None:
    data = good()
    data["case_id"] = "OTHER"
    data["boundary_policy_id"] = "OTRA"
    with pytest.raises(ScenarioInvalidError) as raised:
        accept_scenario(data, the_case())
    error = raised.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert [issue.rule_id for issue in error.issues] == ["SCEN-C01", "SCEN-C06"]
    assert error.field == "case_id"
    assert error.message == (
        "el escenario no es válido: SCEN-C01 en case_id: "
        "el caso es «SYNTHETIC_DEMO» y el escenario dice «OTHER» (y 1 más)"
    )


def test_a_single_problem_has_no_and_n_more_suffix() -> None:
    data = good()
    data["boundary_policy_id"] = "OTRA"
    with pytest.raises(ScenarioInvalidError) as raised:
        accept_scenario(data, the_case())
    assert "más)" not in raised.value.message


def test_a_problem_about_the_whole_scenario_has_no_field_in_the_message() -> None:
    error = ScenarioInvalidError([CaseIssue("SCEN-C02", None, "algo")])
    assert error.field is None
    assert error.message == "el escenario no es válido: SCEN-C02: algo"


def test_an_invalid_scenario_error_needs_at_least_one_problem() -> None:
    with pytest.raises(ValueError, match="al menos un problema"):
        ScenarioInvalidError([])


def test_many_problems_are_capped_with_a_final_count() -> None:
    data = good()
    data["request"]["demand"] = [
        {"movement_id": f"X{i}", "flow_vph": 1, "composition": {"car": 1.0}}
        for i in range(MAX_ISSUES + 20)
    ]
    with pytest.raises(ScenarioInvalidError) as raised:
        accept_scenario(data, the_case())
    issues = raised.value.issues
    assert len(issues) == MAX_ISSUES + 1
    assert "sin mostrar" in issues[-1].message


@pytest.mark.parametrize(
    ("case_origin", "demand_origin", "expected"),
    [
        ("synthetic", "synthetic", "synthetic"),
        ("field", "synthetic", "synthetic"),
        ("synthetic", "field", "synthetic"),
        ("field", "field", "field"),
    ],
)
def test_only_a_real_case_with_a_real_demand_is_field_evidence(
    case_origin: str, demand_origin: str, expected: str
) -> None:
    """Auditoría A03: una demanda supuesta sobre un caso real sigue siendo sintética."""
    assert evidence_origin(case_origin, demand_origin) == expected
