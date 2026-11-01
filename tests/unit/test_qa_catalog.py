"""El catálogo de QA01 a QA10 no se pudre: toda entrada existe y están todos los casos."""

import csv
from pathlib import Path

import pytest

from qa_catalog import CATALOG, ROOT, Qa, list_tests, resolve

MATRIX = ROOT / "documentacion" / "matrices" / "pruebas.csv"
KINDS = {"Unitario", "Integración", "Seguridad"}


def documented() -> dict[str, tuple[str, set[str]]]:
    """QA01 a QA10 de la documentación: tipo y conjunto de historias."""
    with MATRIX.open(encoding="utf-8-sig", newline="") as stream:
        rows = {row["id"]: row for row in csv.DictReader(stream)}
    return {
        qa_id: (row["tipo"], set(row["historias"].split(";")))
        for qa_id, row in rows.items()
        if qa_id in {f"QA{n:02d}" for n in range(1, 11)}
    }


def test_the_catalog_has_exactly_qa01_to_qa10_in_order() -> None:
    assert [qa.qa_id for qa in CATALOG] == [f"QA{n:02d}" for n in range(1, 11)]
    assert set(documented()) == {qa.qa_id for qa in CATALOG}


def test_each_case_has_the_kind_the_documentation_gives_it() -> None:
    kinds = {qa_id: kind for qa_id, (kind, _) in documented().items()}
    assert {qa.qa_id: qa.kind for qa in CATALOG} == kinds
    assert {qa.kind for qa in CATALOG} <= KINDS


@pytest.mark.parametrize("qa", CATALOG, ids=[qa.qa_id for qa in CATALOG])
def test_every_entry_points_to_at_least_one_existing_test(qa: Qa) -> None:
    assert qa.key_tests, f"{qa.qa_id} no tiene pruebas clave"
    for entry in qa.key_tests:
        assert resolve(entry), f"{qa.qa_id}: «{entry}» no corresponde a ninguna prueba"


@pytest.mark.parametrize("qa", CATALOG, ids=[qa.qa_id for qa in CATALOG])
def test_no_entry_is_repeated_and_every_case_has_a_task_and_a_summary(qa: Qa) -> None:
    assert len(set(qa.key_tests)) == len(qa.key_tests)
    assert qa.task
    assert qa.summary


def test_the_resolver_finds_by_prefix_and_by_file() -> None:
    by_prefix = resolve("tests/unit/test_case_rules.py::test_qa01_")
    assert by_prefix
    assert all(item.startswith("tests/unit/test_case_rules.py::test_qa01_") for item in by_prefix)
    assert resolve("tests/unit/test_paths.py") == ["tests/unit/test_paths.py"]


def test_the_resolver_returns_nothing_for_what_does_not_exist() -> None:
    assert resolve("tests/unit/no_existe.py") == []
    assert resolve("tests/unit/test_paths.py::prueba_que_no_existe") == []
    assert resolve("tests/unit/test_paths.py::test_a_prefix_nobody_uses") == []


def test_a_file_without_tests_does_not_count(tmp_path: Path) -> None:
    (tmp_path / "vacio.py").write_text("X = 1\n", encoding="utf-8")
    assert list_tests(tmp_path / "vacio.py") == []
