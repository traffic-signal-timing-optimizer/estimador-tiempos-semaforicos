"""Modelo de la partición, política y reglas SPLIT (DEV12 F1): contrato, QA14 y errores."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scenario_tools import scenarios_of
from semaforo.aprendizaje.splits import PROVISIONAL_POLICY, create_split
from semaforo.dominio.case import MAX_ISSUES, CaseIssue
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import Scenario
from semaforo.dominio.split import (
    PARTITIONS,
    Split,
    SplitInvalidError,
    SplitPolicy,
    accept_split,
    parse_policy,
    parse_split,
    split_issues,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "split.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "split.json"
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


SCENARIOS = scenarios_of(5)


def base() -> dict[str, Any]:
    """Una partición válida de los cinco grupos, como dato listo para estropear."""
    split = create_split(SCENARIOS, PROVISIONAL_POLICY, 7, "SPLIT_T")
    return copy.deepcopy(split.model_dump(mode="json"))


def issues_of(data: dict[str, Any], scenarios: list[Scenario] | None = None) -> list[CaseIssue]:
    return split_issues(parse_split(data), SCENARIOS if scenarios is None else scenarios)


def structure_issues(data: object) -> list[CaseIssue]:
    with pytest.raises(SplitInvalidError) as raised:
        parse_split(data)
    return list(raised.value.issues)


def group_of(data: dict[str, Any], partition: str) -> str:
    return next(a["group_id"] for a in data["assignments"] if a["partition"] == partition)


# --- contrato ---------------------------------------------------------------------------------


def test_the_model_has_the_published_contract_structure() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert without_documentation(Split.model_json_schema()) == without_documentation(published)


def test_the_reference_split_fixture_is_accepted_by_the_model() -> None:
    split = parse_split(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert split.split_id == "SPLIT_DEMO"
    assert split.frozen is True
    assert [a.partition for a in split.assignments] == ["train", "validation", "test"]


def test_the_partitions_are_the_three_of_the_contract() -> None:
    assert PARTITIONS == ("train", "validation", "test")


# --- estructura -------------------------------------------------------------------------------


def test_a_valid_split_has_no_problems() -> None:
    assert issues_of(base()) == []


@pytest.mark.parametrize("field", ["split_id", "policy", "seed", "frozen", "assignments"])
def test_a_missing_field_is_reported(field: str) -> None:
    data = base()
    del data[field]
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S01", field)
    assert "falta" in issue.message


@pytest.mark.parametrize("field", ["scenario_id", "group_id", "partition"])
def test_a_missing_assignment_field_is_reported(field: str) -> None:
    data = base()
    del data["assignments"][2][field]
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S01", f"assignments[2].{field}")


def test_an_unknown_field_is_rejected_at_every_level() -> None:
    top = base()
    top["extra"] = 1
    inner = base()
    inner["assignments"][0]["extra"] = 1
    for data, field in ((top, "extra"), (inner, "assignments[0].extra")):
        [issue] = structure_issues(data)
        assert (issue.rule_id, issue.field) == ("SPLIT-S01", field)
        assert "desconocido" in issue.message


def test_an_unknown_partition_is_rejected() -> None:
    data = base()
    data["assignments"][0]["partition"] = "dev"
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S01", "assignments[0].partition")
    assert "train" in issue.message


@pytest.mark.parametrize("seed", [-1, 1.5, "7", True, None])
def test_the_seed_must_be_a_non_negative_integer(seed: object) -> None:
    data = base()
    data["seed"] = seed
    assert structure_issues(data)[0].field == "seed"


@pytest.mark.parametrize("frozen", ["si", 1, None])
def test_frozen_must_be_a_boolean(frozen: object) -> None:
    data = base()
    data["frozen"] = frozen
    assert structure_issues(data)[0].field == "frozen"


def test_a_split_needs_at_least_one_assignment() -> None:
    data = base()
    data["assignments"] = []
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S01", "assignments")
    assert "al menos" in issue.message


def test_the_schema_version_must_be_the_published_one() -> None:
    data = base()
    data["schema_version"] = "2.0.0"
    assert structure_issues(data)[0].field == "schema_version"


def test_the_data_must_be_an_object() -> None:
    [issue] = structure_issues([])
    assert (issue.rule_id, issue.field) == ("SPLIT-S01", None)


@pytest.mark.parametrize("field", ["split_id", "assignments[0].scenario_id"])
@pytest.mark.parametrize("identifier", ["", " X", "X ", "A\tB", "A\N{ZERO WIDTH SPACE}"])
def test_an_identifier_cannot_be_empty_padded_or_invisible(field: str, identifier: str) -> None:
    data = base()
    if field == "split_id":
        data["split_id"] = identifier
    else:
        data["assignments"][0]["scenario_id"] = identifier
    [issue] = structure_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S02", field)


def test_all_the_structure_problems_come_together() -> None:
    data = base()
    del data["policy"]
    data["frozen"] = "si"
    data["assignments"][1]["partition"] = "dev"
    fields = sorted(str(issue.field) for issue in structure_issues(data))
    assert fields == ["assignments[1].partition", "frozen", "policy"]


# --- QA14: una partición por grupo, fuga y duplicados bloqueados -------------------------------


def test_mixing_a_variant_of_a_family_into_another_partition_is_blocked() -> None:
    data = base()
    first = next(a for a in data["assignments"] if a["partition"] == "train")
    first["partition"] = "test"
    issues = issues_of(data)
    assert [issue.rule_id for issue in issues] == ["SPLIT-C02"]
    assert issues[0].message == (
        f"el grupo «{first['group_id']}» está en varias particiones: train, test"
    )


def test_a_scenario_assigned_twice_is_blocked() -> None:
    data = base()
    data["assignments"].append(copy.deepcopy(data["assignments"][0]))
    issue = issues_of(data)[0]
    assert (issue.rule_id, issue.field) == ("SPLIT-C01", "assignments[20].scenario_id")
    assert "está asignado más de una vez" in issue.message


def test_a_scenario_left_without_partition_is_blocked() -> None:
    data = base()
    missing = data["assignments"].pop(3)["scenario_id"]
    [issue] = issues_of(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-C01", "assignments")
    assert issue.message == f"falta asignar el escenario «{missing}»"


def test_a_scenario_the_set_does_not_have_is_blocked() -> None:
    data = base()
    data["assignments"][0]["scenario_id"] = "FANTASMA"
    issues = issues_of(data)
    assert [(i.rule_id, i.field) for i in issues] == [
        ("SPLIT-C01", "assignments[0].scenario_id"),
        ("SPLIT-C01", "assignments"),
    ]
    assert "el conjunto no tiene el escenario «FANTASMA»" in issues[0].message


def test_an_assignment_with_the_wrong_group_is_blocked() -> None:
    data = base()
    wanted = data["assignments"][0]["group_id"]
    data["assignments"][0]["group_id"] = "OTRO"
    issue = issues_of(data)[0]
    assert (issue.rule_id, issue.field) == ("SPLIT-C03", "assignments[0].group_id")
    assert issue.message == (
        f"el escenario «{data['assignments'][0]['scenario_id']}» es del grupo «{wanted}» "
        "y la asignación dice «OTRO»"
    )


def test_an_assignment_naming_an_unknown_scenario_has_no_group_complaint() -> None:
    data = base()
    data["assignments"][0]["scenario_id"] = "FANTASMA"
    data["assignments"][0]["group_id"] = "LO_QUE_SEA"
    assert "SPLIT-C03" not in [issue.rule_id for issue in issues_of(data)]


def test_a_partition_without_groups_is_blocked() -> None:
    data = base()
    for assignment in data["assignments"]:
        assignment["partition"] = "train"
    issues = issues_of(data)
    assert [(i.rule_id, i.message) for i in issues] == [
        ("SPLIT-C04", "la partición «validation» no tiene ningún grupo"),
        ("SPLIT-C04", "la partición «test» no tiene ningún grupo"),
    ]


def test_a_split_that_is_not_frozen_is_blocked() -> None:
    data = base()
    data["frozen"] = False
    [issue] = issues_of(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-C05", "frozen")


def field_scenarios(sources: dict[str, str]) -> list[Scenario]:
    """Los cinco grupos como escenarios de campo, cada uno con la fuente que dice ``sources``."""
    return [
        s.model_copy(update={"origin": "field_derived", "source_ids": [sources[s.group_id]]})
        for s in SCENARIOS
    ]


def test_a_field_source_shared_by_two_partitions_is_blocked() -> None:
    data = base()
    train = group_of(data, "train")
    test = group_of(data, "test")
    sources = {f"FAM_{n:02d}": f"DIA_{n}" for n in range(1, 6)}
    sources[test] = sources[train]
    [issue] = issues_of(data, field_scenarios(sources))
    assert (issue.rule_id, issue.field) == ("SPLIT-C06", "assignments")
    assert issue.message == (
        f"la fuente de campo «{sources[train]}» aparece en varias particiones: train, test"
    )


def test_field_sources_that_are_not_shared_pass() -> None:
    data = base()
    sources = {f"FAM_{n:02d}": f"DIA_{n}" for n in range(1, 6)}
    assert issues_of(data, field_scenarios(sources)) == []


def test_synthetic_scenarios_may_share_their_example_source() -> None:
    assert {s.source_ids[0] for s in SCENARIOS} == {"SYNTHETIC_FIXTURE"}
    assert issues_of(base()) == []


def test_a_field_source_inside_one_partition_is_fine() -> None:
    data = base()
    same = {g: "DIA_UNICO" for g in ("FAM_01", "FAM_02", "FAM_03", "FAM_04", "FAM_05")}
    one = {a["group_id"] for a in data["assignments"] if a["partition"] == "train"}
    sources = {g: ("DIA_UNICO" if g in one else f"DIA_{g}") for g in same}
    assert issues_of(data, field_scenarios(sources)) == []


def test_the_problems_come_together_and_in_a_fixed_order() -> None:
    data = base()
    data["frozen"] = False
    data["assignments"].pop(0)
    data["assignments"][0]["group_id"] = "OTRO"
    train_group = group_of(data, "train")
    for assignment in data["assignments"]:
        if assignment["group_id"] == train_group:
            assignment["partition"] = "test"
            break
    for assignment in data["assignments"]:
        if assignment["partition"] == "validation":
            assignment["partition"] = "test"
    rules = [issue.rule_id for issue in issues_of(data)]
    assert rules == sorted(rules)
    assert set(rules) >= {"SPLIT-C01", "SPLIT-C03", "SPLIT-C04", "SPLIT-C05"}


# --- aceptar y errores ------------------------------------------------------------------------


def test_accept_split_returns_the_split_when_everything_fits() -> None:
    data = base()
    assert accept_split(data, SCENARIOS) == parse_split(data)


def test_accept_split_raises_with_all_the_problems() -> None:
    data = base()
    data["frozen"] = False
    data["assignments"][0]["group_id"] = "OTRO"
    with pytest.raises(SplitInvalidError) as raised:
        accept_split(data, SCENARIOS)
    error = raised.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert error.message.startswith(
        "la partición no es válida: SPLIT-C03 en assignments[0].group_id: "
    )
    assert error.message.endswith("(y 1 más)")
    assert [issue.rule_id for issue in error.issues] == ["SPLIT-C03", "SPLIT-C05"]


def test_a_single_problem_has_no_extra_note() -> None:
    data = base()
    data["frozen"] = False
    with pytest.raises(SplitInvalidError) as raised:
        accept_split(data, SCENARIOS)
    assert "más" not in raised.value.message


def test_an_error_without_problems_is_a_bug() -> None:
    with pytest.raises(ValueError, match="al menos un problema"):
        SplitInvalidError([])


def test_a_huge_number_of_problems_is_capped() -> None:
    data = base()
    data["assignments"] = [
        {"scenario_id": f"X{n}", "group_id": "G", "partition": "train"}
        for n in range(MAX_ISSUES + 50)
    ]
    with pytest.raises(SplitInvalidError) as raised:
        accept_split(data, SCENARIOS)
    assert len(raised.value.issues) == MAX_ISSUES + 1
    assert "sin mostrar" in raised.value.issues[-1].message


def test_checking_does_not_change_the_split_or_the_scenarios() -> None:
    split = parse_split(base())
    before = (split.model_dump_json(), [s.model_dump_json() for s in SCENARIOS])
    split_issues(split, SCENARIOS)
    assert (split.model_dump_json(), [s.model_dump_json() for s in SCENARIOS]) == before


# --- política ---------------------------------------------------------------------------------


def policy_data() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "policy_id": "family_holdout",
        "proportions": {"train": 0.6, "validation": 0.2, "test": 0.2},
    }


def policy_issues(data: object) -> list[CaseIssue]:
    with pytest.raises(SplitInvalidError) as raised:
        parse_policy(data)
    return list(raised.value.issues)


def test_a_valid_policy_is_accepted_and_is_not_provisional_by_default() -> None:
    policy = parse_policy(policy_data())
    assert (policy.policy_id, policy.provisional) == ("family_holdout", False)
    assert (policy.proportions.train, policy.proportions.validation, policy.proportions.test) == (
        0.6,
        0.2,
        0.2,
    )


def test_the_provisional_mark_can_be_written_in_the_file() -> None:
    data = policy_data()
    data["provisional"] = True
    assert parse_policy(data).provisional is True


def test_the_built_in_policy_is_provisional() -> None:
    assert PROVISIONAL_POLICY.provisional is True
    assert PROVISIONAL_POLICY.policy_id == "family_holdout"
    assert isinstance(PROVISIONAL_POLICY, SplitPolicy)


@pytest.mark.parametrize("field", ["policy_id", "proportions"])
def test_a_missing_policy_field_is_reported(field: str) -> None:
    data = policy_data()
    del data[field]
    [issue] = policy_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S01", field)


@pytest.mark.parametrize("part", ["train", "validation", "test"])
@pytest.mark.parametrize("value", [0, 1, -0.2, 1.5, float("nan")])
def test_each_proportion_must_be_strictly_between_zero_and_one(part: str, value: float) -> None:
    data = policy_data()
    data["proportions"][part] = value
    fields = [issue.field for issue in policy_issues(data)]
    assert fields == [f"proportions.{part}"]


def test_the_proportions_must_add_up_to_one() -> None:
    data = policy_data()
    data["proportions"] = {"train": 0.5, "validation": 0.2, "test": 0.2}
    [issue] = policy_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-P01", "proportions")
    assert issue.message == "las proporciones suman 0.9 y deben sumar 1"


def test_a_sum_inside_the_tolerance_is_accepted() -> None:
    data = policy_data()
    data["proportions"] = {"train": 0.1 + 0.2, "validation": 0.3, "test": 0.4}
    parse_policy(data)


def test_an_unknown_policy_field_is_rejected() -> None:
    data = policy_data()
    data["extra"] = 1
    [issue] = policy_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S01", "extra")


@pytest.mark.parametrize("identifier", ["", "-a", "a b", "a/b", "../x", "a" * 33, "ñ"])
def test_the_policy_name_must_be_a_safe_name(identifier: str) -> None:
    data = policy_data()
    data["policy_id"] = identifier
    [issue] = policy_issues(data)
    assert (issue.rule_id, issue.field) == ("SPLIT-S02", "policy_id")


def test_the_policy_must_be_an_object() -> None:
    assert policy_issues([])[0].field is None
