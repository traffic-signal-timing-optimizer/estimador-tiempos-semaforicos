"""Asignación de familias completas a entrenamiento, validación y prueba (DEV12 F1, QA14)."""

import hashlib
import random
import time
from collections import Counter

import pytest

from scenario_tools import families_spec, generated, scenarios_of
from semaforo.aprendizaje.splits import (
    MIN_GROUPS,
    PROVISIONAL_POLICY,
    assign_groups,
    create_split,
    partition_counts,
)
from semaforo.dominio.case import CaseIssue
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.scenario import Scenario
from semaforo.dominio.split import (
    Partition,
    Proportions,
    SplitInvalidError,
    SplitPolicy,
    parse_split,
    split_issues,
)

SEED = 7


def policy(
    train: float, validation: float, test: float, *, provisional: bool = False
) -> SplitPolicy:
    return SplitPolicy(
        policy_id="family_holdout",
        proportions=Proportions(train=train, validation=validation, test=test),
        provisional=provisional,
    )


def counts_of(n: int, p: Proportions | None = None) -> tuple[int, int, int]:
    result = partition_counts(n, (p or PROVISIONAL_POLICY.proportions))
    return result["train"], result["validation"], result["test"]


# --- cuántos grupos a cada partición ----------------------------------------------------------


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        (3, (1, 1, 1)),
        (4, (2, 1, 1)),
        (5, (3, 1, 1)),
        (6, (4, 1, 1)),
        (7, (4, 2, 1)),
        (10, (6, 2, 2)),
        (20, (12, 4, 4)),
    ],
)
def test_the_provisional_proportions_give_these_counts(
    groups: int, expected: tuple[int, int, int]
) -> None:
    assert counts_of(groups) == expected


def test_every_partition_gets_at_least_one_group_even_with_a_tiny_proportion() -> None:
    assert counts_of(3, Proportions(train=0.9, validation=0.05, test=0.05)) == (1, 1, 1)
    assert counts_of(10, Proportions(train=0.96, validation=0.02, test=0.02)) == (8, 1, 1)


def test_a_tie_in_the_remainders_goes_to_the_first_partition_in_order() -> None:
    assert counts_of(5, Proportions(train=0.5, validation=0.25, test=0.25)) == (3, 1, 1)
    assert counts_of(7, Proportions(train=0.2, validation=0.4, test=0.4)) == (1, 3, 3)
    assert counts_of(4, Proportions(train=0.3, validation=0.35, test=0.35)) == (1, 2, 1)


def test_a_tie_is_decided_with_the_numbers_as_they_were_written() -> None:
    """0.05, 0.15 y 0.8 de 28 grupos: 1.4, 4.2 y 22.4. Hay empate de restos (0.4) entre
    entrenamiento y prueba y gana entrenamiento; con fracciones binarias ganaría la prueba."""
    assert counts_of(28, Proportions(train=0.05, validation=0.15, test=0.8)) == (2, 4, 22)


def test_the_largest_remainder_wins() -> None:
    assert counts_of(4, Proportions(train=0.4, validation=0.3, test=0.3)) == (2, 1, 1)
    assert counts_of(8, Proportions(train=0.45, validation=0.25, test=0.3)) == (4, 2, 2)


@pytest.mark.parametrize(
    "proportions",
    [
        Proportions(train=0.6, validation=0.2, test=0.2),
        Proportions(train=0.7, validation=0.15, test=0.15),
        Proportions(train=0.5, validation=0.25, test=0.25),
        Proportions(train=0.8, validation=0.1, test=0.1),
        Proportions(train=0.34, validation=0.33, test=0.33),
        Proportions(train=0.9, validation=0.05, test=0.05),
    ],
)
def test_the_counts_always_add_up_and_leave_no_partition_empty(proportions: Proportions) -> None:
    for groups in range(MIN_GROUPS, 80):
        counts = counts_of(groups, proportions)
        assert sum(counts) == groups
        assert min(counts) >= 1


@pytest.mark.parametrize("groups", [0, 1, 2])
def test_fewer_than_three_groups_cannot_fill_three_partitions(groups: int) -> None:
    with pytest.raises(ValueError, match=f"hacen falta al menos 3 grupos y hay {groups}"):
        partition_counts(groups, PROVISIONAL_POLICY.proportions)


def test_the_minimum_is_one_group_per_partition() -> None:
    assert MIN_GROUPS == 3


# --- qué grupos a cada partición --------------------------------------------------------------

GROUPS = [f"FAM_{n:02d}" for n in range(1, 11)]


def rank_by_hash(groups: list[str], seed: int, policy_id: str) -> list[str]:
    def key(group: str) -> tuple[str, str]:
        return hashlib.sha256(f"{seed}|{policy_id}|{group}".encode()).hexdigest(), group

    return sorted(groups, key=key)


def test_the_assignment_follows_the_documented_ranking() -> None:
    assigned = assign_groups(GROUPS, PROVISIONAL_POLICY, SEED)
    ranked = rank_by_hash(GROUPS, SEED, "family_holdout")
    assert [assigned[g] for g in ranked] == ["test"] * 2 + ["validation"] * 2 + ["train"] * 6


def test_the_same_input_and_seed_give_the_same_assignment() -> None:
    assert assign_groups(GROUPS, PROVISIONAL_POLICY, SEED) == assign_groups(
        GROUPS, PROVISIONAL_POLICY, SEED
    )


def test_the_order_in_which_the_groups_arrive_does_not_matter() -> None:
    shuffled = list(GROUPS)
    random.Random(1).shuffle(shuffled)  # noqa: S311 - orden de prueba, no seguridad
    assert assign_groups(shuffled, PROVISIONAL_POLICY, SEED) == assign_groups(
        GROUPS, PROVISIONAL_POLICY, SEED
    )


def test_another_seed_gives_another_assignment_for_some_seeds() -> None:
    base = assign_groups(GROUPS, PROVISIONAL_POLICY, SEED)
    others = {
        tuple(sorted(assign_groups(GROUPS, PROVISIONAL_POLICY, s).items())) for s in range(30)
    }
    assert tuple(sorted(base.items())) in others
    assert len(others) > 5


def test_another_policy_name_gives_another_assignment_for_some_names() -> None:
    results: set[tuple[tuple[str, Partition], ...]] = set()
    for name in ("a1", "a2", "a3", "a4", "a5", "a6"):
        other = SplitPolicy(
            policy_id=name, proportions=PROVISIONAL_POLICY.proportions, provisional=True
        )
        results.add(tuple(sorted(assign_groups(GROUPS, other, SEED).items())))
    assert len(results) > 1


def test_every_group_goes_to_exactly_one_partition_with_the_counted_size() -> None:
    assigned = assign_groups(GROUPS, PROVISIONAL_POLICY, SEED)
    assert set(assigned) == set(GROUPS)
    assert Counter(assigned.values()) == {"train": 6, "validation": 2, "test": 2}


def test_the_test_partition_gets_its_own_count() -> None:
    assigned = assign_groups(GROUPS, policy(0.5, 0.2, 0.3), SEED)
    assert Counter(assigned.values()) == {"train": 5, "validation": 2, "test": 3}


def test_the_proportions_decide_the_sizes() -> None:
    assigned = assign_groups(GROUPS, policy(0.4, 0.3, 0.3), SEED)
    assert Counter(assigned.values()) == {"train": 4, "validation": 3, "test": 3}


def test_a_repeated_group_is_rejected() -> None:
    with pytest.raises(ValueError, match="repetidos"):
        assign_groups(["A", "B", "C", "A"], PROVISIONAL_POLICY, SEED)


def test_too_few_groups_are_rejected() -> None:
    with pytest.raises(ValueError, match="hacen falta al menos 3 grupos"):
        assign_groups(["A", "B"], PROVISIONAL_POLICY, SEED)


def test_a_known_assignment_stays_the_same() -> None:
    """Valores fijos de la primera ejecución: si cambian, no se reproducen particiones ya hechas."""
    assigned = assign_groups(GROUPS, PROVISIONAL_POLICY, SEED)
    assert sorted(g for g, p in assigned.items() if p == "test") == ["FAM_03", "FAM_08"]
    assert sorted(g for g, p in assigned.items() if p == "validation") == ["FAM_05", "FAM_10"]


# --- la partición de los escenarios (QA14) ----------------------------------------------------


SCENARIOS = scenarios_of(5)


def split_of(scenarios: list[Scenario] | None = None, seed: int = SEED):  # noqa: ANN201
    return create_split(
        SCENARIOS if scenarios is None else scenarios, PROVISIONAL_POLICY, seed, "SPLIT_T"
    )


def test_a_family_always_goes_whole_to_one_partition() -> None:
    split = split_of()
    for group in {s.group_id for s in SCENARIOS}:
        partitions = {a.partition for a in split.assignments if a.group_id == group}
        assert len(partitions) == 1


def test_all_the_scenarios_of_the_set_are_assigned_once_in_order() -> None:
    split = split_of()
    assert [a.scenario_id for a in split.assignments] == [s.scenario_id for s in SCENARIOS]
    assert [a.group_id for a in split.assignments] == [s.group_id for s in SCENARIOS]


def test_five_families_are_split_three_one_one() -> None:
    split = split_of()
    groups: dict[Partition, set[str]] = {"train": set(), "validation": set(), "test": set()}
    for assignment in split.assignments:
        groups[assignment.partition].add(assignment.group_id)
    assert [len(groups[p]) for p in ("train", "validation", "test")] == [3, 1, 1]


def test_the_split_is_frozen_and_records_seed_and_split_id() -> None:
    split = split_of()
    assert split.frozen is True
    assert (split.split_id, split.seed, split.schema_version) == ("SPLIT_T", SEED, "1.0.0")


def test_the_policy_text_says_when_the_proportions_are_provisional() -> None:
    split = split_of()
    assert split.policy == (
        "family_holdout: familias completas; proporciones provisionales (DEC07 pendiente) de "
        "grupos 0.6/0.2/0.2 (entrenamiento/validación/prueba)"
    )


def test_the_policy_text_for_an_approved_policy_has_no_provisional_note() -> None:
    split = create_split(SCENARIOS, policy(0.5, 0.25, 0.25), SEED, "SPLIT_T")
    assert split.policy == (
        "family_holdout: familias completas; proporciones de grupos 0.5/0.25/0.25 "
        "(entrenamiento/validación/prueba)"
    )


def test_the_same_inputs_give_the_same_split() -> None:
    assert split_of().model_dump_json() == split_of().model_dump_json()


def test_the_split_does_not_depend_on_the_order_of_the_scenarios() -> None:
    forward = {a.scenario_id: a.partition for a in split_of().assignments}
    backward = {a.scenario_id: a.partition for a in split_of(list(reversed(SCENARIOS))).assignments}
    assert forward == backward


def test_another_seed_changes_the_partition_for_some_seeds() -> None:
    partitions = {tuple(a.partition for a in split_of(seed=s).assignments) for s in range(20)}
    assert len(partitions) > 3


def test_the_created_split_passes_every_rule_and_round_trips() -> None:
    split = split_of()
    assert split_issues(split, SCENARIOS) == []
    assert parse_split(split.model_dump(mode="json")) == split


def test_creating_does_not_change_the_scenarios() -> None:
    before = [s.model_dump_json() for s in SCENARIOS]
    split_of()
    assert [s.model_dump_json() for s in SCENARIOS] == before


def problems(scenarios: list[Scenario]) -> list[CaseIssue]:
    with pytest.raises(SplitInvalidError) as raised:
        create_split(scenarios, PROVISIONAL_POLICY, SEED, "SPLIT_T")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    return list(raised.value.issues)


def test_exactly_three_families_fill_the_three_partitions() -> None:
    split = split_of(scenarios_of(3))
    by_group = {a.group_id: a.partition for a in split.assignments}
    assert sorted(by_group.values()) == ["test", "train", "validation"]


def test_two_families_cannot_fill_three_partitions() -> None:
    [issue] = problems(scenarios_of(2))
    assert (issue.rule_id, issue.field) == ("SPLIT-C04", "scenarios")
    assert issue.message == "hacen falta al menos 3 grupos (uno por partición) y hay 2"


def test_no_scenarios_cannot_be_split() -> None:
    [issue] = problems([])
    assert (issue.rule_id, issue.field) == ("SPLIT-C01", "scenarios")
    assert issue.message == "no hay escenarios que asignar"


def test_a_repeated_scenario_is_rejected() -> None:
    [issue] = problems([*SCENARIOS, SCENARIOS[0]])
    assert (issue.rule_id, issue.field) == ("SPLIT-C01", f"scenarios[{len(SCENARIOS)}]")
    assert issue.message == f"el escenario «{SCENARIOS[0].scenario_id}» está repetido"


def test_scenarios_of_a_single_family_cannot_be_split() -> None:
    [issue] = problems([s for s in SCENARIOS if s.group_id == "FAM_01"])
    assert "hay 1" in issue.message


def test_a_field_source_that_would_land_in_two_parts_stops_the_split() -> None:
    shared = [
        s.model_copy(update={"origin": "field_derived", "source_ids": ["DIA_UNICO"]})
        for s in SCENARIOS
    ]
    issues = problems(shared)
    assert [i.rule_id for i in issues] == ["SPLIT-C06"]
    assert "DIA_UNICO" in issues[0].message


def test_field_sources_that_are_not_shared_do_not_stop_the_split() -> None:
    separate = [
        s.model_copy(update={"origin": "field_derived", "source_ids": [f"DIA_{s.group_id}"]})
        for s in SCENARIOS
    ]
    assert split_issues(split_of(separate), separate) == []


def test_synthetic_scenarios_sharing_a_source_do_not_stop_the_split() -> None:
    assert {s.source_ids[0] for s in SCENARIOS} == {"SYNTHETIC_FIXTURE"}
    assert split_of().frozen


def test_scenarios_from_a_real_spec_with_several_variants_stay_together() -> None:
    members = generated(families_spec(4, variants=3, seeds=3))
    scenarios = [m.scenario for m in members]
    split = create_split(scenarios, PROVISIONAL_POLICY, SEED, "SPLIT_T")
    by_family: dict[str, set[str]] = {}
    for assignment in split.assignments:
        by_family.setdefault(assignment.group_id, set()).add(assignment.partition)
    assert all(len(parts) == 1 for parts in by_family.values())
    assert len(split.assignments) == 4 * 3 * 3


def test_a_hundred_families_are_split_quickly() -> None:
    scenarios = scenarios_of(100, variants=2, seeds=10)
    started = time.perf_counter()
    split = create_split(scenarios, PROVISIONAL_POLICY, SEED, "SPLIT_T")
    assert len(split.assignments) == 2000
    assert time.perf_counter() - started < 30
    counts = Counter({a.group_id: a.partition for a in split.assignments}.values())
    assert counts == {"train": 60, "validation": 20, "test": 20}
