"""Modelo del caso (DEV02, F1): reglas de estructura CASE-S01 a S03, sin leer archivos."""

import copy
import json
import unicodedata
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from semaforo.dominio.case import MAX_ISSUES, Case, CaseInvalidError, CaseIssue, parse_case
from semaforo.dominio.errors import ErrorCode

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "case.json"
REQUIRED = [
    "case_id",
    "case_version",
    "origin",
    "description",
    "representation_status",
    "network",
    "tick_s",
    "cycle_s",
    "vehicle_classes",
    "movements",
    "slots",
    "green_groups",
    "boundary_policy_id",
    "restrictions_evidence",
]


def good() -> dict[str, Any]:
    """Copia del caso de ejemplo, lista para estropear."""
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def issues_of(data: object) -> list[CaseIssue]:
    with pytest.raises(CaseInvalidError) as raised:
        parse_case(data)
    return list(raised.value.issues)


def only_issue(data: object) -> CaseIssue:
    issues = issues_of(data)
    assert len(issues) == 1, issues
    return issues[0]


def test_the_reference_case_is_accepted() -> None:
    case = parse_case(good())
    assert isinstance(case, Case)
    assert (case.case_id, case.case_version, case.origin) == (
        "SYNTHETIC_DEMO",
        "1.0.0",
        "synthetic",
    )
    assert [slot.id for slot in case.slots] == ["s1", "s2", "s3", "s4", "s5", "s6"]
    assert case.network is None


def test_a_case_survives_a_dump_and_a_new_parse() -> None:
    case = parse_case(good())
    assert parse_case(case.model_dump()) == case


def test_a_case_with_a_network_is_accepted() -> None:
    data = good()
    data["network"] = {"artifact_id": "red", "path": "osm.net.xml.gz", "sha256": "a" * 64}
    assert parse_case(data).network is not None


@pytest.mark.parametrize("name", REQUIRED)
def test_a_missing_field_is_reported_with_its_name(name: str) -> None:
    data = good()
    del data[name]
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("CASE-S01", name)
    assert issue.message == "falta el campo obligatorio"


def test_the_schema_version_is_optional_but_only_v1_is_accepted() -> None:
    data = good()
    data["schema_version"] = "1.0.0"
    assert parse_case(data).schema_version == "1.0.0"
    data["schema_version"] = "2.0.0"
    issue = only_issue(data)
    assert issue.field == "schema_version"
    assert "'1.0.0'" in issue.message


@pytest.mark.parametrize(
    ("path", "field"),
    [
        (("extra",), "extra"),
        (("slots", 0, "extra"), "slots[0].extra"),
        (("movements", 1, "flow_domain_vph", "extra"), "movements[1].flow_domain_vph.extra"),
        (("cycle_s", "extra"), "cycle_s.extra"),
    ],
)
def test_an_unknown_field_is_rejected_at_any_depth(path: tuple[str | int, ...], field: str) -> None:
    data = good()
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = 1
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("CASE-S01", field)
    assert "desconocido" in issue.message


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("tick_s",), "1", "debe ser un número"),
        (("tick_s",), True, "debe ser un número"),
        (("case_id",), 7, "debe ser un texto"),
        (("movements", 0, "link_indices", 0), 1.0, "debe ser un número entero"),
        (("movements", 0, "link_indices", 0), True, "debe ser un número entero"),
        (("movements",), {"id": "x"}, "debe ser una lista"),
        (("cycle_s",), [40, 100], "debe ser un objeto"),
        (("restrictions_evidence", 0), 5, "debe ser un texto"),
    ],
)
def test_types_are_exact_and_nothing_is_converted(
    path: tuple[str | int, ...], value: object, message: str
) -> None:
    data = good()
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    issue = only_issue(data)
    assert issue.rule_id == "CASE-S01"
    assert issue.message == message


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_are_rejected(value: float) -> None:
    data = good()
    data["tick_s"] = value
    issue = only_issue(data)
    assert issue.field == "tick_s"
    assert "finito" in issue.message


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("tick_s",), 0, "debe ser mayor que 0"),
        (("tick_s",), -1, "debe ser mayor que 0"),
        (("cycle_s", "min"), -1, "debe ser mayor o igual que 0"),
        (("slots", 0, "min_s"), 0, "debe ser mayor que 0"),
        (("slots", 0, "max_s"), -5, "debe ser mayor que 0"),
        (("green_groups", 0, "max_s"), 0, "debe ser mayor que 0"),
        (("movements", 0, "flow_domain_vph", "max"), -1, "debe ser mayor o igual que 0"),
    ],
)
def test_numeric_limits_of_the_contract(
    path: tuple[str | int, ...], value: float, message: str
) -> None:
    data = good()
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    assert only_issue(data).message == message


def test_a_group_may_have_a_minimum_of_zero() -> None:
    data = good()
    data["green_groups"][0]["min_s"] = 0
    assert parse_case(data).green_groups[0].min_s == 0


@pytest.mark.parametrize("name", ["vehicle_classes", "movements", "slots", "green_groups"])
def test_the_main_lists_cannot_be_empty(name: str) -> None:
    data = good()
    data[name] = []
    issue = only_issue(data)
    assert (issue.field, issue.message) == (name, "debe tener al menos 1 elemento(s)")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("origin",), "real"),
        (("representation_status",), "ok"),
        (("slots", 0, "kind"), "dynamic"),
        (("green_groups", 0, "purpose"), "bike"),
    ],
)
def test_values_outside_the_allowed_list_are_rejected(
    path: tuple[str | int, ...], value: str
) -> None:
    data = good()
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    issue = only_issue(data)
    assert issue.message.startswith("valor no admitido; valores posibles: ")
    assert " o " in issue.message or issue.message.endswith("'")


@pytest.mark.parametrize("state", ["", "XY", "G r", "gx"])
def test_a_signal_state_uses_only_the_sumo_letters(state: str) -> None:
    data = good()
    data["slots"][0]["states"][0]["state"] = state
    issue = only_issue(data)
    assert issue.field == "slots[0].states[0].state"
    assert issue.message.startswith("no cumple el formato")


def test_the_network_hash_must_be_sha256() -> None:
    data = good()
    data["network"] = {"artifact_id": "red", "path": "osm.net.xml.gz", "sha256": "ABC"}
    assert only_issue(data).field == "network.sha256"


@pytest.mark.parametrize(
    "field_path",
    [
        ("case_id",),
        ("boundary_policy_id",),
        ("vehicle_classes", 0),
        ("movements", 0, "id"),
        ("movements", 0, "approach_id"),
        ("movements", 0, "tls_id"),
        ("movements", 0, "incoming_lanes", 0),
        ("movements", 0, "outgoing_edges", 0),
        ("slots", 0, "id"),
        ("slots", 0, "states", 0, "tls_id"),
        ("green_groups", 0, "id"),
        ("green_groups", 0, "slot_ids", 0),
    ],
)
@pytest.mark.parametrize(
    "bad",
    ["", "   ", " x", "x ", "a\tb", "a\nb", "a\x00b", "a\u200bb", "﻿x"],
    ids=["empty", "blank", "lead", "trail", "tab", "newline", "nul", "zero-width", "bom"],
)
def test_identifiers_are_clean_text_everywhere(field_path: tuple[str | int, ...], bad: str) -> None:
    data = good()
    target: Any = data
    for step in field_path[:-1]:
        target = target[step]
    target[field_path[-1]] = bad
    issues = [issue for issue in issues_of(data) if issue.rule_id == "CASE-S02"]
    assert len(issues) == 1
    assert issues[0].message.startswith("el identificador no puede estar vacío")


@pytest.mark.parametrize("name", ["Los Frutales", "Ñandú-1", "cruce_Javier Prado/1", "x"])
def test_identifiers_may_have_inner_spaces_and_accents(name: str) -> None:
    data = good()
    data["case_id"] = name
    assert parse_case(data).case_id == name


@given(st.text())
def test_an_accepted_identifier_is_always_clean(text: str) -> None:
    data = good()
    data["case_id"] = text
    try:
        case = parse_case(data)
    except CaseInvalidError:
        return
    assert case.case_id == case.case_id.strip() != ""
    assert all(unicodedata.category(c) not in {"Cc", "Cf"} for c in case.case_id)


@pytest.mark.parametrize("version", ["1.0.0", "0.0.1", "0.12.3", "10.20.30", "2.0.0"])
def test_valid_versions(version: str) -> None:
    data = good()
    data["case_version"] = version
    assert parse_case(data).case_version == version


@pytest.mark.parametrize(
    "version",
    ["1.0", "1", "1.0.0.0", "v1.0.0", "01.0.0", "1.00.0", "1.0.0-beta", " 1.0.0", "1.0.x", ""],
)
def test_invalid_versions(version: str) -> None:
    data = good()
    data["case_version"] = version
    issue = only_issue(data)
    assert (issue.rule_id, issue.field) == ("CASE-S03", "case_version")
    assert "MAYOR.MENOR.PARCHE" in issue.message


def test_every_problem_is_reported_in_one_pass() -> None:
    data = good()
    del data["tick_s"]
    data["case_id"] = " x"
    data["slots"][1]["max_s"] = 0
    data["case_version"] = "1.0"
    issues = issues_of(data)
    assert {(issue.rule_id, issue.field) for issue in issues} == {
        ("CASE-S02", "case_id"),
        ("CASE-S03", "case_version"),
        ("CASE-S01", "tick_s"),
        ("CASE-S01", "slots[1].max_s"),
    }


def test_the_error_carries_input_schema_and_the_first_problem() -> None:
    data = good()
    data["case_id"] = ""
    data["tick_s"] = 0
    with pytest.raises(CaseInvalidError) as raised:
        parse_case(data)
    error = raised.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert error.field == "case_id"
    assert str(error).startswith("INPUT_SCHEMA: el caso no es válido: CASE-S02 en case_id:")
    assert str(error).endswith("(y 1 más)")


@pytest.mark.parametrize("data", [[], "caso", 7, None])
def test_the_content_must_be_an_object(data: object) -> None:
    issue = only_issue(data)
    assert (issue.rule_id, issue.field, issue.message) == ("CASE-S01", None, "debe ser un objeto")


def test_a_flood_of_problems_is_capped() -> None:
    data = good()
    data["slots"] = [{"id": " "} for _ in range(MAX_ISSUES)]
    issues = issues_of(data)
    assert len(issues) == MAX_ISSUES + 1
    assert issues[-1].field is None
    assert issues[-1].message.endswith("más sin mostrar")


@pytest.mark.parametrize(
    ("extra", "listed", "summary"), [(0, MAX_ISSUES, False), (1, MAX_ISSUES + 1, True)]
)
def test_the_cap_is_exact(extra: int, listed: int, summary: bool) -> None:
    data = good()
    data["vehicle_classes"] = [" "] * (MAX_ISSUES + extra)
    issues = issues_of(data)
    assert len(issues) == listed
    assert (issues[-1].field is None) is summary
    if summary:
        assert issues[-1].message == "y 1 problema más sin mostrar"


def test_an_error_needs_at_least_one_problem() -> None:
    with pytest.raises(ValueError, match="al menos un problema"):
        CaseInvalidError([])


def test_the_case_cannot_be_modified_after_parsing() -> None:
    case = parse_case(good())
    with pytest.raises(ValueError, match="frozen"):
        case.tick_s = 2.0  # type: ignore[misc]
