"""Pruebas del orden de ajuste del ciclo de un caso (DEV13, F3; decisiones D6 y D18 de F0).

Datos sintéticos (la réplica de caso-001 está en ``timing_tools``).
"""

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from semaforo.caso.adjust_order_file import ADJUST_ORDER_FILE, MAX_ORDER_BYTES, read_adjust_order
from semaforo.caso.errors import CasoError
from semaforo.dominio.adjust_order import (
    AdjustOrder,
    AdjustOrderInvalidError,
    order_issues,
    parse_adjust_order,
)
from semaforo.dominio.case import CaseIssue
from semaforo.dominio.errors import ErrorCode
from timing_tools import (
    CASE_ID,
    PRIORITY,
    VARIABLE_IDS,
    make_case,
    order_data,
    prepared,
    priority_order,
)

# ---------------------------------------------------------------------------
# Estructura (ORDER-S01 a S03)
# ---------------------------------------------------------------------------


def test_a_valid_order_is_parsed() -> None:
    order = parse_adjust_order(order_data())
    assert order.cut_order == PRIORITY
    assert order.case_id == CASE_ID
    assert order.evidence == ["criterio de prueba"]


def test_the_schema_version_has_a_default_and_only_one_value() -> None:
    data = order_data()
    del data["schema_version"]
    assert parse_adjust_order(data).schema_version == "1.0.0"
    with pytest.raises(AdjustOrderInvalidError) as raised:
        parse_adjust_order(order_data(schema_version="2.0.0"))
    assert raised.value.issues[0].rule_id == "ORDER-S01"


@pytest.mark.parametrize("missing", ["case_id", "case_version", "cut_order", "evidence"])
def test_every_field_is_required(missing: str) -> None:
    data = order_data()
    del data[missing]
    with pytest.raises(AdjustOrderInvalidError) as raised:
        parse_adjust_order(data)
    assert [(i.rule_id, i.field) for i in raised.value.issues] == [("ORDER-S01", missing)]


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"extra": 1}, "ORDER-S01"),
        ({"cut_order": []}, "ORDER-S01"),
        ({"evidence": []}, "ORDER-S01"),
        ({"cut_order": "t7,t5"}, "ORDER-S01"),
        ({"cut_order": [7, 5]}, "ORDER-S01"),
        ({"evidence": "texto"}, "ORDER-S01"),
        ({"case_id": " caso"}, "ORDER-S02"),
        ({"cut_order": ["t7", ""]}, "ORDER-S02"),
        ({"cut_order": ["t7\N{ZERO WIDTH SPACE}"]}, "ORDER-S02"),
        ({"case_version": "1.0"}, "ORDER-S03"),
        ({"case_version": "01.0.0"}, "ORDER-S03"),
    ],
)
def test_a_structure_problem_is_reported_with_its_rule(change: dict[str, Any], rule: str) -> None:
    with pytest.raises(AdjustOrderInvalidError) as raised:
        parse_adjust_order(order_data(**change))
    assert raised.value.issues[0].rule_id == rule


@pytest.mark.parametrize("value", [None, [], "orden", 5, ["t7"]])
def test_something_that_is_not_an_object_is_rejected(value: object) -> None:
    with pytest.raises(AdjustOrderInvalidError) as raised:
        parse_adjust_order(value)
    assert raised.value.issues[0].rule_id == "ORDER-S01"


def test_the_error_has_the_code_and_the_first_problem() -> None:
    with pytest.raises(AdjustOrderInvalidError) as raised:
        parse_adjust_order(order_data(cut_order=[], evidence=[]))
    error = raised.value
    assert error.code is ErrorCode.INPUT_SCHEMA
    assert len(error.issues) == 2
    assert str(error).startswith("INPUT_SCHEMA: el orden de ajuste no es válido: ORDER-S01 en ")
    assert str(error).endswith("(y 1 más)")


def test_an_error_without_field_does_not_say_where_and_needs_a_problem() -> None:
    error = AdjustOrderInvalidError([CaseIssue("ORDER-C02", None, "algo")])
    assert str(error) == "INPUT_SCHEMA: el orden de ajuste no es válido: ORDER-C02: algo"
    assert error.field is None
    with pytest.raises(ValueError, match="al menos un problema"):
        AdjustOrderInvalidError([])


def test_an_order_cannot_be_modified() -> None:
    order = priority_order()
    with pytest.raises((TypeError, ValueError)):
        order.case_id = "otro"  # type: ignore[misc]
    assert not dataclasses.is_dataclass(order)


# ---------------------------------------------------------------------------
# Frente al caso (ORDER-C01 a C03)
# ---------------------------------------------------------------------------


def test_the_priority_order_fits_the_case() -> None:
    assert order_issues(make_case(), priority_order()) == []


def test_the_sequence_order_also_fits() -> None:
    assert order_issues(make_case(), priority_order(VARIABLE_IDS)) == []


def test_an_order_of_another_case_or_version_is_reported() -> None:
    order = parse_adjust_order(order_data(case_id="OTRO", case_version="2.0.0"))
    issues = order_issues(make_case(), order)
    assert [(i.rule_id, i.field) for i in issues] == [
        ("ORDER-C01", "case_id"),
        ("ORDER-C01", "case_version"),
    ]
    assert "'OTRO'" in issues[0].message
    assert "'2.0.0'" in issues[1].message


def test_a_missing_variable_slot_is_reported() -> None:
    issues = order_issues(make_case(), priority_order(["t7", "t5", "t3"]))
    assert [(i.rule_id, i.field, i.message) for i in issues] == [
        ("ORDER-C02", "cut_order", "falta el slot variable 't1'")
    ]


def test_a_repeated_slot_is_reported_where_it_repeats() -> None:
    issues = order_issues(make_case(), priority_order(["t7", "t5", "t7", "t3", "t1"]))
    assert [(i.rule_id, i.field, i.message) for i in issues] == [
        ("ORDER-C02", "cut_order[2]", "el slot 't7' está repetido")
    ]


def test_a_fixed_or_unknown_slot_is_reported() -> None:
    issues = order_issues(make_case(), priority_order(["t7", "t2", "t5", "zz", "t3", "t1"]))
    assert [(i.rule_id, i.field) for i in issues] == [
        ("ORDER-C03", "cut_order[1]"),
        ("ORDER-C03", "cut_order[3]"),
    ]
    assert "fijo" in issues[0].message
    assert "no es del caso" in issues[1].message


def test_every_problem_is_reported_together_in_order() -> None:
    order = parse_adjust_order(order_data(["t2", "t2"], case_id="OTRO"))
    issues = order_issues(make_case(), order)
    assert [(i.rule_id, i.field) for i in issues] == [
        ("ORDER-C01", "case_id"),
        ("ORDER-C03", "cut_order[0]"),
        ("ORDER-C02", "cut_order[1]"),
        *[("ORDER-C02", "cut_order")] * 4,
    ]


def test_a_huge_order_is_capped() -> None:
    order = priority_order([f"x{index}" for index in range(500)])
    issues = order_issues(make_case(), order)
    assert len(issues) == 101
    # 500 desconocidos y los 4 slots variables que faltan: 504 problemas; se muestran 100.
    assert issues[-1].message == "y 404 problemas más sin mostrar"


def test_prepare_rejects_an_order_that_does_not_fit() -> None:
    with pytest.raises(AdjustOrderInvalidError) as raised:
        prepared(order=priority_order(["t7", "t5"]))
    assert [i.rule_id for i in raised.value.issues] == ["ORDER-C02", "ORDER-C02"]


def test_prepare_keeps_the_declared_order_and_gives_in_reverse() -> None:
    ready = prepared(order=priority_order())
    assert ready.order_source == "declared"
    assert ready.cut_order == ("t7", "t5", "t3", "t1")
    assert ready.give_order == ("t1", "t3", "t5", "t7")


def test_without_an_order_the_sequence_is_used_to_cut_and_to_give() -> None:
    ready = prepared()
    assert ready.order_source == "sequence"
    assert ready.cut_order == ready.give_order == tuple(VARIABLE_IDS)


# ---------------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------------


def write(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / ADJUST_ORDER_FILE
    path.write_bytes(content)
    return path


def test_the_file_is_read_and_validated(tmp_path: Path) -> None:
    path = write(tmp_path, json.dumps(order_data()).encode("utf-8"))
    assert read_adjust_order(path) == priority_order()


def test_a_file_with_a_byte_order_mark_is_read(tmp_path: Path) -> None:
    path = write(tmp_path, b"\xef\xbb\xbf" + json.dumps(order_data()).encode("utf-8"))
    assert read_adjust_order(path).cut_order == PRIORITY


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        (b'{"case_id": "a", "case_id": "b"}', "más de una vez"),
        (b'{"cut_order": NaN}', "NaN"),
        (b"{", "no es JSON"),
        (b"\xff\xfe", "UTF-8"),
        (b"[" * 30_000 + b"]" * 30_000, "anidado"),
    ],
    ids=["clave-repetida", "nan", "roto", "no-utf8", "anidado"],
)
def test_a_broken_file_is_rejected_with_its_reason(
    tmp_path: Path, content: bytes, fragment: str
) -> None:
    with pytest.raises(CasoError) as raised:
        read_adjust_order(write(tmp_path, content))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert fragment in raised.value.message


def test_the_size_limit_is_64_kib(tmp_path: Path) -> None:
    assert MAX_ORDER_BYTES == 64 * 1024
    small = order_data(evidence=["x" * 60_000])
    assert read_adjust_order(write(tmp_path, json.dumps(small).encode("utf-8"))).evidence
    big = order_data(evidence=["x" * 70_000])
    with pytest.raises(CasoError) as raised:
        read_adjust_order(write(tmp_path, json.dumps(big).encode("utf-8")))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert "65536" in raised.value.message


def test_a_missing_file_or_a_folder_is_rejected(tmp_path: Path) -> None:
    for path in (tmp_path / "no-existe.json", tmp_path):
        with pytest.raises(CasoError) as raised:
            read_adjust_order(path)
        assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_a_file_with_a_bad_structure_raises_the_domain_error(tmp_path: Path) -> None:
    path = write(tmp_path, json.dumps(order_data(cut_order=[])).encode("utf-8"))
    with pytest.raises(AdjustOrderInvalidError):
        read_adjust_order(path)


def test_the_order_model_has_no_extra_fields() -> None:
    assert set(AdjustOrder.model_fields) == {
        "schema_version",
        "case_id",
        "case_version",
        "cut_order",
        "evidence",
    }
