"""Comparadores publicados y verificables (DEV15 F4, HU08 y HU12; sin SUMO).

Datos sintéticos: el caso de demostración de dos movimientos, con los flujos de cada prueba. Las
cifras de Webster están calculadas a mano en ``test_baselines.py``: con N 720 y E 540 veh/h, el
ciclo de Webster es 56,667 s y el plan, 28 / 3 / 1 / 21 / 3 / 1 (ciclo 57 s).
"""

import json
import os
import stat
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from baselines_tools import parameters
from prepared_inputs import DURATIONS, request_for
from semaforo.app.integrity import verify_workspace
from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.feasibility import prepare
from semaforo.referencias.baselines import ADAPTATION
from semaforo.referencias.comparators import (
    COMPARATORS,
    COMPARATORS_FILE,
    MANIFEST_FILE,
    MAX_FILE_BYTES,
    PARAMETERS_FILE,
    ComparatorsResult,
    ProblemRow,
    WebsterSection,
    compute_comparators,
    publish_comparators,
    read_comparators,
)
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.search import generate_candidates
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import TrazabilidadError

MOMENT = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC)
WEBSTER_PLAN = {"s1": 28.0, "s2": 3.0, "s3": 1.0, "s4": 21.0, "s5": 3.0, "s6": 1.0}


def demand(north: float, east: float) -> list[dict[str, Any]]:
    mix = {"car": 1.0, "bus": 0.0}
    return [
        {"movement_id": "N_S", "flow_vph": north, "composition": mix if north else None},
        {"movement_id": "E_W", "flow_vph": east, "composition": mix if east else None},
    ]


def comparators_in(
    tmp_path: Path,
    north: float = 720,
    east: float = 540,
    **case_rules: Any,  # noqa: ANN401
) -> ComparatorsResult:
    """Los comparadores con esos flujos; ``ns_max`` cambia el máximo del grupo NS."""

    def change_case(data: dict[str, Any]) -> None:
        if "ns_max" in case_rules:
            data["green_groups"][0]["max_s"] = case_rules["ns_max"]

    def change_scenario(data: dict[str, Any]) -> None:
        data["request"]["demand"] = demand(north, east)

    request = request_for(tmp_path, case_change=change_case, scenario_change=change_scenario)
    return compute_comparators(
        prepare(request.case), request.scenario, parameters(), request.program_dir
    )


def new_dir(tmp_path: Path, name: str = "caso") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


def published(tmp_path: Path, **flows: float) -> Path:
    result = comparators_in(new_dir(tmp_path), **flows)
    return publish_comparators(tmp_path / "datos", result, MOMENT)


def rewrite(path: Path, data: dict[str, Any]) -> None:
    path.chmod(stat.S_IWRITE)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --- cálculo ------------------------------------------------------------------------------------


def test_the_comparators_hold_the_current_plan_and_webster(tmp_path: Path) -> None:
    result = comparators_in(new_dir(tmp_path))
    assert dict(result.current.durations_s) == DURATIONS
    assert result.current.feasible
    assert result.webster.status == "applicable"
    assert dict(result.webster.durations_s or {}) == WEBSTER_PLAN
    assert result.webster.webster_cycle_s == pytest.approx(17 / 0.3)
    assert result.search_current_plan == DURATIONS
    assert result.search_webster_plan == WEBSTER_PLAN
    assert result.scenario_id == "SCENARIO_DEMO_001"


def test_a_webster_that_does_not_apply_gives_the_search_nothing(tmp_path: Path) -> None:
    result = comparators_in(new_dir(tmp_path), north=900, east=900)
    assert result.webster.status == "not_applicable"
    assert [p.code for p in result.webster.problems] == ["oversaturated"]
    assert result.search_webster_plan is None
    assert result.search_current_plan == DURATIONS


def test_a_webster_that_breaks_a_case_rule_is_kept_as_a_proposal_and_not_given_to_the_search(
    tmp_path: Path,
) -> None:
    result = comparators_in(new_dir(tmp_path), ns_max=25)
    assert result.webster.status == "not_applicable"
    assert [p.code for p in result.webster.problems] == ["plan_infeasible"]
    assert result.webster.durations_s is not None
    assert result.webster.violated
    assert result.search_webster_plan is None


def test_a_scenario_of_another_case_is_refused(tmp_path: Path) -> None:
    request = request_for(new_dir(tmp_path))
    scenario = request.scenario.model_copy(update={"case_id": "OTRO"})
    with pytest.raises(ReferenciasError) as error:
        compute_comparators(prepare(request.case), scenario, parameters(), request.program_dir)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


# --- publicar y leer ----------------------------------------------------------------------------


def test_the_comparators_are_published_and_read_back(tmp_path: Path) -> None:
    folder = published(tmp_path)
    assert folder.parent == tmp_path / "datos" / COMPARATORS / "SYNTHETIC_DEMO"
    assert folder.name.startswith("20261104T120000Z_")
    stored = read_comparators(folder)
    content = stored.comparators
    assert content.scenario_id == "SCENARIO_DEMO_001"
    assert content.current_plan.plan.durations_s == DURATIONS
    assert content.current_plan.violated == []
    assert content.current_plan.program_folder
    assert content.webster.status == "applicable"
    assert content.webster.plan is not None
    assert content.webster.plan.durations_s == WEBSTER_PLAN
    assert content.webster.plan.cycle_s == 57
    assert content.webster.webster_cycle_s == pytest.approx(17 / 0.3)
    assert content.webster.critical_path is not None
    assert content.webster.adaptation == ADAPTATION
    assert content.webster.provisional
    assert stored.manifest.webster_status == "applicable"
    assert stored.manifest.current_plan_feasible
    assert stored.manifest.provisional
    assert stored.parameters == parameters()


def test_the_folder_holds_the_comparators_the_parameters_and_the_manifest(tmp_path: Path) -> None:
    folder = published(tmp_path)
    files = {path.name: path for path in folder.iterdir()}
    assert set(files) == {COMPARATORS_FILE, PARAMETERS_FILE, MANIFEST_FILE}
    assert not any(os.access(path, os.W_OK) for path in files.values())
    manifest = read_comparators(folder).manifest
    assert set(manifest.files) == {COMPARATORS_FILE, PARAMETERS_FILE}
    assert manifest.files[COMPARATORS_FILE] == sha256_bytes(files[COMPARATORS_FILE].read_bytes())


def test_a_webster_that_does_not_apply_is_published_with_its_reason(tmp_path: Path) -> None:
    folder = published(tmp_path, north=900, east=900)
    stored = read_comparators(folder)
    assert stored.comparators.webster.status == "not_applicable"
    assert stored.comparators.webster.plan is None
    assert [p.code for p in stored.comparators.webster.problems] == ["oversaturated"]
    assert stored.manifest.webster_status == "not_applicable"


def test_an_observed_plan_that_breaks_a_rule_is_published_with_it(tmp_path: Path) -> None:
    def narrow(data: dict[str, Any]) -> None:
        data["slots"][0]["max_s"] = 25

    request = request_for(new_dir(tmp_path), case_change=narrow)
    result = compute_comparators(
        prepare(request.case), request.scenario, parameters(), request.program_dir
    )
    folder = publish_comparators(tmp_path / "datos", result, MOMENT)
    stored = read_comparators(folder)
    assert stored.comparators.current_plan.violated
    assert not stored.manifest.current_plan_feasible
    assert stored.comparators.current_plan.plan.durations_s == DURATIONS


def test_the_folder_is_named_in_utc_even_from_lima_time(tmp_path: Path) -> None:
    result = comparators_in(new_dir(tmp_path))
    lima = datetime(2026, 11, 4, 7, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    folder = publish_comparators(tmp_path / "datos", result, lima)
    assert folder.name.startswith("20261104T120000Z_")
    assert read_comparators(folder).manifest.created_at == MOMENT


def test_the_same_comparators_cannot_be_published_twice_in_the_same_instant(tmp_path: Path) -> None:
    result = comparators_in(new_dir(tmp_path))
    publish_comparators(tmp_path / "datos", result, MOMENT)
    with pytest.raises(ReferenciasError) as error:
        publish_comparators(tmp_path / "datos", result, MOMENT)
    assert error.value.code == ErrorCode.RUN_EXISTS


@pytest.mark.parametrize("case_id", ["../fuera", "a/b", "a\\b", "C:x", ".oculto", ""])
def test_a_case_name_with_a_path_cannot_become_a_folder(tmp_path: Path, case_id: str) -> None:
    result = comparators_in(new_dir(tmp_path))
    hostile = replace(result, case=result.case.model_copy(update={"case_id": case_id}))
    with pytest.raises(ReferenciasError) as error:
        publish_comparators(tmp_path / "datos", hostile, MOMENT)
    assert error.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert not (tmp_path / "datos").exists()
    assert not (tmp_path / "fuera").exists()


# --- verificar ----------------------------------------------------------------------------------


def test_a_changed_file_is_detected(tmp_path: Path) -> None:
    folder = published(tmp_path)
    path = folder / COMPARATORS_FILE
    path.chmod(stat.S_IWRITE)
    path.write_text(path.read_text(encoding="utf-8").replace("applicable", "x", 1))
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.HASH_MISMATCH


def test_an_extra_file_is_detected(tmp_path: Path) -> None:
    folder = published(tmp_path)
    (folder / "NOTAS.txt").write_text("x", encoding="utf-8")
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.HASH_MISMATCH


def test_a_manifest_that_lists_only_the_comparators_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    (folder / PARAMETERS_FILE).chmod(stat.S_IWRITE)
    (folder / PARAMETERS_FILE).unlink()
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {COMPARATORS_FILE: manifest["files"][COMPARATORS_FILE]}
    rewrite(manifest_path, manifest)
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA
    assert error.value.field == MANIFEST_FILE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scenario_id", "OTRO"),
        ("case_id", "OTRO"),
        ("case_version", "9.9.9"),
        ("webster_status", "not_applicable"),
        ("parameter_set", "otro"),
        ("provisional", False),
        ("adaptation", "otra"),
        ("current_plan_feasible", False),
    ],
)
def test_a_manifest_that_contradicts_the_files_is_refused(
    tmp_path: Path, field: str, value: object
) -> None:
    folder = published(tmp_path)
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    rewrite(manifest_path, manifest)
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def forge_content(folder: Path, change: dict[str, Any]) -> None:
    """Cambia ``comparadores.json`` y pone su huella nueva en el manifiesto (lo sabe todo)."""
    content = json.loads((folder / COMPARATORS_FILE).read_text(encoding="utf-8"))
    content.update(change)
    forged = json.dumps(content, indent=2).encode("utf-8")
    (folder / COMPARATORS_FILE).chmod(stat.S_IWRITE)
    (folder / COMPARATORS_FILE).write_bytes(forged)
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][COMPARATORS_FILE] = sha256_bytes(forged)
    rewrite(manifest_path, manifest)


@pytest.mark.parametrize(
    "change",
    [
        {"case_id": "OTRO"},
        {"case_version": "9.9.9"},
        {"scenario_id": "OTRO"},
    ],
    ids=["caso", "version", "escenario"],
)
def test_a_forged_content_with_its_new_hash_is_still_refused_when_it_contradicts(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    folder = published(tmp_path)
    forge_content(folder, change)
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA
    assert error.value.field == COMPARATORS_FILE


def test_a_webster_forged_into_not_applicable_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    content = json.loads((folder / COMPARATORS_FILE).read_text(encoding="utf-8"))
    forge_content(folder, {"webster": {**content["webster"], "status": "not_applicable"}})
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_a_file_over_the_size_limit_is_rejected_before_parsing(tmp_path: Path) -> None:
    folder = published(tmp_path)
    valid = (folder / COMPARATORS_FILE).read_bytes()
    big = valid + b" " * MAX_FILE_BYTES
    (folder / COMPARATORS_FILE).chmod(stat.S_IWRITE)
    (folder / COMPARATORS_FILE).write_bytes(big)
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][COMPARATORS_FILE] = sha256_bytes(big)
    rewrite(manifest_path, manifest)
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA
    assert error.value.field == COMPARATORS_FILE


def test_an_applicable_webster_needs_its_plan_and_no_problems() -> None:
    base: dict[str, Any] = {
        "adaptation": ADAPTATION,
        "parameter_set": "p",
        "provisional": True,
        "violated": [],
        "critical_path": None,
    }
    problem = ProblemRow(code="oversaturated", subject="ciclo", message="x")
    with pytest.raises(ValidationError):
        WebsterSection(status="applicable", webster_cycle_s=None, plan=None, problems=[], **base)
    with pytest.raises(ValidationError):
        WebsterSection(
            status="applicable", webster_cycle_s=50.0, plan=None, problems=[problem], **base
        )


def test_a_webster_that_does_not_apply_must_say_why() -> None:
    with pytest.raises(ValidationError):
        WebsterSection(
            status="not_applicable",
            adaptation=ADAPTATION,
            parameter_set="p",
            provisional=True,
            webster_cycle_s=None,
            plan=None,
            violated=[],
            problems=[],
            critical_path=None,
        )


def label_statuses(workspace: Path) -> list[str]:
    report = verify_workspace(workspace)
    return [item.status for item in report.items if item.family == "comparators"]


def test_the_workspace_check_reports_the_comparators(tmp_path: Path) -> None:
    folder = published(tmp_path)
    workspace = tmp_path / "datos"
    assert label_statuses(workspace) == ["intact"]
    (folder / COMPARATORS_FILE).chmod(stat.S_IWRITE)
    (folder / COMPARATORS_FILE).write_text("{}", encoding="utf-8")
    assert label_statuses(workspace) == ["altered"]


# --- entrada a la búsqueda ----------------------------------------------------------------------


def test_the_comparators_feed_the_search_as_auxiliary_candidates(tmp_path: Path) -> None:
    result = comparators_in(new_dir(tmp_path))
    found = generate_candidates(
        prepare(result.case),
        scenario_id=result.scenario_id,
        budget=3,
        attempt_limit=100,
        seed=1,
        current_plan=result.search_current_plan,
        webster_plan=result.search_webster_plan,
    )
    assert [c.origin for c in found.candidates[:2]] == ["current_plan", "webster"]
    assert found.current_plan == "included"
    assert found.webster == "included"
    assert found.budget_used == 3
    assert dict(found.candidates[1].durations_s) == WEBSTER_PLAN


def test_a_webster_that_does_not_apply_does_not_enter_the_search(tmp_path: Path) -> None:
    result = comparators_in(new_dir(tmp_path), north=900, east=900)
    found = generate_candidates(
        prepare(result.case),
        scenario_id=result.scenario_id,
        budget=3,
        attempt_limit=100,
        seed=1,
        current_plan=result.search_current_plan,
        webster_plan=result.search_webster_plan,
    )
    assert found.webster == "absent"
    assert "webster" not in [c.origin for c in found.candidates]
