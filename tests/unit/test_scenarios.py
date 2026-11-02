"""Generación repetible de escenarios controlados (DEV11 F2): QA13, repetibilidad y familia."""

import hashlib
import random
import re
import time

import pytest

from scenario_tools import SEED, generated, spec_data, the_case, the_spec
from semaforo.datos import scenarios as module
from semaforo.datos.scenarios import (
    GeneratedScenario,
    demand_seed_for,
    flow_for,
    generate_scenarios,
)
from semaforo.dominio.case import Case, CaseIssue
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import Scenario, ScenarioInvalidError, accept_scenario
from semaforo.dominio.scenario_spec import MAX_SCENARIOS, SpecInvalidError

EXPECTED_IDS = [
    "FAM_PUNTA-V01-S01",
    "FAM_PUNTA-V01-S02",
    "FAM_PUNTA-V02-S01",
    "FAM_PUNTA-V02-S02",
    "FAM_PUNTA-V03-S01",
    "FAM_PUNTA-V03-S02",
    "FAM_VALLE-V01-S01",
    "FAM_VALLE-V01-S02",
    "FAM_VALLE-V02-S01",
    "FAM_VALLE-V02-S02",
]


def ids(members: tuple[GeneratedScenario, ...]) -> list[str]:
    return [member.scenario.scenario_id for member in members]


def by_id(members: tuple[GeneratedScenario, ...]) -> dict[str, str]:
    """Cada escenario como JSON, por identificador."""
    return {m.scenario.scenario_id: m.scenario.model_dump_json() for m in members}


def digest(text: str) -> bytes:
    return hashlib.sha256(text.encode()).digest()


# --- repetibilidad (QA13) ---------------------------------------------------------------------


def test_the_same_spec_and_seed_give_the_same_scenarios() -> None:
    first = generated()
    second = generated()
    assert by_id(first) == by_id(second)
    assert [m.flows for m in first] == [m.flows for m in second]


def test_the_scenarios_are_identical_byte_for_byte() -> None:
    first = [m.scenario.model_dump_json(indent=2) for m in generated()]
    second = [m.scenario.model_dump_json(indent=2) for m in generated()]
    assert first == second


def test_a_different_seed_changes_the_flows_and_the_demand_seeds() -> None:
    first = generated(seed=SEED)
    second = generated(seed=SEED + 1)
    assert ids(first) == ids(second)
    assert [m.flows for m in first] != [m.flows for m in second]
    assert [m.scenario.demand_seed for m in first] != [m.scenario.demand_seed for m in second]


def test_the_scenarios_come_in_family_variant_repetition_order() -> None:
    assert ids(generated()) == EXPECTED_IDS


def test_the_count_is_the_one_the_spec_announces() -> None:
    assert len(generated()) == 3 * 2 + 2 * 2


def test_each_member_remembers_where_it_came_from() -> None:
    members = generated()
    assert [(m.family_id, m.variant, m.repetition) for m in members] == [
        ("FAM_PUNTA", 1, 1),
        ("FAM_PUNTA", 1, 2),
        ("FAM_PUNTA", 2, 1),
        ("FAM_PUNTA", 2, 2),
        ("FAM_PUNTA", 3, 1),
        ("FAM_PUNTA", 3, 2),
        ("FAM_VALLE", 1, 1),
        ("FAM_VALLE", 1, 2),
        ("FAM_VALLE", 2, 1),
        ("FAM_VALLE", 2, 2),
    ]


def test_the_flows_follow_the_documented_derivation() -> None:
    for member in generated():
        for row in the_spec().families[0 if member.family_id == "FAM_PUNTA" else 1].demand:
            low, high = row.flow_vph.min, row.flow_vph.max
            if low == high:
                expected = float(low)
            else:
                stream = random.Random(  # noqa: S311 - simulación, no seguridad
                    int.from_bytes(
                        digest(
                            f"{SEED}|flujo|{member.family_id}|{member.variant}|{row.movement_id}"
                        ),
                        "big",
                    )
                )
                expected = min(max(round(low + (high - low) * stream.random(), 1), low), high)
            assert member.flows[row.movement_id] == expected


def test_the_demand_seeds_follow_the_documented_derivation() -> None:
    for member in generated():
        text = f"{SEED}|semilla|{member.family_id}|{member.variant}|{member.repetition}|0"
        expected = int.from_bytes(digest(text)[:4], "big") & 0x7FFFFFFF
        assert member.scenario.demand_seed == expected


def test_a_known_scenario_stays_the_same() -> None:
    """Valores fijos: cualquier cambio en la derivación rompe la repetibilidad entre versiones."""
    first, valley = generated()[0], generated()[6]
    assert first.scenario.scenario_id == "FAM_PUNTA-V01-S01"
    assert first.scenario.demand_seed == 603748014
    assert first.flows == {"N_S": 516.0, "E_W": 274.5}
    assert valley.scenario.scenario_id == "FAM_VALLE-V01-S01"
    assert valley.scenario.demand_seed == 583759803
    assert valley.flows == {"N_S": 156.5, "E_W": 0.0}


# --- las repeticiones y las perturbaciones ----------------------------------------------------


def test_repetitions_share_the_flows_but_not_the_demand_seed() -> None:
    first, second = generated()[0], generated()[1]
    assert (first.variant, second.variant) == (1, 1)
    assert first.flows == second.flows
    assert first.scenario.demand_seed != second.scenario.demand_seed
    assert first.scenario.request.demand == second.scenario.request.demand


def test_the_variants_of_a_family_differ_in_their_flows() -> None:
    members = [m for m in generated() if m.family_id == "FAM_PUNTA" and m.repetition == 1]
    vectors = {tuple(m.flows.items()) for m in members}
    assert len(vectors) == 3


def test_every_flow_is_inside_its_range_and_has_one_decimal() -> None:
    members = generated()
    for member in members:
        family = the_spec().families[0 if member.family_id == "FAM_PUNTA" else 1]
        for row in family.demand:
            flow = member.flows[row.movement_id]
            assert row.flow_vph.min <= flow <= row.flow_vph.max
            assert round(flow, 1) == flow


def test_a_single_value_range_gives_that_value() -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 450.55, "max": 450.55}
    for member in generated(data):
        if member.family_id == "FAM_PUNTA":
            assert member.flows["N_S"] == 450.55


def test_a_zero_range_keeps_zero_flow_and_no_composition() -> None:
    for member in generated():
        if member.family_id == "FAM_VALLE":
            row = member.scenario.request.demand[1]
            assert (row.movement_id, row.flow_vph, row.composition) == ("E_W", 0.0, None)


def test_flows_never_leave_the_range_even_after_rounding() -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 400.04, "max": 400.06}
    data["families"][0]["variants"] = 200
    data["families"][0]["seeds"] = 1
    flows = {m.flows["N_S"] for m in generated(data) if m.family_id == "FAM_PUNTA"}
    # Redondeados a 0.1 serían 400.0 o 400.1, fuera del rango: se llevan al borde más cercano.
    assert flows == {400.04, 400.06}


# --- la familia se conserva (HU06) ------------------------------------------------------------


def test_every_scenario_belongs_to_its_family_group() -> None:
    for member in generated():
        assert member.scenario.group_id == member.family_id
        assert member.scenario.scenario_id.startswith(f"{member.family_id}-")


def test_origin_window_times_and_sources_come_from_the_spec() -> None:
    spec = the_spec()
    for member in generated():
        scenario = member.scenario
        assert scenario.origin == "synthetic"
        assert scenario.request.origin == "synthetic"
        assert scenario.source_ids == spec.source_ids == scenario.request.source_ids
        assert scenario.request.observation_start == spec.observation_start
        assert scenario.request.observation_end == spec.observation_end
        assert (scenario.warmup_s, scenario.measure_s, scenario.drain_max_s) == (0, 900, 900)


def test_the_times_and_the_window_of_the_spec_reach_every_scenario() -> None:
    data = spec_data()
    data.update(
        {
            "warmup_s": 30,
            "measure_s": 600,
            "drain_max_s": 300,
            "observation_start": "2026-10-19T17:00:00-05:00",
            "observation_end": "2026-10-19T17:10:00-05:00",
            "source_ids": ["SRC_A", "SRC_B"],
        }
    )
    for member in generated(data):
        scenario = member.scenario
        assert (scenario.warmup_s, scenario.measure_s, scenario.drain_max_s) == (30, 600, 300)
        assert scenario.request.observation_start == "2026-10-19T17:00:00-05:00"
        assert scenario.request.observation_end == "2026-10-19T17:10:00-05:00"
        assert scenario.source_ids == ["SRC_A", "SRC_B"]
        assert scenario.request.source_ids == ["SRC_A", "SRC_B"]


def test_a_field_derived_spec_gives_field_requests() -> None:
    data = spec_data()
    data["origin"] = "field_derived"
    for member in generated(data):
        assert member.scenario.origin == "field_derived"
        assert member.scenario.request.origin == "field"


def test_the_boundary_and_the_case_are_the_cases() -> None:
    case = the_case()
    for member in generated():
        scenario = member.scenario
        assert scenario.boundary_policy_id == case.boundary_policy_id
        assert (scenario.case_id, scenario.case_version) == (case.case_id, case.case_version)
        assert (scenario.request.case_id, scenario.request.case_version) == (
            case.case_id,
            case.case_version,
        )


def test_the_composition_is_the_family_one() -> None:
    for member in generated():
        spec_family = the_spec().families[0 if member.family_id == "FAM_PUNTA" else 1]
        compositions = [row.composition for row in member.scenario.request.demand]
        assert compositions == [row.composition for row in spec_family.demand]


def test_the_order_of_the_classes_in_the_spec_does_not_change_the_scenarios() -> None:
    data = spec_data()
    for family in data["families"]:
        for row in family["demand"]:
            if row["composition"] is not None:
                row["composition"] = dict(reversed(list(row["composition"].items())))
    assert by_id(generated(data)) == by_id(generated())


def test_the_flows_of_the_member_are_the_ones_in_its_request() -> None:
    for member in generated():
        in_request = {row.movement_id: row.flow_vph for row in member.scenario.request.demand}
        assert in_request == member.flows


def test_every_scenario_is_accepted_by_the_scenario_rules() -> None:
    case = the_case()
    for member in generated():
        accepted = accept_scenario(member.scenario.model_dump(mode="json"), case)
        assert accepted == member.scenario


def test_ids_and_request_ids_are_unique_and_the_demand_artifact_is_empty() -> None:
    members = generated()
    assert len({m.scenario.scenario_id for m in members}) == len(members)
    assert len({m.scenario.request.request_id for m in members}) == len(members)
    assert all(m.scenario.demand_artifact is None for m in members)
    assert members[0].scenario.request.request_id == "FAM_PUNTA-V01-S01-REQ"


def test_the_demand_seeds_are_unique_inside_each_family_and_fit_31_bits() -> None:
    members = generated()
    for family in ("FAM_PUNTA", "FAM_VALLE"):
        seeds = [m.scenario.demand_seed for m in members if m.family_id == family]
        assert len(set(seeds)) == len(seeds)
    assert all(0 <= m.scenario.demand_seed < 2**31 for m in members)


# --- independencia entre familias -------------------------------------------------------------


def test_adding_or_removing_a_family_does_not_change_the_others() -> None:
    both = by_id(generated())
    data = spec_data()
    data["families"] = data["families"][:1]
    only_first = by_id(generated(data))
    assert {k: v for k, v in both.items() if k in only_first} == only_first
    data = spec_data()
    data["families"] = data["families"][1:]
    only_second = by_id(generated(data))
    assert {k: v for k, v in both.items() if k in only_second} == only_second


def test_reordering_the_families_does_not_change_their_scenarios() -> None:
    data = spec_data()
    data["families"].reverse()
    reordered = generated(data)
    assert sorted(ids(reordered)) == sorted(EXPECTED_IDS)
    assert by_id(reordered) == by_id(generated())


def test_changing_another_family_does_not_change_a_family() -> None:
    data = spec_data()
    data["families"][1]["demand"][0]["flow_vph"] = {"min": 150, "max": 190}
    data["families"][1]["variants"] = 5
    changed = by_id(generated(data))
    original = by_id(generated())
    punta = {k: v for k, v in original.items() if k.startswith("FAM_PUNTA")}
    assert {k: v for k, v in changed.items() if k.startswith("FAM_PUNTA")} == punta


def test_the_number_of_seeds_of_a_variant_does_not_change_its_flows() -> None:
    data = spec_data()
    data["families"][0]["seeds"] = 5
    more = generated(data)
    base = {m.scenario.scenario_id: m for m in generated()}
    for member in more:
        if member.scenario.scenario_id in base:
            assert member.flows == base[member.scenario.scenario_id].flows
            assert (
                member.scenario.demand_seed
                == base[member.scenario.scenario_id].scenario.demand_seed
            )


# --- nombres ----------------------------------------------------------------------------------


def test_the_numbers_in_the_names_have_at_least_two_digits() -> None:
    data = spec_data()
    data["families"] = data["families"][:1]
    data["families"][0].update({"variants": 9, "seeds": 1})
    assert ids(generated(data))[0] == "FAM_PUNTA-V01-S01"
    assert ids(generated(data))[-1] == "FAM_PUNTA-V09-S01"


def test_the_numbers_grow_in_width_with_the_counts() -> None:
    data = spec_data()
    data["families"] = data["families"][:1]
    data["families"][0].update({"variants": 20, "seeds": 100})
    members = generated(data)
    assert members[0].scenario.scenario_id == "FAM_PUNTA-V01-S001"
    assert members[-1].scenario.scenario_id == "FAM_PUNTA-V20-S100"
    data["families"][0].update({"variants": 100, "seeds": 20})
    members = generated(data)
    assert members[0].scenario.scenario_id == "FAM_PUNTA-V001-S01"
    assert members[-1].scenario.scenario_id == "FAM_PUNTA-V100-S20"


def test_a_scenario_name_stays_a_safe_file_name() -> None:
    safe = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
    assert all(safe.fullmatch(name) for name in ids(generated()))


# --- semilla de la demanda --------------------------------------------------------------------


def test_demand_seed_for_is_deterministic() -> None:
    assert demand_seed_for(7, "F", 1, 1, frozenset()) == demand_seed_for(7, "F", 1, 1, frozenset())


def test_demand_seed_for_skips_a_seed_already_taken() -> None:
    first = demand_seed_for(7, "F", 1, 1, frozenset())
    second = demand_seed_for(7, "F", 1, 1, frozenset({first}))
    assert second != first
    third = demand_seed_for(7, "F", 1, 1, frozenset({first, second}))
    assert third not in {first, second}
    text = f"7|semilla|F|1|1|{1}"
    assert second == int.from_bytes(digest(text)[:4], "big") & 0x7FFFFFFF


def test_a_repeated_demand_seed_inside_a_family_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = module.derivation_digest  # se fuerza una colisión en el primer intento

    def colliding(text: str) -> bytes:
        return b"\x00\x00\x00\x07" if "|semilla|" in text and text.endswith("|0") else real(text)

    monkeypatch.setattr(module, "derivation_digest", colliding)
    members = generated()
    for family in ("FAM_PUNTA", "FAM_VALLE"):
        seeds = [m.scenario.demand_seed for m in members if m.family_id == family]
        assert len(set(seeds)) == len(seeds)
    punta = [m for m in members if m.family_id == "FAM_PUNTA"]
    first, second = punta[0], punta[1]
    assert first.scenario.demand_seed == 7
    assert second.scenario.demand_seed != 7


def test_flow_for_matches_the_generated_flows() -> None:
    spec = the_spec()
    row = spec.families[0].demand[0]
    assert flow_for(SEED, "FAM_PUNTA", 2, row) == generated()[2].flows["N_S"]


# --- semilla maestra y especificación inválida ------------------------------------------------


@pytest.mark.parametrize("seed", [-1, 9223372036854775808])
def test_the_master_seed_must_be_a_non_negative_integer_in_range(seed: int) -> None:
    with pytest.raises(DomainError) as raised:
        generated(seed=seed)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "seed"
    assert "la semilla debe ser un entero de 0 a" in raised.value.message


@pytest.mark.parametrize("seed", [0, 9223372036854775807])
def test_the_seed_limits_themselves_work(seed: int) -> None:
    assert len(generated(seed=seed)) == 10


def test_an_invalid_spec_is_rejected_before_generating_anything() -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 600, "max": 400}
    with pytest.raises(SpecInvalidError) as raised:
        generated(data)
    assert raised.value.issues[0].rule_id == "SPEC-C03"


def test_a_spec_for_another_case_is_rejected() -> None:
    data = spec_data()
    data["case_id"] = "OTHER"
    with pytest.raises(SpecInvalidError) as raised:
        generated(data)
    assert raised.value.issues[0].rule_id == "SPEC-C01"


def test_a_defective_scenario_is_reported_with_the_scenario_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(scenario: Scenario, case: Case) -> list[CaseIssue]:
        return [CaseIssue("SCEN-C04", "request.demand[0].flow_vph", "falla de prueba")]

    monkeypatch.setattr(module, "scenario_issues", broken)
    with pytest.raises(ScenarioInvalidError) as raised:
        generated()
    assert raised.value.issues[0].rule_id == "SCEN-C04"


# --- tamaño e inmutabilidad -------------------------------------------------------------------


def test_the_largest_allowed_set_is_generated_quickly() -> None:
    data = spec_data()
    data["families"] = data["families"][:1]
    data["families"][0].update({"variants": 20, "seeds": 100})
    started = time.perf_counter()
    members = generated(data)
    assert len(members) == MAX_SCENARIOS
    assert len({m.scenario.scenario_id for m in members}) == MAX_SCENARIOS
    assert time.perf_counter() - started < 30


def test_generating_does_not_change_the_spec_or_the_case() -> None:
    spec, case = the_spec(), the_case()
    before = (spec.model_dump_json(), case.model_dump_json())
    generate_scenarios(spec, case, SEED)
    assert (spec.model_dump_json(), case.model_dump_json()) == before
