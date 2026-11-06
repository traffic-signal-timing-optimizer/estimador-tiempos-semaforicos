"""Qué protocolo mide cada corrida que no tiene métricas (DEV31 F4)."""

from datetime import UTC, datetime
from pathlib import Path

from search_tools import protocol
from semaforo.bd import metricas
from semaforo.bd.metricas import choose_protocol, zone_edges
from semaforo.trazabilidad.manifest import Error, RunManifest

ONE = protocol(protocol_id="UNO", zone_lane_ids=["a_0", "a_1", "b_0"])
SAME_ZONE = protocol(protocol_id="OTRO", zone_lane_ids=["b_0", "a_1", "a_0"])
WIDER = protocol(protocol_id="AMPLIO", zone_lane_ids=["a_0", "b_0", "c_0"])
EDGES = frozenset({"a", "b"})


def test_the_zone_of_a_protocol_is_its_streets_without_the_lane_index() -> None:
    assert zone_edges(ONE) == EDGES
    assert zone_edges(WIDER) == frozenset({"a", "b", "c"})


def test_a_run_is_measured_with_the_only_protocol_that_has_exactly_its_zone() -> None:
    chosen, reason = choose_protocol(EDGES, {"UNO": ONE, "AMPLIO": WIDER})
    assert (chosen, reason) == (ONE, None)


def test_a_wider_zone_than_the_run_recorded_is_not_a_match() -> None:
    chosen, reason = choose_protocol(frozenset({"a"}), {"UNO": ONE, "AMPLIO": WIDER})
    assert chosen is None
    assert reason is not None
    assert "exactamente" in reason


def test_two_protocols_with_the_same_zone_need_the_choice_to_be_said() -> None:
    both = {"UNO": ONE, "OTRO": SAME_ZONE}
    chosen, reason = choose_protocol(EDGES, both)
    assert chosen is None
    assert reason is not None
    assert "OTRO, UNO" in reason
    assert "--protocolo" in reason
    assert choose_protocol(EDGES, both, "OTRO") == (SAME_ZONE, None)


def test_a_requested_protocol_that_does_not_fit_is_not_used() -> None:
    chosen, reason = choose_protocol(EDGES, {"UNO": ONE, "AMPLIO": WIDER}, "AMPLIO")
    assert chosen is ONE
    assert reason is None
    none, why = choose_protocol(EDGES, {"AMPLIO": WIDER}, "AMPLIO")
    assert none is None
    assert why is not None


def _manifest(status: str) -> RunManifest:
    failed = status == "failed"
    return RunManifest.model_validate(
        {
            "run_id": "r1",
            "kind": "simulation",
            "status": status,
            "created_at": datetime(2026, 11, 6, tzinfo=UTC),
            "case_id": "c",
            "case_version": "1.0.0",
            "scenario_id": "s",
            "seed": 1,
            "protocol_id": None,
            "command": ["sumo"],
            "environment": {},
            "inputs": [],
            "outputs": [{"artifact_id": "o", "path": "outputs/x", "sha256": "a" * 64}],
            "exit_code": 1 if failed else 0,
            "error": Error(code="SIM_FAILED", field=None, message="m") if failed else None,
            "retry_of": None,
        }
    )


def test_only_a_succeeded_run_with_its_inputs_can_be_measured(tmp_path: Path) -> None:
    inputs = tmp_path / "manifiesto.json"
    inputs.write_text("{}", encoding="utf-8")
    assert metricas._cannot_measure(_manifest("succeeded"), inputs) is None  # pyright: ignore[reportPrivateUsage]
    failed = metricas._cannot_measure(_manifest("failed"), inputs)  # pyright: ignore[reportPrivateUsage]
    assert failed is not None
    assert "no terminó bien" in failed
    missing = metricas._cannot_measure(_manifest("succeeded"), tmp_path / "no-esta.json")  # pyright: ignore[reportPrivateUsage]
    assert missing is not None
    assert "DEV06" in missing
