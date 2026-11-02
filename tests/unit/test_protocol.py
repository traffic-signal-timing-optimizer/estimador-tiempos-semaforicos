"""DTO del contrato protocol (DEV19 F2, decisión D5)."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from semaforo.dominio.errors import ErrorCode
from semaforo.dominio.protocol import Protocol, ProtocolInvalidError, parse_protocol

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "protocol.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "protocol.json"
REFERENCE = ROOT / "tools" / "contracts" / "modelos_contrato.py"
HASH = "b" * 64


def reference_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("modelos_contrato", REFERENCE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["modelos_contrato"] = module
    spec.loader.exec_module(module)
    return module


def protocol(**changes: object) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.update(changes)
    return data


def frozen_main(**changes: object) -> dict[str, Any]:
    """Un protocolo principal congelado con todo resuelto, con los cambios pedidos."""
    data = protocol(
        status="frozen",
        purpose="main_experiment",
        approval_reference="acta-2026-12-01",
        acceptance_margin_s=1.0,
        count_error_tolerance=0.1,
        simulation_fit_tolerance=0.15,
        calibration_criteria=[
            {
                "variable": "volume",
                "metric": "GEH",
                "unit": "1",
                "scope": "movimiento",
                "maximum_error": 5,
                "pilot_evidence": "piloto",
            },
            {
                "variable": "queue",
                "metric": "MAE",
                "unit": "veh",
                "scope": "acceso",
                "maximum_error": 2,
                "pilot_evidence": "piloto",
            },
        ],
    )
    data.update(changes)
    return data


def test_the_schema_is_identical_to_the_published_contract() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert Protocol.model_json_schema() == published


def test_the_contract_fixture_is_valid() -> None:
    parsed = parse_protocol(protocol())
    assert (parsed.status, parsed.queue_speed_threshold_mps, parsed.queue_sampling_s) == (
        "draft",
        0.1,
        1,
    )
    assert parsed.zone_lane_ids == ["demo_N_0", "demo_E_0"]


def test_a_frozen_main_protocol_with_everything_resolved_is_valid() -> None:
    assert parse_protocol(frozen_main()).status == "frozen"


def test_a_protocol_round_trips_through_json() -> None:
    parsed = parse_protocol(protocol())
    assert Protocol.model_validate_json(parsed.model_dump_json()) == parsed


INVALID: dict[str, dict[str, Any]] = {
    "alternative-without-rule": protocol(censoring_policy="approved_alternative"),
    "frozen-main-without-approval": frozen_main(approval_reference=None),
    "frozen-main-with-pending-margin": frozen_main(acceptance_margin_s=None),
    "frozen-main-with-pending-count-tolerance": frozen_main(count_error_tolerance=None),
    "frozen-main-with-pending-fit-tolerance": frozen_main(simulation_fit_tolerance=None),
    "frozen-main-without-volume": frozen_main(calibration_criteria=[]),
    "frozen-main-with-volume-only": frozen_main(
        calibration_criteria=[
            {
                "variable": "volume",
                "metric": "GEH",
                "unit": "1",
                "scope": "movimiento",
                "maximum_error": 5,
                "pilot_evidence": "piloto",
            }
        ]
    ),
    "declared-weights-without-artifact": protocol(group_aggregation="declared_field_weights"),
    "overlapping-seeds": protocol(seeds={"search": [1], "finalists": [1], "final": [2]}),
    "negative-seed": protocol(seeds={"search": [-1], "finalists": [2], "final": [3]}),
    "empty-seeds": protocol(seeds={"search": [], "finalists": [2], "final": [3]}),
    "unknown-field": protocol(extra=1),
    "missing-field": {k: v for k, v in protocol().items() if k != "zone_lane_ids"},
    "empty-zone": protocol(zone_lane_ids=[]),
    "zero-sampling": protocol(queue_sampling_s=0),
    "negative-queue-threshold": protocol(queue_speed_threshold_mps=-0.1),
    "negative-stop-threshold": protocol(stop_speed_threshold_mps=-0.1),
    "confidence-one": protocol(confidence_level=1),
    "confidence-zero": protocol(confidence_level=0),
    "zero-budget": protocol(search_budget=0),
    "budget-as-text": protocol(search_budget="10"),
    "budget-as-bool": protocol(search_budget=True),
    "unknown-status": protocol(status="approved"),
    "unknown-purpose": protocol(purpose="demo"),
    "unknown-refit": protocol(refit_policy="all"),
    "bad-artifact-hash": protocol(
        group_aggregation="declared_field_weights",
        group_weight_artifact={"artifact_id": "w", "path": "w.json", "sha256": "x"},
    ),
    "negative-tolerance": protocol(numeric_abs_tolerance=-1e-9),
    "other-schema-version": protocol(schema_version="2.0.0"),
}


@pytest.mark.parametrize("data", INVALID.values(), ids=INVALID.keys())
def test_rejects_invalid_protocols(data: dict[str, Any]) -> None:
    with pytest.raises(ProtocolInvalidError) as raised:
        parse_protocol(data)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert raised.value.issues


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ProtocolInvalidError):
        parse_protocol(protocol(queue_speed_threshold_mps=value))


def test_a_repeated_zone_lane_is_refused_although_the_reference_accepts_it() -> None:
    data = protocol(zone_lane_ids=["demo_N_0", "demo_N_0"])
    reference_module().Protocol.model_validate_json(json.dumps(data))
    with pytest.raises(ProtocolInvalidError, match="no pueden repetirse"):
        parse_protocol(data)


def test_a_declared_weights_protocol_with_its_artifact_is_valid() -> None:
    artifact = {"artifact_id": "w", "path": "w.json", "sha256": HASH}
    parsed = parse_protocol(
        protocol(group_aggregation="declared_field_weights", group_weight_artifact=artifact)
    )
    assert parsed.group_weight_artifact is not None


def test_is_at_least_as_strict_as_the_reference_model() -> None:
    reference: type[BaseModel] = reference_module().Protocol
    reference.model_validate_json(json.dumps(protocol()))
    for name, data in INVALID.items():
        try:
            reference.model_validate_json(json.dumps(data))
        except ValidationError:
            with pytest.raises(ProtocolInvalidError):
                parse_protocol(data)
        else:  # el de referencia lo acepta: el nuestro debe rechazarlo por su regla añadida
            pytest.fail(f"la referencia acepta {name}")


def test_the_error_reports_the_field() -> None:
    with pytest.raises(ProtocolInvalidError) as raised:
        parse_protocol(protocol(queue_sampling_s=0))
    assert raised.value.field == "queue_sampling_s"
    assert "queue_sampling_s" in raised.value.message


def test_the_protocol_cannot_be_changed_once_parsed() -> None:
    parsed = parse_protocol(protocol())
    with pytest.raises(ValidationError):
        parsed.status = "frozen"  # type: ignore[misc]
