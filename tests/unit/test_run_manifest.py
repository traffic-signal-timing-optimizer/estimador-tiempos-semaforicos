"""Pruebas del DTO del contrato run_manifest (ADR09, F5)."""

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from semaforo.trazabilidad.manifest import RunManifest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "run_manifest.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "run_manifest.json"
REFERENCE = ROOT / "tools" / "contracts" / "modelos_contrato.py"
HASH = "a" * 64
RUN_ID = "20261020T150000Z_simulation_1a2b3c4d"


def reference_module() -> ModuleType:
    """Modelos de referencia que entregó la documentación (tools/contracts)."""
    spec = importlib.util.spec_from_file_location("modelos_contrato", REFERENCE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["modelos_contrato"] = module
    spec.loader.exec_module(module)
    return module


def manifest(**changes: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "kind": "simulation",
        "status": "succeeded",
        "created_at": "2026-10-20T15:00:00Z",
        "case_id": "SYNTHETIC_DEMO",
        "case_version": "1.0.0",
        "scenario_id": None,
        "seed": 301,
        "protocol_id": None,
        "command": ["sumo", "-c", "inputs/demo.sumocfg"],
        "environment": {"sumo": "1.27.1"},
        "inputs": [
            {"artifact_id": "inputs/demo.sumocfg", "path": "inputs/demo.sumocfg", "sha256": HASH}
        ],
        "outputs": [
            {"artifact_id": "outputs/tripinfo.xml", "path": "outputs/tripinfo.xml", "sha256": HASH}
        ],
        "exit_code": 0,
        "error": None,
        "retry_of": None,
    }
    data.update(changes)
    return data


def validate(data: dict[str, Any]) -> RunManifest:
    return RunManifest.model_validate_json(json.dumps(data))


def test_the_schema_is_identical_to_the_published_contract() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert RunManifest.model_json_schema() == published


def test_the_contract_fixture_is_valid() -> None:
    fixture = RunManifest.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert (fixture.status, fixture.seed) == ("queued", 301)


def test_a_valid_manifest_round_trips_through_json() -> None:
    first = validate(manifest())
    assert RunManifest.model_validate_json(first.model_dump_json()) == first
    assert first.created_at == datetime(2026, 10, 20, 15, tzinfo=UTC)


INVALID: dict[str, dict[str, object]] = {
    "succeeded-with-nonzero-exit": {"exit_code": 1},
    "succeeded-without-exit": {"exit_code": None},
    "succeeded-without-outputs": {"outputs": []},
    "succeeded-with-error": {"error": {"code": "X", "field": None, "message": "m"}},
    "failed-without-error": {"status": "failed", "exit_code": 1},
    "naive-created-at": {"created_at": "2026-10-20T15:00:00"},
    "negative-seed": {"seed": -1},
    "unknown-kind": {"kind": "magic"},
    "unknown-field": {"extra": 1},
    "run-id-with-slash": {"run_id": "a/b"},
    "run-id-with-dots": {"run_id": ".."},
    "run-id-empty": {"run_id": ""},
    "run-id-with-backslash": {"run_id": "a\\b"},
    "artifact-outside": {
        "outputs": [{"artifact_id": "o", "path": "../tripinfo.xml", "sha256": HASH}]
    },
    "artifact-absolute": {
        "outputs": [{"artifact_id": "o", "path": "C:/tripinfo.xml", "sha256": HASH}]
    },
    "artifact-bad-hash": {
        "outputs": [{"artifact_id": "o", "path": "outputs/t.xml", "sha256": "x"}]
    },
    "repeated-artifact-id": {
        "outputs": [
            {"artifact_id": "o", "path": "outputs/a.xml", "sha256": HASH},
            {"artifact_id": "o", "path": "outputs/b.xml", "sha256": HASH},
        ]
    },
    "repeated-id-across-lists": {
        "outputs": [{"artifact_id": "inputs/demo.sumocfg", "path": "outputs/a.xml", "sha256": HASH}]
    },
    "repeated-path": {
        "outputs": [{"artifact_id": "o", "path": "inputs/demo.sumocfg", "sha256": HASH}]
    },
}


@pytest.mark.parametrize("changes", INVALID.values(), ids=INVALID.keys())
def test_rejects_invalid_manifests(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate(manifest(**changes))


def test_is_at_least_as_strict_as_the_reference_model() -> None:
    reference: type[BaseModel] = reference_module().RunManifest
    reference.model_validate_json(json.dumps(manifest()))
    reference_rejects = [
        "succeeded-with-nonzero-exit",
        "succeeded-without-outputs",
        "failed-without-error",
        "negative-seed",
        "unknown-kind",
        "unknown-field",
        "artifact-bad-hash",
    ]
    for name in reference_rejects:
        with pytest.raises(ValidationError):
            reference.model_validate_json(json.dumps(manifest(**INVALID[name])))


def test_a_failed_run_with_error_is_valid() -> None:
    failed = validate(
        manifest(
            status="failed",
            exit_code=1,
            outputs=[],
            error={"code": "SIM_FAILED", "field": None, "message": "SUMO terminó con código 1"},
        )
    )
    assert failed.error is not None
    assert failed.error.code == "SIM_FAILED"


def test_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        validate(manifest()).status = "failed"
