"""Bloqueo de la fuga de la prueba hacia el ajuste (DEV12 F2, HU07, ADR07)."""

import dataclasses
import json

import pytest

from scenario_tools import scenarios_of
from semaforo.aprendizaje.split_access import (
    ALLOWED,
    MAX_SHOWN,
    DevelopmentView,
    LeakageError,
    Purpose,
    check_ids,
    development_view,
    ids_for,
    rows_for,
)
from semaforo.aprendizaje.splits import PROVISIONAL_POLICY, create_split
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.split import PARTITIONS, Partition, Split

SPLIT = create_split(scenarios_of(10, variants=1, seeds=2), PROVISIONAL_POLICY, 7, "SPLIT_T")


def ids_of(split: Split, partition: Partition) -> list[str]:
    return [a.scenario_id for a in split.assignments if a.partition == partition]


TRAIN = ids_of(SPLIT, "train")
VALIDATION = ids_of(SPLIT, "validation")
TEST = ids_of(SPLIT, "test")
PURPOSES: tuple[Purpose, ...] = ("fit", "select", "refit", "final_evaluation")


# --- la vista de desarrollo -------------------------------------------------------------------


def test_the_split_has_the_expected_sizes() -> None:
    assert (len(TRAIN), len(VALIDATION), len(TEST)) == (12, 4, 4)


def test_the_development_view_has_the_train_and_validation_ids_only() -> None:
    view = development_view(SPLIT)
    assert list(view.train_ids) == TRAIN
    assert list(view.validation_ids) == VALIDATION
    assert list(view.development_ids) == TRAIN + VALIDATION
    assert view.split_id == "SPLIT_T"


def test_the_development_view_has_the_groups_of_each_part() -> None:
    view = development_view(SPLIT)
    train_groups = {a.group_id for a in SPLIT.assignments if a.partition == "train"}
    validation_groups = {a.group_id for a in SPLIT.assignments if a.partition == "validation"}
    assert set(view.train_groups) == train_groups
    assert set(view.validation_groups) == validation_groups
    assert len(view.train_groups) == 6
    assert len(view.validation_groups) == 2


def test_nothing_of_the_test_is_in_the_development_view() -> None:
    view = development_view(SPLIT)
    test_groups = {a.group_id for a in SPLIT.assignments if a.partition == "test"}
    text = repr(view) + json.dumps(dataclasses.asdict(view))
    assert not any(scenario_id in text for scenario_id in TEST)
    assert not any(group in text for group in test_groups)
    assert {field.name for field in dataclasses.fields(DevelopmentView)} == {
        "split_id",
        "train_ids",
        "validation_ids",
        "train_groups",
        "validation_groups",
    }


def test_the_view_is_immutable() -> None:
    view = development_view(SPLIT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.train_ids = ()  # type: ignore[misc]


def test_the_view_does_not_change_the_split() -> None:
    before = SPLIT.model_dump_json()
    development_view(SPLIT)
    assert SPLIT.model_dump_json() == before


# --- qué se puede pedir para cada finalidad ---------------------------------------------------

ALLOWED_TABLE = {
    ("fit", "train"): True,
    ("fit", "validation"): False,
    ("fit", "test"): False,
    ("select", "train"): False,
    ("select", "validation"): True,
    ("select", "test"): False,
    ("refit", "train"): True,
    ("refit", "validation"): True,
    ("refit", "test"): False,
    ("final_evaluation", "train"): False,
    ("final_evaluation", "validation"): False,
    ("final_evaluation", "test"): True,
}


def test_the_documented_table_has_every_combination() -> None:
    assert set(ALLOWED_TABLE) == {(p, q) for p in PURPOSES for q in PARTITIONS}
    assert {p: set(parts) for p, parts in ALLOWED.items()} == {
        p: {q for q in PARTITIONS if ALLOWED_TABLE[(p, q)]} for p in PURPOSES
    }


@pytest.mark.parametrize(("purpose", "partition"), sorted(ALLOWED_TABLE))
def test_ids_are_given_or_blocked_by_purpose(purpose: Purpose, partition: Partition) -> None:
    expected = {"train": TRAIN, "validation": VALIDATION, "test": TEST}[partition]
    if ALLOWED_TABLE[(purpose, partition)]:
        assert list(ids_for(SPLIT, partition, purpose)) == expected
    else:
        with pytest.raises(LeakageError):
            ids_for(SPLIT, partition, purpose)


@pytest.mark.parametrize("purpose", ["fit", "select", "refit"])
def test_asking_for_the_test_to_fit_select_or_refit_says_what_was_asked(purpose: Purpose) -> None:
    with pytest.raises(LeakageError) as raised:
        ids_for(SPLIT, "test", purpose)
    error = raised.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert error.field == "partition"
    assert f"para «{purpose}» solo se pueden pedir: " in error.message
    assert error.message.endswith("se pidió «test»")


def test_the_message_names_the_allowed_partitions() -> None:
    with pytest.raises(LeakageError) as raised:
        ids_for(SPLIT, "test", "refit")
    assert raised.value.message == (
        "para «refit» solo se pueden pedir: train, validation; se pidió «test»"
    )


def test_the_test_ids_only_come_out_for_the_final_evaluation() -> None:
    assert list(ids_for(SPLIT, "test", "final_evaluation")) == TEST


def test_training_cannot_be_requested_for_the_final_evaluation() -> None:
    with pytest.raises(LeakageError, match="solo se pueden pedir: test"):
        ids_for(SPLIT, "train", "final_evaluation")


@pytest.mark.parametrize("purpose", ["evaluar", "", "FIT", "test"])
def test_an_unknown_purpose_is_rejected(purpose: str) -> None:
    with pytest.raises(LeakageError) as raised:
        ids_for(SPLIT, "train", purpose)  # type: ignore[arg-type]
    assert raised.value.field == "purpose"
    assert "finalidad" in raised.value.message
    assert "fit, select, refit, final_evaluation" in raised.value.message


# --- comprobar identificadores ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("purpose", "ids"),
    [
        ("fit", TRAIN),
        ("select", VALIDATION),
        ("refit", TRAIN + VALIDATION),
        ("final_evaluation", TEST),
        ("fit", []),
    ],
)
def test_ids_from_allowed_partitions_pass(purpose: Purpose, ids: list[str]) -> None:
    check_ids(SPLIT, ids, purpose)


def test_a_test_id_among_the_fit_ids_is_blocked_and_named() -> None:
    with pytest.raises(LeakageError) as raised:
        check_ids(SPLIT, [*TRAIN[:3], TEST[0], *TRAIN[3:5]], "fit")
    error = raised.value
    assert error.field == "scenario_ids"
    assert error.message == (
        f"para «fit» solo se admiten escenarios de: train; no sirven «{TEST[0]}» (test)"
    )


def test_a_validation_id_among_the_fit_ids_is_blocked() -> None:
    with pytest.raises(LeakageError, match=rf"«{VALIDATION[0]}» \(validation\)"):
        check_ids(SPLIT, [TRAIN[0], VALIDATION[0]], "fit")


def test_an_unknown_id_is_blocked_because_its_origin_cannot_be_known() -> None:
    with pytest.raises(LeakageError, match=r"«FANTASMA» \(desconocido\)"):
        check_ids(SPLIT, [TRAIN[0], "FANTASMA"], "refit")


def test_only_the_first_offenders_are_listed() -> None:
    big = create_split(scenarios_of(10, variants=2, seeds=5), PROVISIONAL_POLICY, 7, "SPLIT_B")
    offenders = [a.scenario_id for a in big.assignments if a.partition != "train"]
    assert len(offenders) == 40
    with pytest.raises(LeakageError) as raised:
        check_ids(big, offenders, "fit")
    shown = raised.value.message.count("«") - 1  # el de la finalidad
    assert shown == 10
    assert raised.value.message.endswith("y 30 más")


def test_the_number_of_names_shown_is_ten() -> None:
    assert MAX_SHOWN == 10


def test_exactly_ten_offenders_have_no_more_note() -> None:
    big = create_split(scenarios_of(10, variants=2, seeds=5), PROVISIONAL_POLICY, 7, "SPLIT_B")
    ten = [a.scenario_id for a in big.assignments if a.partition != "train"][:10]
    with pytest.raises(LeakageError) as raised:
        check_ids(big, ten, "fit")
    assert " más" not in raised.value.message
    assert raised.value.message.count("«") - 1 == 10


def test_check_ids_rejects_an_unknown_purpose() -> None:
    with pytest.raises(LeakageError, match="finalidad"):
        check_ids(SPLIT, TRAIN, "otra")  # type: ignore[arg-type]


# --- filas ------------------------------------------------------------------------------------

LABELS = {scenario_id: float(n) for n, scenario_id in enumerate(TRAIN + VALIDATION + TEST)}


def test_rows_for_fit_gives_only_the_training_rows_in_split_order() -> None:
    rows = rows_for(SPLIT, LABELS, "fit")
    assert list(rows) == TRAIN
    assert all(rows[scenario_id] == LABELS[scenario_id] for scenario_id in TRAIN)


@pytest.mark.parametrize(
    ("purpose", "ids"),
    [
        ("fit", TRAIN),
        ("select", VALIDATION),
        ("refit", [i for i in (a.scenario_id for a in SPLIT.assignments) if i not in TEST]),
        ("final_evaluation", TEST),
    ],
)
def test_rows_for_each_purpose_are_only_the_allowed_ones(purpose: Purpose, ids: list[str]) -> None:
    assert list(rows_for(SPLIT, LABELS, purpose)) == ids


def test_the_test_rows_never_reach_the_fit_even_if_they_are_in_the_input() -> None:
    altered = {**LABELS, **{scenario_id: 1e9 for scenario_id in TEST}}
    assert rows_for(SPLIT, altered, "fit") == rows_for(SPLIT, LABELS, "fit")
    assert rows_for(SPLIT, altered, "refit") == rows_for(SPLIT, LABELS, "refit")
    assert rows_for(SPLIT, altered, "select") == rows_for(SPLIT, LABELS, "select")


def test_rows_missing_from_the_input_are_just_missing() -> None:
    partial = {scenario_id: 1.0 for scenario_id in TRAIN[:3]}
    assert list(rows_for(SPLIT, partial, "fit")) == TRAIN[:3]


def test_rows_for_an_unknown_scenario_are_blocked() -> None:
    with pytest.raises(LeakageError) as raised:
        rows_for(SPLIT, {**LABELS, "FANTASMA": 1.0}, "fit")
    assert raised.value.field == "rows"
    assert raised.value.message == "la partición no conoce estos escenarios: «FANTASMA»"


def test_many_unknown_rows_are_summarised() -> None:
    rows = {f"X{n}": 1.0 for n in range(13)}
    with pytest.raises(LeakageError) as raised:
        rows_for(SPLIT, rows, "fit")
    assert raised.value.message.endswith("y 3 más")
    assert raised.value.message.count("«") == 10


def test_exactly_ten_unknown_rows_have_no_more_note() -> None:
    rows = {f"X{n}": 1.0 for n in range(10)}
    with pytest.raises(LeakageError) as raised:
        rows_for(SPLIT, rows, "fit")
    assert " más" not in raised.value.message
    assert raised.value.message.count("«") == 10


def test_rows_for_rejects_an_unknown_purpose() -> None:
    with pytest.raises(LeakageError, match="finalidad"):
        rows_for(SPLIT, LABELS, "otra")  # type: ignore[arg-type]


def test_rows_for_does_not_change_its_input() -> None:
    before = dict(LABELS)
    rows_for(SPLIT, LABELS, "fit")
    assert LABELS == before


def test_the_error_is_an_input_error() -> None:
    with pytest.raises(LeakageError) as raised:
        ids_for(SPLIT, "test", "fit")
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
