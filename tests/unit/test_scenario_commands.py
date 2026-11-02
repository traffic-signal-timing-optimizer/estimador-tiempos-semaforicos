"""Caso de uso de ``scenarios generate`` y las líneas de problemas (DEV11 F4, decisión D12)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scenario_tools import SEED, spec_data, write_inputs
from semaforo.app import scenario_commands as module
from semaforo.app.issue_lines import issue_lines
from semaforo.app.scenario_commands import MAX_SEED, ScenarioSetResult, generate_scenario_set
from semaforo.caso.errors import CasoError
from semaforo.datos.importer import CountImportError, CountIssue
from semaforo.datos.scenario_set import read_scenario_set
from semaforo.dominio.case import CaseInvalidError, CaseIssue
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.scenario import ScenarioInvalidError
from semaforo.dominio.scenario_spec import SpecInvalidError

NOW = datetime(2026, 11, 2, 14, 0, 7, tzinfo=UTC)


def generate(
    tmp_path: Path, spec: dict[str, Any] | None = None, seed: int = SEED
) -> ScenarioSetResult:
    case, spec_path = write_inputs(tmp_path / "entradas", spec)
    return generate_scenario_set(tmp_path / "datos", case, spec_path, seed, NOW)


def nothing_published(tmp_path: Path) -> bool:
    return not (tmp_path / "datos").exists()


# --- el resultado -----------------------------------------------------------------------------


def test_the_summary_describes_the_published_set(tmp_path: Path) -> None:
    result = generate(tmp_path)
    assert result.status == "published"
    assert (result.case_id, result.spec_id, result.seed) == ("SYNTHETIC_DEMO", "SPEC_DEMO", SEED)
    assert (result.families, result.scenarios) == (2, 10)
    assert (
        result.folder
        == f"derivados/escenarios/SYNTHETIC_DEMO/20261102T140007Z_{result.content_id[:8]}"
    )
    assert result.manifest == f"{result.folder}/manifiesto.json"
    assert (tmp_path / "datos" / result.manifest).is_file()


def test_the_summary_has_exactly_the_documented_fields(tmp_path: Path) -> None:
    data = generate(tmp_path).model_dump(mode="json")
    assert set(data) == {
        "schema_version",
        "status",
        "case_id",
        "spec_id",
        "seed",
        "content_id",
        "families",
        "scenarios",
        "vehicles",
        "folder",
        "manifest",
    }
    assert data["schema_version"] == "1.0.0"
    assert json.dumps(data)


def test_the_vehicle_count_is_the_sum_over_the_scenarios(tmp_path: Path) -> None:
    result = generate(tmp_path)
    loaded = read_scenario_set(tmp_path / "datos" / result.folder)
    assert result.vehicles == sum(entry.vehicles for entry in loaded.manifest.scenarios)
    assert result.vehicles > 0
    assert result.content_id == loaded.manifest.content_id


def test_the_published_set_reads_back_verified(tmp_path: Path) -> None:
    result = generate(tmp_path)
    loaded = read_scenario_set(tmp_path / "datos" / result.folder)
    assert len(loaded.scenarios) == result.scenarios


def test_the_clock_of_the_machine_is_used_when_no_date_is_given(tmp_path: Path) -> None:
    case, spec_path = write_inputs(tmp_path / "entradas")
    before = datetime.now(UTC).replace(microsecond=0)
    result = generate_scenario_set(tmp_path / "datos", case, spec_path, SEED)
    after = datetime.now(UTC)
    loaded = read_scenario_set(tmp_path / "datos" / result.folder)
    assert before <= loaded.manifest.created_at <= after


def test_the_same_inputs_give_the_same_content_hash_on_different_dates(tmp_path: Path) -> None:
    case, spec_path = write_inputs(tmp_path / "entradas")
    first = generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW)
    second = generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW.replace(hour=15))
    assert first.content_id == second.content_id
    assert first.folder != second.folder


def test_the_whitespace_of_the_spec_file_does_not_change_the_content(tmp_path: Path) -> None:
    case, spec_path = write_inputs(tmp_path / "entradas")
    first = generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW)
    spec_path.write_text(json.dumps(spec_data(), indent=4, sort_keys=True), encoding="utf-8")
    second = generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW.replace(hour=15))
    assert first.content_id == second.content_id


# --- lo que se rechaza ------------------------------------------------------------------------


def test_an_invalid_range_publishes_nothing_and_says_why(tmp_path: Path) -> None:
    data = spec_data()
    data["families"][0]["demand"][0]["flow_vph"] = {"min": 600, "max": 400}
    with pytest.raises(SpecInvalidError) as raised:
        generate(tmp_path, data)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert "SPEC-C03" in raised.value.message
    assert nothing_published(tmp_path)


def test_an_invalid_case_publishes_nothing(tmp_path: Path) -> None:
    case, spec_path = write_inputs(tmp_path / "entradas")
    data = json.loads(case.read_text(encoding="utf-8"))
    data["green_groups"][0]["slot_ids"] = ["NO_EXISTE"]
    case.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CaseInvalidError):
        generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW)
    assert nothing_published(tmp_path)


@pytest.mark.parametrize("which", ["case", "spec"])
def test_a_missing_input_file_is_reported(tmp_path: Path, which: str) -> None:
    case, spec_path = write_inputs(tmp_path / "entradas")
    (case if which == "case" else spec_path).unlink()
    with pytest.raises(CasoError) as raised:
        generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert nothing_published(tmp_path)


def test_a_spec_that_is_not_json_is_reported(tmp_path: Path) -> None:
    case, spec_path = write_inputs(tmp_path / "entradas")
    spec_path.write_text("{no es json", encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW)
    assert "especificación" in raised.value.message
    assert nothing_published(tmp_path)


def test_a_spec_with_a_repeated_key_is_reported(tmp_path: Path) -> None:
    case, spec_path = write_inputs(tmp_path / "entradas")
    spec_path.write_text('{"schema_version": "1.0.0", "schema_version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(CasoError) as raised:
        generate_scenario_set(tmp_path / "datos", case, spec_path, SEED, NOW)
    assert "más de una vez" in raised.value.message


def test_a_spec_that_is_a_link_is_not_followed(tmp_path: Path) -> None:
    case, real = write_inputs(tmp_path / "entradas")
    link = tmp_path / "entradas" / "enlace.json"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(CasoError) as raised:
        generate_scenario_set(tmp_path / "datos", case, link, SEED, NOW)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert nothing_published(tmp_path)


@pytest.mark.parametrize("seed", [-1, MAX_SEED + 1])
def test_a_bad_seed_is_reported_and_publishes_nothing(tmp_path: Path, seed: int) -> None:
    with pytest.raises(DomainError) as raised:
        generate(tmp_path, seed=seed)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.field == "seed"
    assert nothing_published(tmp_path)


def test_the_same_set_on_the_same_second_is_not_overwritten(tmp_path: Path) -> None:
    generate(tmp_path)
    with pytest.raises(DomainError) as raised:
        generate(tmp_path)
    assert raised.value.code is ErrorCode.RUN_EXISTS


def test_the_seed_limit_is_the_documented_one() -> None:
    assert MAX_SEED == 9223372036854775807
    assert module.MAX_SEED == MAX_SEED


# --- líneas de problemas ----------------------------------------------------------------------


def test_each_problem_has_its_own_line_with_rule_field_and_reason() -> None:
    error = SpecInvalidError(
        [
            CaseIssue("SPEC-C01", "case_id", "el caso es «A»"),
            CaseIssue("SPEC-C02", None, "falta una fila"),
        ]
    )
    assert issue_lines(error) == [
        "- SPEC-C01 case_id: el caso es «A»",
        "- SPEC-C02: falta una fila",
    ]


def test_the_case_and_scenario_errors_also_list_their_problems() -> None:
    issues = [CaseIssue("CASE-S01", "a", "x"), CaseIssue("CASE-S02", "b", "y")]
    assert issue_lines(CaseInvalidError(issues)) == ["- CASE-S01 a: x", "- CASE-S02 b: y"]
    assert issue_lines(ScenarioInvalidError(issues)) == ["- CASE-S01 a: x", "- CASE-S02 b: y"]


def test_an_error_without_problems_gives_no_lines() -> None:
    assert issue_lines(DomainError(ErrorCode.RUN_EXISTS, "ya existe")) == []


def test_problems_of_another_shape_are_left_alone() -> None:
    error = CountImportError([CountIssue(line=3, field="x", message="mal")])
    assert issue_lines(error) == []


def test_the_vehicle_total_counts_the_warmup_vehicles_too(tmp_path: Path) -> None:
    data = spec_data()
    data["warmup_s"] = 60
    result = generate(tmp_path, data)
    loaded = read_scenario_set(tmp_path / "datos" / result.folder)
    assert result.vehicles == sum(entry.vehicles for entry in loaded.manifest.scenarios)
    assert result.vehicles > sum(entry.measured for entry in loaded.manifest.scenarios)
