"""Reglas de consistencia del caso CASE-C01 a C13 (DEV02, F2). Incluye QA01 y QA02.

QA01: un caso válido se acepta; las copias con un ID repetido o una referencia inexistente se
rechazan con el campo y el motivo.
QA02: límites, tick, solapes y ciclo con casos frontera; los solapes no se cuentan dos veces y un
caso inválido nunca se acepta.
"""

import copy
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from semaforo.dominio.case import MAX_ISSUES, CaseInvalidError, CaseIssue, parse_case
from semaforo.dominio.case_rules import (
    RULES,
    Window,
    accept_case,
    cycle_window,
    evaluate_rules,
    group_window,
)
from semaforo.dominio.errors import ErrorCode

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "case.json"
ALL_RULES = [f"CASE-C{number:02d}" for number in range(1, 14)]


def good() -> dict[str, Any]:
    """Copia del caso de ejemplo, lista para estropear."""
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def build(
    specs: Sequence[tuple[str, float, float, str]],
    *,
    groups: list[dict[str, Any]] | None = None,
    cycle: tuple[float, float] | None = None,
    tick: float = 1,
) -> dict[str, Any]:
    """Caso mínimo y coherente: un semáforo de dos enlaces y los slots de ``specs``.

    Cada spec es ``(tipo, mínimo, máximo, estado)``. Por defecto hay un grupo de verde por slot
    variable, con la misma ventana, y el ciclo es justo lo que pueden sumar los slots.
    """
    slots = [
        {
            "id": f"s{index}",
            "kind": kind,
            "min_s": low,
            "max_s": high,
            "states": [{"tls_id": "T", "state": state}],
        }
        for index, (kind, low, high, state) in enumerate(specs)
    ]
    if groups is None:
        groups = [
            {
                "id": f"g{index}",
                "slot_ids": [f"s{index}"],
                "min_s": low,
                "max_s": high,
                "purpose": "vehicle",
            }
            for index, (kind, low, high, _) in enumerate(specs)
            if kind == "variable"
        ]
    if cycle is None:
        cycle = (sum(spec[1] for spec in specs), sum(spec[2] for spec in specs))
    return {
        "case_id": "MINI",
        "case_version": "1.0.0",
        "origin": "synthetic",
        "description": "caso de prueba",
        "representation_status": "synthetic_fixture",
        "network": None,
        "tick_s": tick,
        "cycle_s": {"min": cycle[0], "max": cycle[1]},
        "vehicle_classes": ["car"],
        "movements": [
            {
                "id": name,
                "approach_id": name,
                "incoming_lanes": [f"in_{name}"],
                "outgoing_edges": [f"out_{name}"],
                "tls_id": "T",
                "link_indices": [link],
                "flow_domain_vph": {"min": 0, "max": 1000},
            }
            for link, name in enumerate(["A", "B"])
        ],
        "slots": slots,
        "green_groups": groups,
        "boundary_policy_id": "POLICY",
        "restrictions_evidence": [],
    }


def three_slots() -> list[tuple[str, float, float, str]]:
    return [("variable", 10, 30, "Gr"), ("fixed", 4, 4, "yr"), ("variable", 8, 20, "rG")]


def results(data: dict[str, Any]) -> dict[str, tuple[str, list[CaseIssue]]]:
    """Estado e incidencias de cada regla que no pasó."""
    return {
        r.rule_id: (r.status, list(r.issues))
        for r in evaluate_rules(parse_case(data))
        if r.status != "passed"
    }


def only(data: dict[str, Any], rule_id: str) -> list[CaseIssue]:
    """Las incidencias de ``rule_id``, comprobando que ninguna otra regla falla."""
    found = results(data)
    assert list(found) == [rule_id], found
    return found[rule_id][1]


def single(data: dict[str, Any], rule_id: str) -> CaseIssue:
    issues = only(data, rule_id)
    assert len(issues) == 1, issues
    return issues[0]


def two_tls() -> dict[str, Any]:
    """El caso de ejemplo con un segundo semáforo ``T2`` de un enlace en todos los slots."""
    data = good()
    for slot in data["slots"]:
        slot["states"].append({"tls_id": "T2", "state": "r"})
    return data


# --- La regla registrada -------------------------------------------------------------------


def test_the_registry_has_the_thirteen_rules_in_order() -> None:
    assert [rule.rule_id for rule in RULES] == ALL_RULES
    assert all(rule.title for rule in RULES)
    assert [rule.rule_id for rule in RULES if rule.severity == "warning"] == ["CASE-C07"]


def test_the_reference_case_passes_every_rule() -> None:
    case = parse_case(good())
    assert [(r.rule_id, r.status, r.issues) for r in evaluate_rules(case)] == [
        (rule_id, "passed", ()) for rule_id in ALL_RULES
    ]
    assert accept_case(good()) == case


# --- QA01 ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "key", "second", "first"),
    [
        ("vehicle_classes", None, "vehicle_classes[1]", "vehicle_classes[0]"),
        ("movements", "id", "movements[1].id", "movements[0].id"),
        ("slots", "id", "slots[2].id", "slots[0].id"),
        ("green_groups", "id", "green_groups[1].id", "green_groups[0].id"),
    ],
)
def test_qa01_a_repeated_id_is_rejected_with_its_field(
    section: str, key: str | None, second: str, first: str
) -> None:
    data = good()
    index = int(second.split("[")[1].split("]", maxsplit=1)[0])
    if key is None:
        data[section][index] = data[section][0]
    else:
        data[section][index][key] = data[section][0][key]
    issue = single(data, "CASE-C01")
    assert issue.field == second
    assert "repetido" in issue.message
    assert first in issue.message


def test_qa01_a_group_with_a_missing_slot_is_rejected() -> None:
    data = good()
    data["green_groups"][0]["slot_ids"] = ["no-existe"]
    issue = single(data, "CASE-C09")
    assert issue.field == "green_groups[0].slot_ids[0]"
    assert issue.message == "el slot 'no-existe' no existe"


def test_qa01_the_rejection_carries_every_rule_field_and_reason() -> None:
    data = good()
    data["slots"][3]["id"] = "s1"
    data["green_groups"][1]["slot_ids"] = ["no-existe"]
    with pytest.raises(CaseInvalidError) as raised:
        accept_case(data)
    error = raised.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert [(i.rule_id, i.field) for i in error.issues] == [
        ("CASE-C01", "slots[3].id"),
        ("CASE-C09", "green_groups[1].slot_ids[0]"),
    ]
    assert error.field == "slots[3].id"
    assert all(issue.message for issue in error.issues)


def test_the_structure_is_checked_before_the_consistency() -> None:
    data = good()
    data["slots"][3]["id"] = "s1"
    data["case_version"] = "x"
    with pytest.raises(CaseInvalidError) as raised:
        accept_case(data)
    assert [i.rule_id for i in raised.value.issues] == ["CASE-S03"]


def test_a_flood_of_consistency_problems_is_capped() -> None:
    data = good()
    data["vehicle_classes"] = ["car"] * (MAX_ISSUES + 50)
    with pytest.raises(CaseInvalidError) as raised:
        accept_case(data)
    issues = raised.value.issues
    assert len(issues) == MAX_ISSUES + 1
    assert (issues[-1].rule_id, issues[-1].field) == ("CASE-C01", None)
    assert issues[-1].message == "y 49 problemas más sin mostrar"


def test_twenty_thousand_repeated_ids_are_handled_quickly() -> None:
    data = good()
    data["vehicle_classes"] = ["car"] * 20_000
    with pytest.raises(CaseInvalidError) as raised:
        accept_case(data)
    assert len(raised.value.issues) == MAX_ISSUES + 1


def test_a_large_valid_case_is_accepted() -> None:
    count = 1_500
    specs = [("variable", 1, 5, "r" * i + "G" + "r" * (count - 1 - i)) for i in range(count)]
    data = build(specs)
    data["movements"] = [
        {
            "id": f"m{i}",
            "approach_id": "A",
            "incoming_lanes": ["l"],
            "outgoing_edges": ["e"],
            "tls_id": "T",
            "link_indices": [i],
            "flow_domain_vph": {"min": 0, "max": 10},
        }
        for i in range(count)
    ]
    assert len(accept_case(data).slots) == count


# --- QA02 ----------------------------------------------------------------------------------


def test_qa02_a_range_with_minimum_above_maximum_is_rejected() -> None:
    data = good()
    data["cycle_s"] = {"min": 50, "max": 40}
    issue = single(data, "CASE-C02")
    assert issue.field == "cycle_s"
    assert "supera" in issue.message


def test_qa02_a_flow_domain_with_minimum_above_maximum_is_rejected() -> None:
    data = good()
    data["movements"][1]["flow_domain_vph"] = {"min": 900, "max": 100}
    assert single(data, "CASE-C02").field == "movements[1].flow_domain_vph"


def test_qa02_equal_minimum_and_maximum_are_accepted() -> None:
    data = good()
    data["cycle_s"] = {"min": 60, "max": 60}
    data["movements"][0]["flow_domain_vph"] = {"min": 300, "max": 300}
    assert accept_case(data)


def test_qa02_a_slot_with_minimum_above_maximum_is_rejected() -> None:
    data = good()
    data["slots"][0]["min_s"] = 80
    issues = only(data, "CASE-C03")
    assert [i.field for i in issues] == ["slots[0].min_s"]


@pytest.mark.parametrize(
    ("low", "high", "valid"),
    [(3, 3, True), (3, 3 + 1e-12, True), (3, 4, False), (4, 3, False)],
)
def test_qa02_a_fixed_slot_needs_equal_bounds(low: float, high: float, valid: bool) -> None:
    data = good()
    data["slots"][1]["min_s"] = low
    data["slots"][1]["max_s"] = high
    if valid:
        assert accept_case(data)
    else:
        assert only(data, "CASE-C03")[0].field in {"slots[1].kind", "slots[1].min_s"}


def test_qa02_a_fixed_slot_with_different_bounds_names_the_kind() -> None:
    data = good()
    data["slots"][1]["max_s"] = 5
    issue = single(data, "CASE-C03")
    assert issue.field == "slots[1].kind"
    assert "mínimo igual a máximo" in issue.message


def test_a_slot_with_inverted_bounds_does_not_also_break_the_cycle() -> None:
    data = good()
    data["slots"][0]["min_s"] = 80
    data["cycle_s"] = {"min": 40, "max": 70}
    assert list(results(data)) == ["CASE-C03"]


def test_a_repeated_slot_id_resolves_to_the_first_slot() -> None:
    data = good()
    data["slots"][2]["id"] = "s1"
    case = parse_case(data)
    assert group_window(case, 0) == Window(10, 50)
    assert list(results(data)) == ["CASE-C01"]


def test_a_slot_repeated_in_a_group_counts_once_in_its_window() -> None:
    data = good()
    data["green_groups"][0]["slot_ids"] = ["s1", "s1"]
    assert group_window(parse_case(data), 0) == Window(10, 50)


@pytest.mark.parametrize(("extra", "listed", "summary"), [(0, 100, False), (1, 101, True)])
def test_the_cap_of_consistency_problems_is_exact(extra: int, listed: int, summary: bool) -> None:
    data = good()
    data["vehicle_classes"] = ["car"] * (1 + MAX_ISSUES + extra)
    with pytest.raises(CaseInvalidError) as raised:
        accept_case(data)
    issues = raised.value.issues
    assert len(issues) == listed
    assert (issues[-1].field is None) is summary
    if summary:
        assert issues[-1].message == "y 1 problema más sin mostrar"


def test_qa02_without_a_variable_slot_the_case_is_rejected() -> None:
    specs = [("fixed", 5, 5, "Gr"), ("fixed", 3, 3, "rG")]
    data = build(
        specs,
        groups=[{"id": "g", "slot_ids": ["s0"], "min_s": 5, "max_s": 5, "purpose": "vehicle"}],
    )
    issue = single(data, "CASE-C04")
    assert issue.field == "slots"


@pytest.mark.parametrize("tick", [0.1, 0.25, 0.5, 1, 2, 5])
@given(steps=st.integers(min_value=1, max_value=400))
def test_qa02_multiples_of_the_tick_are_aligned_even_with_float_noise(
    tick: float, steps: int
) -> None:
    data = build([("variable", tick, steps * tick, "Gr")], tick=tick)
    assert accept_case(data)


@pytest.mark.parametrize("tick", [0.1, 0.25, 0.5, 1, 2, 5])
@given(steps=st.integers(min_value=1, max_value=400))
def test_qa02_half_a_tick_off_is_never_aligned(tick: float, steps: int) -> None:
    data = build([("variable", tick, (steps + 0.5) * tick, "Gr")], tick=tick)
    issues = only(data, "CASE-C05")
    assert [i.field for i in issues] == ["slots[0].max_s", "cycle_s.max", "green_groups[0].max_s"]


@pytest.mark.parametrize(
    ("path", "value", "field"),
    [
        (("slots", 0, "min_s"), 10.5, "slots[0].min_s"),
        (("slots", 3, "max_s"), 50.25, "slots[3].max_s"),
        (("cycle_s", "min"), 40.5, "cycle_s.min"),
        (("cycle_s", "max"), 99.5, "cycle_s.max"),
        (("green_groups", 0, "min_s"), 10.5, "green_groups[0].min_s"),
        (("green_groups", 1, "max_s"), 49.5, "green_groups[1].max_s"),
    ],
)
def test_qa02_every_limit_must_match_the_tick(
    path: tuple[str | int, ...], value: float, field: str
) -> None:
    data = good()
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    issues = [i for i in only_with_c05(data) if i.field == field]
    assert len(issues) == 1
    assert "múltiplo de tick_s (1)" in issues[0].message


def only_with_c05(data: dict[str, Any]) -> list[CaseIssue]:
    """Incidencias de C05; otras reglas pueden fallar si el valor cambia también sus sumas."""
    found = results(data)
    assert "CASE-C05" in found
    return found["CASE-C05"][1]


def test_qa02_a_huge_multiple_of_the_tick_is_aligned_despite_float_error() -> None:
    """428038701.2 / 0.1 se desvía 4.8e-7 de un entero por coma flotante, pero es un múltiplo."""
    assert abs(428038701.2 / 0.1 - round(428038701.2 / 0.1)) > 1e-8
    data = build([("variable", 0.1, 428038701.2, "Gr")], tick=0.1)
    assert accept_case(data)


def test_a_missing_tls_state_in_a_slot_is_rejected() -> None:
    data = two_tls()
    del data["slots"][2]["states"][1]
    issue = single(data, "CASE-C06")
    assert issue.field == "slots[2].states"
    assert issue.message == "falta el estado del semáforo 'T2'"


def test_a_tls_repeated_in_a_slot_is_rejected() -> None:
    data = two_tls()
    data["slots"][1]["states"].append({"tls_id": "T2", "state": "r"})
    issue = single(data, "CASE-C06")
    assert issue.field == "slots[1].states[2].tls_id"
    assert "dos veces" in issue.message


def test_a_state_of_another_length_is_rejected() -> None:
    data = two_tls()
    data["slots"][3]["states"][1]["state"] = "rr"
    issue = single(data, "CASE-C06")
    assert issue.field == "slots[3].states[1].state"
    assert issue.message == "el estado mide 2 y el de 'T2' mide 1 en el primer slot que lo usa"


def test_the_length_of_the_first_slot_is_the_reference() -> None:
    data = good()
    data["slots"][0]["states"][0]["state"] = "Grr"
    issues = only(data, "CASE-C06")
    assert [i.field for i in issues] == [f"slots[{n}].states[0].state" for n in range(1, 6)]


def test_slots_with_the_same_states_in_a_row_only_warn() -> None:
    data = good()
    data["slots"][1]["states"] = copy.deepcopy(data["slots"][0]["states"])
    found = results(data)
    assert list(found) == ["CASE-C07"]
    status, issues = found["CASE-C07"]
    assert status == "warning"
    assert [i.field for i in issues] == ["slots[1]"]
    assert "'s1'" in issues[0].message
    assert accept_case(data)


def test_the_last_slot_is_compared_with_the_first() -> None:
    data = good()
    data["slots"][5]["states"] = copy.deepcopy(data["slots"][0]["states"])
    data["slots"][5]["states"][0]["state"] = "Gr"
    issues = results(data)["CASE-C07"][1]
    assert [i.field for i in issues] == ["slots[0]"]
    assert "'s6'" in issues[0].message


def test_two_slots_with_the_same_states_warn_once() -> None:
    data = build([("variable", 5, 9, "Gr"), ("fixed", 3, 3, "Gr")])
    assert [i.field for i in results(data)["CASE-C07"][1]] == ["slots[1]"]


def test_a_single_slot_has_nothing_to_compare() -> None:
    assert "CASE-C07" not in results(build([("variable", 5, 9, "Gr")]))


def test_a_movement_with_an_unknown_tls_is_rejected() -> None:
    data = good()
    data["movements"][1]["tls_id"] = "OTRO"
    issue = single(data, "CASE-C08")
    assert issue.field == "movements[1].tls_id"
    assert "'OTRO'" in issue.message


@pytest.mark.parametrize(
    ("links", "field", "text"),
    [
        ([-1], "movements[0].link_indices[0]", "negativo"),
        ([0, 0], "movements[0].link_indices[1]", "repetido en el movimiento"),
        ([2], "movements[0].link_indices[0]", "no cabe en el estado de 'DEMO_TLS', que mide 2"),
        ([1], "movements[1].link_indices[0]", "ya lo usa 'N_S'"),
    ],
    ids=["negative", "repeated", "out-of-range", "taken-by-another"],
)
def test_the_link_indices_of_a_movement_are_checked(
    links: list[int], field: str, text: str
) -> None:
    data = good()
    data["movements"][0]["link_indices"] = links
    issue = single(data, "CASE-C08")
    assert issue.field == field
    assert text in issue.message


def test_the_last_valid_link_index_is_accepted() -> None:
    data = good()
    data["movements"][0]["link_indices"] = [0]
    data["movements"][1]["link_indices"] = [1]
    assert accept_case(data)


def test_a_group_with_a_repeated_slot_is_rejected() -> None:
    data = good()
    data["green_groups"][0]["slot_ids"] = ["s1", "s1"]
    issue = single(data, "CASE-C09")
    assert issue.field == "green_groups[0].slot_ids[1]"
    assert "repetido" in issue.message


def test_a_group_with_minimum_above_maximum_is_rejected_once() -> None:
    data = good()
    data["green_groups"][0]["min_s"] = 60
    issue = single(data, "CASE-C09")
    assert issue.field == "green_groups[0].min_s"


def test_a_group_whose_slots_need_more_than_its_maximum_is_rejected() -> None:
    data = good()
    data["green_groups"][0].update({"min_s": 0, "max_s": 9})
    issue = single(data, "CASE-C09")
    assert issue.field == "green_groups[0].max_s"
    assert "al menos 10 s" in issue.message


def test_a_group_whose_slots_cannot_reach_its_minimum_is_rejected() -> None:
    data = good()
    data["slots"][0]["max_s"] = 25
    data["green_groups"][0]["min_s"] = 30
    issue = single(data, "CASE-C09")
    assert issue.field == "green_groups[0].min_s"
    assert "como mucho 25 s" in issue.message


@pytest.mark.parametrize(
    ("group_min", "group_max", "valid"),
    [(25, 50, True), (26, 50, False), (10, 10, True), (10, 9, False)],
)
def test_qa02_the_group_window_boundaries(group_min: float, group_max: float, valid: bool) -> None:
    data = build([("variable", 10, 25, "Gr"), ("fixed", 5, 5, "rG")])
    data["green_groups"][0].update({"min_s": group_min, "max_s": group_max})
    if valid:
        assert accept_case(data)
    else:
        assert only(data, "CASE-C09")


@pytest.mark.parametrize(
    ("cycle", "valid"),
    [
        ((10, 28), True),
        ((10, 27), False),
        ((108, 200), True),
        ((109, 200), False),
        ((28, 108), True),
        ((50, 50), True),
    ],
)
def test_qa02_the_cycle_boundaries(cycle: tuple[float, float], valid: bool) -> None:
    data = good()
    data["cycle_s"] = {"min": cycle[0], "max": cycle[1]}
    if valid:
        assert accept_case(data)
    else:
        issue = single(data, "CASE-C10")
        assert issue.field == "cycle_s"
        assert "no se cruza" in issue.message


def test_qa02_an_incoherent_cycle_is_rejected() -> None:
    data = good()
    data["cycle_s"] = {"min": 10, "max": 20}
    assert single(data, "CASE-C10").field == "cycle_s"


def test_an_inverted_cycle_is_reported_by_c02_alone() -> None:
    data = good()
    data["cycle_s"] = {"min": 100, "max": 40}
    assert list(results(data)) == ["CASE-C02"]


def test_qa02_overlapping_groups_do_not_count_a_slot_twice() -> None:
    specs = [("variable", 5, 10, "Gr"), ("variable", 5, 10, "rG"), ("variable", 5, 10, "Gr")]
    overlapping = [
        {"id": "a", "slot_ids": ["s0", "s1"], "min_s": 10, "max_s": 20, "purpose": "vehicle"},
        {"id": "b", "slot_ids": ["s1", "s2"], "min_s": 10, "max_s": 20, "purpose": "vehicle"},
        {"id": "c", "slot_ids": ["s0", "s1", "s2"], "min_s": 15, "max_s": 30, "purpose": "vehicle"},
    ]
    case = parse_case(build(specs, groups=overlapping, cycle=(15, 30)))
    assert cycle_window(case) == Window(15, 30)
    assert accept_case(build(specs, groups=overlapping, cycle=(15, 30)))
    assert [group_window(case, i) for i in range(3)] == [
        Window(10, 20),
        Window(10, 20),
        Window(15, 30),
    ]


def test_qa02_a_cycle_above_the_slots_is_rejected_even_if_groups_would_add_up() -> None:
    specs = [("variable", 5, 10, "Gr"), ("variable", 5, 10, "rG")]
    groups = [
        {"id": "a", "slot_ids": ["s0", "s1"], "min_s": 10, "max_s": 20, "purpose": "vehicle"},
        {"id": "b", "slot_ids": ["s0", "s1"], "min_s": 10, "max_s": 20, "purpose": "vehicle"},
    ]
    data = build(specs, groups=groups, cycle=(30, 80))
    assert only(data, "CASE-C10")


def test_the_windows_of_the_reference_case() -> None:
    case = parse_case(good())
    assert cycle_window(case) == Window(40, 100)
    assert group_window(case, 0) == Window(10, 50)


def test_the_windows_are_none_when_empty() -> None:
    data = good()
    data["cycle_s"] = {"min": 10, "max": 20}
    data["green_groups"][0]["slot_ids"] = ["no-existe"]
    case = parse_case(data)
    assert cycle_window(case) is None
    assert group_window(case, 0) is None


def test_a_group_slot_without_green_is_rejected() -> None:
    data = good()
    data["green_groups"][0]["slot_ids"] = ["s1", "s2"]
    issue = single(data, "CASE-C11")
    assert issue.field == "green_groups[0].slot_ids[1]"
    assert "'s2'" in issue.message


def test_green_may_be_lowercase_in_any_link() -> None:
    data = good()
    data["slots"][1]["states"][0]["state"] = "rg"
    data["green_groups"][0]["slot_ids"] = ["s1", "s2"]
    assert accept_case(data)


def pedestrian_case(evidence: list[str]) -> dict[str, Any]:
    data = good()
    data["green_groups"][1]["purpose"] = "pedestrian"
    data["restrictions_evidence"] = evidence
    return data


@pytest.mark.parametrize("evidence", [[], [""], ["   "], ["", " "]])
def test_a_pedestrian_group_needs_evidence(evidence: list[str]) -> None:
    issue = single(pedestrian_case(evidence), "CASE-C12")
    assert issue.field == "restrictions_evidence"
    assert "['EW']" in issue.message


def test_a_pedestrian_group_with_evidence_is_accepted() -> None:
    assert accept_case(pedestrian_case(["", "Estudio peatonal 2026"]))


def test_a_case_without_pedestrian_groups_needs_no_evidence() -> None:
    data = good()
    data["restrictions_evidence"] = []
    assert accept_case(data)


NETWORK = {"artifact_id": "red", "path": "osm.net.xml.gz", "sha256": "a" * 64}


@pytest.mark.parametrize(
    ("origin", "status", "network", "fields"),
    [
        ("field", "unverified", None, ["network"]),
        ("field", "synthetic_fixture", NETWORK, ["representation_status"]),
        ("field", "synthetic_fixture", None, ["network", "representation_status"]),
        ("synthetic", "calibrated", None, ["representation_status"]),
        ("synthetic", "validated", NETWORK, ["representation_status"]),
    ],
)
def test_the_origin_must_match_the_network_and_the_status(
    origin: str, status: str, network: dict[str, str] | None, fields: list[str]
) -> None:
    data = good()
    data.update({"origin": origin, "representation_status": status, "network": network})
    assert [i.field for i in only(data, "CASE-C13")] == fields


@pytest.mark.parametrize(
    ("origin", "status", "network"),
    [
        ("field", "unverified", NETWORK),
        ("field", "calibrated", NETWORK),
        ("field", "validated", NETWORK),
        ("synthetic", "unverified", None),
        ("synthetic", "synthetic_fixture", NETWORK),
    ],
)
def test_coherent_origins_are_accepted(
    origin: str, status: str, network: dict[str, str] | None
) -> None:
    data = good()
    data.update({"origin": origin, "representation_status": status, "network": network})
    assert accept_case(data)


# --- Propiedades ---------------------------------------------------------------------------

SLOT = st.integers(min_value=1, max_value=20).flatmap(
    lambda low: st.tuples(st.just(low), st.integers(min_value=low, max_value=low + 15))
)


@given(
    windows=st.lists(SLOT, min_size=1, max_size=6),
    cycle=st.integers(min_value=0, max_value=120).flatmap(
        lambda low: st.tuples(st.just(low), st.integers(min_value=low, max_value=low + 120))
    ),
)
def test_the_cycle_is_feasible_exactly_when_the_ranges_intersect(
    windows: list[tuple[int, int]], cycle: tuple[int, int]
) -> None:
    specs = [
        ("variable", low, high, "Gr" if i % 2 == 0 else "rG")
        for i, (low, high) in enumerate(windows)
    ]
    data = build(specs, cycle=cycle)
    case = parse_case(data)
    low = max(cycle[0], sum(w[0] for w in windows))
    high = min(cycle[1], sum(w[1] for w in windows))
    feasible = low <= high
    assert (cycle_window(case) is not None) is feasible
    if feasible:
        assert cycle_window(case) == Window(low, high)
        assert accept_case(data)
    else:
        assert {r.rule_id for r in evaluate_rules(case) if r.status == "failed"} == {"CASE-C10"}
        with pytest.raises(CaseInvalidError):
            accept_case(data)


@given(
    windows=st.lists(SLOT, min_size=1, max_size=6),
    members=st.sets(st.integers(min_value=0, max_value=5), min_size=1),
    group=SLOT,
)
def test_a_group_is_reachable_exactly_when_the_ranges_intersect(
    windows: list[tuple[int, int]], members: set[int], group: tuple[int, int]
) -> None:
    ids = sorted(i for i in members if i < len(windows))
    if not ids:
        return
    specs = [
        ("variable", low, high, "Gr" if i % 2 == 0 else "rG")
        for i, (low, high) in enumerate(windows)
    ]
    groups = [
        {
            "id": "g",
            "slot_ids": [f"s{i}" for i in ids],
            "min_s": group[0],
            "max_s": group[1],
            "purpose": "vehicle",
        }
    ]
    data = build(specs, groups=groups)
    case = parse_case(data)
    low = max(group[0], sum(windows[i][0] for i in ids))
    high = min(group[1], sum(windows[i][1] for i in ids))
    reachable = low <= high
    assert (group_window(case, 0) is not None) is reachable
    failed = {r.rule_id for r in evaluate_rules(case) if r.status == "failed"}
    assert ("CASE-C09" in failed) is not reachable
    assert failed <= {"CASE-C09"}
