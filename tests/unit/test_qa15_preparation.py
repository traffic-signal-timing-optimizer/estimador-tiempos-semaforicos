"""Caso de prueba de QA15 (DEV12 F4): un valor atípico solo en la prueba no entra al ajuste.

QA15 completo (entrenar, comparar el paquete del modelo, las transformaciones y la selección) es de
DEV16. Aquí se prepara lo que le toca a DEV12: las filas de ajuste y su huella no cambian si se
altera la prueba, y pedir la prueba para ajustar se bloquea.
"""

import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scenario_tools import publish_set
from semaforo.aprendizaje.split_access import (
    LeakageError,
    Purpose,
    check_ids,
    development_view,
    ids_for,
    rows_digest,
    rows_for,
)
from semaforo.aprendizaje.split_store import publish_split, read_split
from semaforo.aprendizaje.splits import PROVISIONAL_POLICY
from semaforo.datos.scenario_set import read_scenario_set
from semaforo.dominio.split import Split

NOW = datetime(2026, 11, 2, 15, 30, 0, tzinfo=UTC)
OUTLIER = 1_000_000.0


def stored_split(tmp_path: Path, seed: int = 7) -> Split:
    """Una partición publicada y leída de nuevo, como la usaría el entrenamiento."""
    workspace = tmp_path / "datos"
    scenario_set = read_scenario_set(publish_set(workspace, 6).folder)
    published = publish_split(workspace, scenario_set, PROVISIONAL_POLICY, seed, clock=lambda: NOW)
    return read_split(published.folder).split


def labels_of(split: Split) -> dict[str, float]:
    """Una etiqueta sintética por escenario (no es resultado de ninguna búsqueda en SUMO)."""
    return {a.scenario_id: 10.0 + n for n, a in enumerate(split.assignments)}


def with_outlier(
    split: Split, labels: dict[str, float], value: float = OUTLIER
) -> dict[str, float]:
    """``labels`` con ``value`` en el primer escenario de la prueba."""
    victim = ids_for(split, "test", "final_evaluation")[0]
    return {**labels, victim: value}


# --- la huella de las filas -------------------------------------------------------------------


def test_the_digest_of_known_rows_is_the_documented_one() -> None:
    text = b"A\t1.0\nB\t2.5\n"
    assert rows_digest({"B": 2.5, "A": 1.0}) == hashlib.sha256(text).hexdigest()


def test_the_digest_of_no_rows_is_the_digest_of_nothing() -> None:
    assert rows_digest({}) == hashlib.sha256(b"").hexdigest()


def test_the_digest_does_not_depend_on_the_order_of_the_rows() -> None:
    assert rows_digest({"A": 1.0, "B": 2.0}) == rows_digest({"B": 2.0, "A": 1.0})


def test_the_digest_changes_with_a_value_an_id_or_an_extra_row() -> None:
    base = rows_digest({"A": 1.0, "B": 2.0})
    assert rows_digest({"A": 1.0, "B": 2.1}) != base
    assert rows_digest({"A": 1.0, "C": 2.0}) != base
    assert rows_digest({"A": 1.0, "B": 2.0, "C": 3.0}) != base


def test_the_digest_tells_apart_one_row_from_two_that_look_alike() -> None:
    assert rows_digest({"A": 1.0}) != rows_digest({"A": 1.0, "A\t1.0\nB": 0.0})


def test_the_digest_keeps_the_exact_float() -> None:
    assert rows_digest({"A": 0.1 + 0.2}) != rows_digest({"A": 0.3})
    assert rows_digest({"A": 1}) != rows_digest({"A": 1.0})


# --- QA15: el valor atípico de la prueba no entra al ajuste -----------------------------------


@pytest.mark.parametrize("purpose", ["fit", "select", "refit"])
def test_altering_the_test_does_not_change_what_the_fit_receives(
    tmp_path: Path, purpose: Purpose
) -> None:
    split = stored_split(tmp_path)
    labels = labels_of(split)
    plain = rows_for(split, labels, purpose)
    for value in (OUTLIER, -1.0, 0.0, 1e300, math.inf, math.nan):
        altered = rows_for(split, with_outlier(split, labels, value), purpose)
        assert rows_digest(altered) == rows_digest(plain)
        assert list(altered) == list(plain)


def test_the_outlier_is_only_in_the_test_rows(tmp_path: Path) -> None:
    split = stored_split(tmp_path)
    labels = with_outlier(split, labels_of(split))
    development = rows_for(split, labels, "refit")
    assert max(development.values()) < 1000
    assert OUTLIER in rows_for(split, labels, "final_evaluation").values()
    assert OUTLIER not in development.values()


def test_the_digest_of_the_final_evaluation_does_see_the_change(tmp_path: Path) -> None:
    split = stored_split(tmp_path)
    labels = labels_of(split)
    before = rows_digest(rows_for(split, labels, "final_evaluation"))
    after = rows_digest(rows_for(split, with_outlier(split, labels), "final_evaluation"))
    assert before != after


def test_the_digest_of_the_fit_does_see_a_change_in_the_training_rows(tmp_path: Path) -> None:
    split = stored_split(tmp_path)
    labels = labels_of(split)
    victim = ids_for(split, "train", "fit")[0]
    changed = {**labels, victim: OUTLIER}
    assert rows_digest(rows_for(split, changed, "fit")) != rows_digest(
        rows_for(split, labels, "fit")
    )


def test_asking_for_the_outlier_to_fit_is_blocked(tmp_path: Path) -> None:
    split = stored_split(tmp_path)
    victim = ids_for(split, "test", "final_evaluation")[0]
    with pytest.raises(LeakageError) as raised:
        check_ids(split, [victim], "fit")
    assert f"«{victim}» (test)" in raised.value.message
    with pytest.raises(LeakageError):
        ids_for(split, "test", "refit")


def test_the_development_view_does_not_even_know_the_outlier_scenario(tmp_path: Path) -> None:
    split = stored_split(tmp_path)
    victim = ids_for(split, "test", "final_evaluation")[0]
    view = development_view(split)
    assert victim not in view.development_ids
    assert victim not in repr(view)


def test_it_holds_for_other_partitions_too(tmp_path: Path) -> None:
    for seed in range(8):
        split = stored_split(tmp_path / f"s{seed}", seed=seed)
        labels = labels_of(split)
        for purpose in ("fit", "select", "refit"):
            assert rows_digest(rows_for(split, with_outlier(split, labels), purpose)) == (
                rows_digest(rows_for(split, labels, purpose))
            )
