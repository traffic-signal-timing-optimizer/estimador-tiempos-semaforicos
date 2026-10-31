"""Pruebas del compilador del programa derivado (DEV03, F2)."""

import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from defusedxml.ElementTree import fromstring

from semaforo.caso.inventory import read_network_inventory
from semaforo.caso.network_map import NetworkMap, build_network_map
from semaforo.dominio.case import Case, canonical_sha256, parse_case
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.compiler import (
    DERIVED_PROGRAM_ID,
    CompilationError,
    compile_program,
    publish_program,
)
from semaforo.trazabilidad.hashing import sha256_file

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DEMO_NET = FIXTURES / "sumo" / "demo" / "demo.net.xml"
DEMO_CASE = json.loads((FIXTURES / "case.json").read_text(encoding="utf-8"))
# Plan de ejemplo de response.json: es el programa que ya trae la red de demostración.
DURATIONS = {"s1": 30.0, "s2": 3.0, "s3": 1.0, "s4": 22.0, "s5": 3.0, "s6": 1.0}
NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)


def make_case(change: Callable[[dict[str, Any]], None] | None = None) -> Case:
    data = copy.deepcopy(DEMO_CASE)
    if change is not None:
        change(data)
    return parse_case(data)


def complete_map(case: Case) -> NetworkMap:
    network_map = build_network_map(DEMO_NET, case)
    assert network_map.is_complete
    return network_map


def test_the_compiled_program_equals_the_one_in_the_demo_network() -> None:
    case = make_case()
    program = compile_program(case, complete_map(case), DURATIONS)
    original = read_network_inventory(DEMO_NET).traffic_lights[0].programs[0]
    assert [(p.duration_s, p.state) for p in original.phases] == [
        (phase.duration_s, phase.state) for phase in program.phases
    ]
    assert program.cycle_s == 60.0
    assert program.tls_id == "DEMO_TLS"


def test_the_file_is_an_additional_with_its_own_program_id() -> None:
    case = make_case()
    program = compile_program(case, complete_map(case), DURATIONS)
    text = program.xml.decode("utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n')
    assert text.endswith("</additional>\n")
    assert "\r" not in text
    logic = fromstring(text).find("tlLogic")
    assert logic is not None
    assert logic.attrib == {
        "id": "DEMO_TLS",
        "type": "static",
        "programID": DERIVED_PROGRAM_ID,
        "offset": "0",
    }
    assert [(p.get("duration"), p.get("state")) for p in logic.findall("phase")] == [
        ("30", "Gr"),
        ("3", "yr"),
        ("1", "rr"),
        ("22", "rG"),
        ("3", "ry"),
        ("1", "rr"),
    ]


def test_the_same_input_gives_the_same_file() -> None:
    case = make_case()
    network_map = complete_map(case)
    first = compile_program(case, network_map, DURATIONS)
    second = compile_program(case, network_map, dict(reversed(DURATIONS.items())))
    assert first.xml == second.xml
    assert first.sha256 == second.sha256


def test_a_half_second_duration_is_written_with_its_decimal() -> None:
    def half_tick(data: dict[str, Any]) -> None:
        data["tick_s"] = 0.5

    case = make_case(half_tick)
    program = compile_program(case, complete_map(case), {**DURATIONS, "s1": 30.5})
    assert b'duration="30.5"' in program.xml


def test_an_id_with_special_characters_is_escaped() -> None:
    tls_id = 'A&B<"C>'

    def rename(data: dict[str, Any]) -> None:
        for slot in data["slots"]:
            slot["states"][0]["tls_id"] = tls_id

    case = make_case(rename)
    network_map = NetworkMap(tls_id=tls_id, link_count=2, movements=(), issues=())
    program = compile_program(case, network_map, DURATIONS)
    logic = fromstring(program.xml).find("tlLogic")
    assert logic is not None
    assert logic.get("id") == tls_id


def test_an_incomplete_network_map_is_not_compiled() -> None:
    case = make_case()
    incomplete = build_network_map(DEMO_NET, make_case(lambda d: d["movements"].pop()))
    with pytest.raises(CompilationError) as raised:
        compile_program(case, incomplete, DURATIONS)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.issues == incomplete.issues


def test_a_slot_state_of_the_wrong_length_is_rejected() -> None:
    def shorten(data: dict[str, Any]) -> None:
        data["slots"][0]["states"][0]["state"] = "G"

    case = make_case(shorten)
    with pytest.raises(CompilationError) as raised:
        compile_program(case, complete_map(make_case()), DURATIONS)
    [issue] = raised.value.issues
    assert (issue.rule_id, issue.field) == ("COMPILE-01", "slots[0].states[0].state")


def test_a_slot_with_two_states_is_rejected() -> None:
    def duplicate(data: dict[str, Any]) -> None:
        data["slots"][0]["states"].append({"tls_id": "OTRO", "state": "Gr"})

    case = make_case(duplicate)
    with pytest.raises(CompilationError) as raised:
        compile_program(case, complete_map(make_case()), DURATIONS)
    assert [issue.field for issue in raised.value.issues] == ["slots[0].states"]


def test_durations_outside_the_limits_are_rejected_with_their_issues() -> None:
    case = make_case()
    with pytest.raises(CompilationError) as raised:
        compile_program(case, complete_map(case), {**DURATIONS, "s1": 99.0})
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.issues[0].rule_id == "PLAN-02"
    assert "durations[s1]" in str(raised.value)


def test_a_published_program_has_its_three_files_and_matching_hashes(tmp_path: Path) -> None:
    case = make_case()
    program = compile_program(case, complete_map(case), DURATIONS)
    folder = publish_program(tmp_path, case, program, NOW)
    assert folder == tmp_path / "SYNTHETIC_DEMO" / f"20261030T120000Z_{program.sha256[:8]}"
    assert sorted(path.name for path in folder.iterdir()) == [
        "manifiesto.json",
        "programa.tll.xml",
        "tramos.json",
    ]
    assert (folder / "programa.tll.xml").read_bytes() == program.xml
    manifest = json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
    assert manifest["case_sha256"] == canonical_sha256(case)
    assert manifest["network_sha256"] is None
    assert manifest["created_at"] == "2026-10-30T12:00:00+00:00"
    assert manifest["files"] == {
        "programa.tll.xml": sha256_file(folder / "programa.tll.xml"),
        "tramos.json": sha256_file(folder / "tramos.json"),
    }


def test_the_slots_file_lists_durations_limits_and_green_totals(tmp_path: Path) -> None:
    case = make_case()
    folder = publish_program(
        tmp_path, case, compile_program(case, complete_map(case), DURATIONS), NOW
    )
    data = json.loads((folder / "tramos.json").read_text(encoding="utf-8"))
    assert data["cycle_s"] == 60
    assert data["slots"][0] == {
        "id": "s1",
        "kind": "variable",
        "min_s": 10,
        "max_s": 50,
        "duration_s": 30,
    }
    assert [(g["id"], g["total_s"]) for g in data["green_groups"]] == [("NS", 30), ("EW", 22)]


def test_the_declared_network_fingerprint_goes_into_the_manifest(tmp_path: Path) -> None:
    fingerprint = "a" * 64

    def declare(data: dict[str, Any]) -> None:
        data["network"] = {"artifact_id": "net", "path": "demo.net.xml", "sha256": fingerprint}

    case = make_case(declare)
    program = compile_program(case, complete_map(case), DURATIONS)
    folder = publish_program(tmp_path, case, program, NOW)
    manifest = json.loads((folder / "manifiesto.json").read_text(encoding="utf-8"))
    assert manifest["network_sha256"] == fingerprint


def test_a_published_folder_is_never_overwritten(tmp_path: Path) -> None:
    case = make_case()
    program = compile_program(case, complete_map(case), DURATIONS)
    folder = publish_program(tmp_path, case, program, NOW)
    before = (folder / "programa.tll.xml").read_bytes()
    with pytest.raises(CompilationError) as raised:
        publish_program(tmp_path, case, program, NOW)
    assert raised.value.code is ErrorCode.RUN_EXISTS
    assert (folder / "programa.tll.xml").read_bytes() == before


def test_a_new_publication_with_other_durations_goes_to_another_folder(tmp_path: Path) -> None:
    case = make_case()
    network_map = complete_map(case)
    first = publish_program(tmp_path, case, compile_program(case, network_map, DURATIONS), NOW)
    other = compile_program(case, network_map, {**DURATIONS, "s1": 31.0})
    second = publish_program(tmp_path, case, other, NOW)
    assert first != second
    assert first.parent == second.parent


@pytest.mark.parametrize("case_id", ["../fuera", "a/b", "a\\b", ".oculto", "C:x", "con espacio"])
def test_a_case_id_that_is_not_a_safe_folder_name_is_rejected(tmp_path: Path, case_id: str) -> None:
    case = make_case(lambda data: data.update(case_id=case_id))
    program = compile_program(case, complete_map(case), DURATIONS)
    with pytest.raises(CompilationError) as raised:
        publish_program(tmp_path / "raiz", case, program, NOW)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert not (tmp_path / "raiz").exists()
