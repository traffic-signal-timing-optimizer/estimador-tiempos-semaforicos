"""Seguridad de las reglas temporales (DEV13): propuestas, caso y orden de ajuste no confiables.

Una propuesta de duraciones, el archivo del orden de ajuste y el caso son entradas no confiables:
se prueba que lo hostil no tumba el programa (el corrector nunca lanza ante una propuesta
inválida), que los mensajes no repiten textos enormes del usuario, que el tiempo y la memoria
crecen de forma lineal y que los archivos con enlaces o de tamaño excesivo se rechazan.
"""

import copy
import json
import random
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from semaforo.caso.adjust_order_file import MAX_ORDER_BYTES, read_adjust_order
from semaforo.caso.errors import CasoError
from semaforo.dominio.adjust_order import AdjustOrderInvalidError, order_issues, parse_adjust_order
from semaforo.dominio.case import MAX_ISSUES, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import Correction, check_plan, correct, prepare, summarize
from semaforo.dominio.timing import MAX_SHOWN_CHARS, reconstruct
from timing_tools import (
    BASELINE,
    BASELINE_VARIABLE,
    CASE_ID,
    CASE_VERSION,
    DEMO_CASE,
    VARIABLE_IDS,
    order_data,
    prepared,
    priority_order,
)

MESSAGE_LIMIT = 400


def run(proposal: object, **claim: str) -> Correction:
    return correct(
        prepared(None, priority_order()),
        proposal,  # type: ignore[arg-type]
        **{"case_id": CASE_ID, "case_version": CASE_VERSION, **claim},
    )


def nested_dict(depth: int) -> object:
    value: object = 1.0
    for _ in range(depth):
        value = {"a": value}
    return value


def nested_list(depth: int) -> object:
    value: object = 1.0
    for _ in range(depth):
        value = [value]
    return value


HOSTILE_VALUES = {
    "dict-anidado": nested_dict(50_000),
    "lista-anidada": nested_list(50_000),
    "texto-enorme": "9" * 5_000_000,
    "bytes-enormes": b"9" * 5_000_000,
    "entero-gigante": 10**100_000,
    "entero-negativo-gigante": -(10**100_000),
    "nan": float("nan"),
    "infinito": float("inf"),
    "menos-infinito": float("-inf"),
    "booleano": True,
    "nulo": None,
    "objeto": object(),
    "lista-de-numeros": list(range(100_000)),
    "complejo": 1 + 1j,
}


@pytest.mark.parametrize("value", list(HOSTILE_VALUES.values()), ids=list(HOSTILE_VALUES))
def test_a_hostile_value_in_a_slot_is_invalid_input_and_never_raises(value: object) -> None:
    started = time.perf_counter()
    result = run({**BASELINE_VARIABLE, "t1": value})
    assert time.perf_counter() - started < 5
    assert result.status == "invalid_input"
    assert [i.field for i in result.issues] == ["durations[t1]"]
    assert all(len(i.message) < MESSAGE_LIMIT for i in result.issues)


@pytest.mark.parametrize("value", list(HOSTILE_VALUES.values()), ids=list(HOSTILE_VALUES))
def test_a_hostile_value_in_a_full_plan_is_a_violation_of_time_01_and_never_raises(
    value: object,
) -> None:
    ready = prepared(None, priority_order())
    result = check_plan(ready, {**BASELINE, "t1": value})  # type: ignore[dict-item]
    assert result.violated == ("TIME-01",)
    assert result.timing is None


@pytest.mark.parametrize(
    "proposal",
    [None, 5, 5.5, "plan", b"plan", [], [1, 2, 3], (1, 2), {1, 2}, object()],
    ids=lambda value: type(value).__name__,
)
def test_a_proposal_that_is_not_an_object_is_invalid_input(proposal: object) -> None:
    result = run(proposal)
    assert result.status == "invalid_input"
    assert [i.field for i in result.issues] == ["durations"]


def test_a_proposal_with_a_million_unknown_keys_is_answered_in_linear_time_with_capped_issues() -> (
    None
):
    proposal: dict[object, object] = {f"x{index}": 1.0 for index in range(1_000_000)}
    started = time.perf_counter()
    result = run(proposal)
    assert time.perf_counter() - started < 10
    assert result.status == "invalid_input"
    assert len(result.issues) == MAX_ISSUES + 1
    # 1 000 000 claves de más y los 4 verdes que faltan: 1 000 004 problemas; se muestran 100.
    assert result.issues[-1].message == "y 999904 problemas más sin mostrar"


def test_unknown_keys_of_any_kind_are_reported_without_echoing_them_whole() -> None:
    proposal: dict[object, object] = {
        **BASELINE_VARIABLE,
        "k" * 1_000_000: 1.0,
        ("a",) * 100_000: 1.0,
        "\x00\x1b[31mrojo": 1.0,
        3.5: 1.0,
        None: 1.0,
    }
    result = run(proposal)
    assert result.status == "invalid_input"
    assert len(result.issues) == 5
    assert all(len(i.message) < MESSAGE_LIMIT for i in result.issues)
    assert all(len(i.field or "") < MAX_SHOWN_CHARS + 30 for i in result.issues)


def test_a_huge_claim_is_not_echoed_whole() -> None:
    big = "X" * 1_000_000
    result = run(BASELINE_VARIABLE, case_id=big, case_version=big)
    assert result.status == "invalid_input"
    assert [i.rule_id for i in result.issues] == ["TIME-02", "TIME-02"]
    assert all(len(i.message) < MESSAGE_LIMIT for i in result.issues)
    assert "…" in result.issues[0].message


def test_the_corrector_never_raises_with_random_garbage() -> None:
    rng = random.Random(13)  # noqa: S311 - entradas de prueba, no seguridad
    pool: list[object] = [
        float("nan"),
        float("inf"),
        -1e308,
        1e308,
        0,
        -0.0,
        5,
        82.5,
        True,
        None,
        "x",
        b"x",
        [],
        {},
        (1,),
        1j,
        10**400,
        sys.float_info.min / 4,
    ]
    for _ in range(2_000):
        shape = rng.randrange(3)
        if shape == 0:
            proposal: object = {slot_id: rng.choice(pool) for slot_id in VARIABLE_IDS}
        elif shape == 1:
            proposal = {
                rng.choice([*VARIABLE_IDS, "t2", "zz", 7, None]): rng.choice(pool)
                for _ in range(rng.randrange(8))
            }
        else:
            proposal = rng.choice(pool)
        result = run(proposal)
        assert result.status in ("accepted", "corrected", "rejected", "invalid_input")
        assert result.admissible == (result.status in ("accepted", "corrected"))
        if result.admissible:
            assert result.final_s is not None
            assert check_plan(prepared(None, priority_order()), result.final_s).feasible


def test_a_subnormal_or_extreme_but_finite_proposal_is_corrected_not_rejected_as_input() -> None:
    for value in (sys.float_info.min / 4, 5e-324, 1e-320, 1e308, -1e308, sys.float_info.max):
        result = run({**BASELINE_VARIABLE, "t1": value})
        assert result.status == "corrected"
        assert result.final_s is not None
        assert result.final_s["t1"] in (30.0, 110.0)


def test_the_corrector_does_not_modify_the_proposal_or_the_prepared_case() -> None:
    ready = prepared(None, priority_order())
    proposal = {**BASELINE_VARIABLE, "t1": 500.0}
    snapshot = copy.deepcopy(proposal)
    first = correct(ready, proposal, case_id=CASE_ID, case_version=CASE_VERSION)
    assert proposal == snapshot
    assert correct(ready, proposal, case_id=CASE_ID, case_version=CASE_VERSION) == first


# ---------------------------------------------------------------------------
# Caso grande: tiempo lineal
# ---------------------------------------------------------------------------


def large_case(count: int) -> dict[str, Any]:
    data = copy.deepcopy(DEMO_CASE)
    data["cycle_s"] = {"min": count, "max": 10 * count}
    data["slots"] = [
        {
            "id": f"s{index}",
            "kind": "variable",
            "min_s": 1,
            "max_s": 10,
            "states": [{"tls_id": "DEMO_TLS", "state": "Gr" if index % 2 else "rG"}],
        }
        for index in range(count)
    ]
    data["green_groups"] = [
        {
            "id": "todos",
            "slot_ids": [f"s{index}" for index in range(count)],
            "min_s": count,
            "max_s": 10 * count,
            "purpose": "vehicle",
        }
    ]
    return data


def test_a_case_with_five_thousand_slots_is_prepared_and_corrected_in_linear_time() -> None:
    count = 5_000
    case = parse_case(large_case(count))
    started = time.perf_counter()
    ready = prepare(case)
    rng = random.Random(5)  # noqa: S311 - entradas de prueba, no seguridad
    for _ in range(5):
        proposal = {f"s{index}": rng.uniform(-5, 20) for index in range(count)}
        result = correct(ready, proposal, case_id=case.case_id, case_version=case.case_version)
        assert result.status == "corrected"
        assert result.check is not None
        assert result.check.feasible
    assert time.perf_counter() - started < 15


def test_the_timing_of_a_huge_plan_is_computed_in_linear_time() -> None:
    count = 20_000
    case = parse_case(large_case(count))
    started = time.perf_counter()
    timing = reconstruct(case, {f"s{index}": 1.5 for index in range(count)})
    assert time.perf_counter() - started < 10
    assert timing.cycle_s == 30_000.0


# ---------------------------------------------------------------------------
# Archivo del orden de ajuste
# ---------------------------------------------------------------------------


def write(folder: Path, content: bytes) -> Path:
    path = folder / "orden_de_ajuste.json"
    path.write_bytes(content)
    return path


def test_an_order_file_that_is_a_symlink_or_a_folder_is_not_read(tmp_path: Path) -> None:
    real = write(tmp_path, json.dumps(order_data()).encode("utf-8"))
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(CasoError) as raised:
        read_adjust_order(link)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    with pytest.raises(CasoError):
        read_adjust_order(tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"   ",
        b"null",
        b"[]",
        b'"texto"',
        b"{}",
        b'{"cut_order": ["t1"]}',
        b'{"a": 1, "a": 2}',
        b'{"cut_order": NaN}',
        b"\xff\xfe\x00\x00",
        b"\x00" * 1000,
        b"[" * 20_000,
        b'{"x":' * 10_000,
    ],
    ids=lambda content: f"{len(content)}-bytes-{content[:8]!r}",
)
def test_a_hostile_order_file_is_rejected_with_a_domain_error(
    tmp_path: Path, content: bytes
) -> None:
    with pytest.raises((CasoError, AdjustOrderInvalidError)) as raised:
        read_adjust_order(write(tmp_path, content))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert len(str(raised.value)) < 2000


def test_an_order_file_over_the_limit_is_rejected_without_reading_it_all(tmp_path: Path) -> None:
    path = write(tmp_path, b"x" * (50 * 1024 * 1024))
    started = time.perf_counter()
    with pytest.raises(CasoError) as raised:
        read_adjust_order(path)
    assert time.perf_counter() - started < 5
    assert str(MAX_ORDER_BYTES) in raised.value.message


def test_an_order_with_thousands_of_hostile_slots_is_reported_capped_and_bounded() -> None:
    names = [f"{index}" + "z" * 60 for index in range(900)] + ["t2", "t2", "t7"]
    order = parse_adjust_order(order_data(names))
    started = time.perf_counter()
    issues = order_issues(prepared().case, order)
    assert time.perf_counter() - started < 5
    assert len(issues) == MAX_ISSUES + 1
    assert all(len(i.message) < MESSAGE_LIMIT for i in issues)


def test_an_order_with_a_huge_slot_name_is_reported_without_echoing_it_whole() -> None:
    order = parse_adjust_order(order_data(["y" * 60_000, "t7", "t5", "t3", "t1"]))
    issues = order_issues(prepared().case, order)
    assert len(issues) == 1
    assert len(issues[0].message) < MESSAGE_LIMIT
    assert "…" in issues[0].message


def test_an_order_for_another_case_with_a_huge_name_is_not_echoed_whole() -> None:
    order = parse_adjust_order(order_data(case_id="Q" * 60_000, case_version="1.0.0"))
    issues = order_issues(prepared().case, order)
    assert [i.field for i in issues] == ["case_id"]
    assert len(issues[0].message) < MESSAGE_LIMIT


def test_preparing_with_a_hostile_order_fails_before_any_correction() -> None:
    order = parse_adjust_order(order_data(["t1", "t1", "t1", "t1"]))
    with pytest.raises(AdjustOrderInvalidError) as raised:
        prepare(prepared().case, order)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA


def test_a_summary_of_many_corrections_keeps_a_constant_amount_of_data() -> None:
    ready = prepared(None, priority_order())

    def stream() -> Iterator[Correction]:
        rng = random.Random(8)  # noqa: S311 - entradas de prueba, no seguridad
        for _ in range(20_000):
            yield correct(
                ready,
                {slot_id: rng.uniform(-50, 300) for slot_id in VARIABLE_IDS},
                case_id=CASE_ID,
                case_version=CASE_VERSION,
            )

    started = time.perf_counter()
    summary = summarize(stream())
    assert time.perf_counter() - started < 60
    assert summary.total == 20_000
    assert summary.rejected == 0
    assert len(summary.corrected_by_slot) <= len(VARIABLE_IDS)


@pytest.mark.parametrize(
    "name",
    ["t7" + chr(10), "t7 ", " t7", "t7" + chr(0), "t" + chr(0x200B) + "7", ""],
    ids=["salto", "espacio-final", "espacio-inicial", "nulo", "ancho-cero", "vacio"],
)
def test_slot_names_with_control_or_invisible_characters_are_rejected_by_the_structure(
    name: str,
) -> None:
    with pytest.raises(AdjustOrderInvalidError) as raised:
        parse_adjust_order(order_data(["t5", name]))
    assert raised.value.issues[0].rule_id == "ORDER-S02"


def test_a_deeply_nested_proposal_value_does_not_break_the_corrector() -> None:
    result = run({**BASELINE_VARIABLE, "t1": nested_dict(10_000)})
    assert result.status == "invalid_input"
    assert [i.field for i in result.issues] == ["durations[t1]"]


def test_an_order_for_another_version_with_huge_digits_is_not_echoed_whole() -> None:
    order = parse_adjust_order(order_data(case_version="1.0." + "9" * 60_000))
    issues = order_issues(prepared().case, order)
    assert [i.field for i in issues] == ["case_version"]
    assert len(issues[0].message) < MESSAGE_LIMIT


def test_a_case_with_a_huge_identifier_is_not_echoed_whole_by_the_claim_or_the_order() -> None:
    data = copy.deepcopy(DEMO_CASE)
    data["case_id"] = "C" * 60_000
    data["case_version"] = "1.0." + "7" * 60_000
    case = parse_case(data)
    ready = prepare(case)
    claim = correct(ready, {"s1": 30.0, "s4": 22.0}, case_id="otro", case_version="9.9.9")
    assert [i.rule_id for i in claim.issues] == ["TIME-02", "TIME-02"]
    assert all(len(i.message) < MESSAGE_LIMIT for i in claim.issues)
    order = parse_adjust_order(
        order_data(["s1", "s4"], case_id="otro", case_version="9.9.9"),
    )
    issues = order_issues(case, order)
    assert [i.field for i in issues] == ["case_id", "case_version"]
    assert all(len(i.message) < MESSAGE_LIMIT for i in issues)


def test_a_repeated_huge_slot_name_in_the_order_is_not_echoed_whole() -> None:
    huge = "r" * 60_000
    order = parse_adjust_order(order_data([huge, huge, "t7", "t5", "t3", "t1"]))
    issues = order_issues(prepared().case, order)
    assert [i.field for i in issues] == ["cut_order[0]", "cut_order[1]"]
    assert "repetido" in issues[1].message
    assert all(len(i.message) < MESSAGE_LIMIT for i in issues)


def test_a_fixed_slot_with_a_huge_name_in_the_order_is_not_echoed_whole() -> None:
    huge = "f" * 60_000

    def rename_fixed_slot(data: dict[str, Any]) -> None:
        data["slots"][1]["id"] = huge
        data["green_groups"][1]["slot_ids"] = ["t1", huge, "t3"]

    case = prepared(rename_fixed_slot).case
    order = parse_adjust_order(order_data([huge, "t7", "t5", "t3", "t1"]))
    issues = order_issues(case, order)
    assert [(i.rule_id, i.field) for i in issues] == [("ORDER-C03", "cut_order[0]")]
    assert "fijo" in issues[0].message
    assert len(issues[0].message) < MESSAGE_LIMIT
