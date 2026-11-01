"""Límites de una corrida y modelo de sus tiempos (DEV07 F2, decisiones D6, D7 y D19)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from semaforo.simulacion.process import ProcessLimits
from semaforo.simulacion.runner import RunLimits
from semaforo.simulacion.summary import RunTiming

GIB = 1024**3
MIB = 1024 * 1024
NOON = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def test_the_default_limits_are_the_ones_of_the_decisions() -> None:
    limits = RunLimits()
    assert limits.end_s == 7200
    assert limits.wall_timeout_s == 900
    assert limits.max_output_bytes == 512 * MIB
    assert limits.max_log_bytes == 16 * MIB
    assert limits.max_memory_bytes == 4 * GIB
    assert limits.min_free_memory_bytes == 1 * GIB
    assert limits.poll_s == 0.25


def not_positive(field: str, value: int) -> RunLimits:
    """Un ``RunLimits`` con un solo campo cambiado, escrito campo por campo para los tipos."""
    return {
        "end_s": lambda: RunLimits(end_s=value),
        "wall_timeout_s": lambda: RunLimits(wall_timeout_s=value),
        "smoke_end_s": lambda: RunLimits(smoke_end_s=value),
        "max_output_bytes": lambda: RunLimits(max_output_bytes=value),
        "max_log_bytes": lambda: RunLimits(max_log_bytes=value),
        "max_memory_bytes": lambda: RunLimits(max_memory_bytes=value),
        "poll_s": lambda: RunLimits(poll_s=value),
    }[field]()


@pytest.mark.parametrize(
    "field",
    [
        "end_s",
        "wall_timeout_s",
        "smoke_end_s",
        "max_output_bytes",
        "max_log_bytes",
        "max_memory_bytes",
        "poll_s",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_a_limit_that_is_not_positive_is_refused(field: str, value: int) -> None:
    with pytest.raises(ValueError, match="deben ser positivos"):
        not_positive(field, value)


def test_the_minimum_free_memory_may_be_zero_but_not_negative() -> None:
    assert RunLimits(min_free_memory_bytes=0).min_free_memory_bytes == 0
    with pytest.raises(ValueError, match="no puede ser negativo"):
        RunLimits(min_free_memory_bytes=-1)


def test_the_path_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_path_chars"):
        RunLimits(max_path_chars=0)


def test_the_process_limits_come_from_the_run_limits() -> None:
    limits = RunLimits(
        wall_timeout_s=5, max_output_bytes=6, max_log_bytes=7, max_memory_bytes=8, poll_s=0.5
    )
    assert limits.process_limits() == ProcessLimits(
        wall_timeout_s=5, max_output_bytes=6, max_log_bytes=7, max_memory_bytes=8, poll_s=0.5
    )


# --- tiempos --------------------------------------------------------------------------------


def timing(**changes: object) -> RunTiming:
    values: dict[str, object] = {
        "started_at": NOON,
        "finished_at": NOON,
        "duration_s": 8.5,
        "wall_timeout_s": 900,
        "end_s": 2100,
        "termination": "completed",
        "peak_memory_bytes": 35 * MIB,
        "output_bytes": 850_000,
    }
    values.update(changes)
    return RunTiming.model_validate(values)


def test_a_timing_survives_a_round_trip_through_json() -> None:
    original = timing()
    assert RunTiming.model_validate_json(original.model_dump_json()) == original


def test_the_memory_may_be_unknown() -> None:
    assert timing(peak_memory_bytes=None).peak_memory_bytes is None


@pytest.mark.parametrize(
    "termination",
    [
        "completed",
        "sumo_error",
        "timeout",
        "cancelled",
        "output_budget",
        "memory_budget",
        "not_started",
    ],
)
def test_every_way_of_ending_is_valid(termination: str) -> None:
    assert timing(termination=termination).termination == termination


def test_an_unknown_way_of_ending_is_refused() -> None:
    with pytest.raises(ValidationError):
        timing(termination="se cayó")


@pytest.mark.parametrize(
    "change",
    [
        {"duration_s": -1},
        {"wall_timeout_s": 0},
        {"end_s": 0},
        {"peak_memory_bytes": -1},
        {"output_bytes": -1},
        {"started_at": "ayer"},
    ],
)
def test_an_invalid_timing_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        timing(**change)


def test_an_unknown_field_in_the_timing_is_refused() -> None:
    with pytest.raises(ValidationError):
        timing(extra="no")
