"""Seguridad de las métricas (DEV19): FCD, tripinfo y protocolo son entradas no confiables."""

import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.caso.errors import CasoError
from semaforo.dominio.case import Case, parse_case
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.protocol import ProtocolInvalidError, parse_protocol
from semaforo.evaluacion.cohort import cohort_delay, require_supported
from semaforo.evaluacion.errors import EvaluacionError
from semaforo.evaluacion.fcd import read_fcd
from semaforo.evaluacion.run_metrics import evaluate_run
from semaforo.simulacion.prepare import publish_inputs
from semaforo.simulacion.reconcile import Reconciliation, VehicleOutcome
from semaforo.simulacion.tripinfo import Trip

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LIMIT = 64 * 1024 * 1024
MAX_MESSAGE = 400
HUGE = "x" * 1_000_000


def case() -> Case:
    return parse_case(json.loads((FIXTURES / "case.json").read_text(encoding="utf-8")))


def protocol_data(**changes: object) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "protocol.json").read_text(encoding="utf-8"))
    data.update(changes)
    return data


def read(tmp_path: Path, text: str) -> int:
    path = tmp_path / "fcd.xml"
    path.write_text(text, encoding="utf-8")
    return read_fcd(path, LIMIT, lambda _time, _records: None)


def test_a_billion_laughs_fcd_is_refused_quickly(tmp_path: Path) -> None:
    entities = "".join(f'<!ENTITY e{i} "&e{i - 1};&e{i - 1};">' for i in range(1, 30))
    text = f'<!DOCTYPE f [<!ENTITY e0 "ja">{entities}]><fcd-export>&e29;</fcd-export>'
    started = time.perf_counter()
    with pytest.raises(CasoError):
        read(tmp_path, text)
    assert time.perf_counter() - started < 5


def test_an_external_entity_is_not_resolved(tmp_path: Path) -> None:
    secret = tmp_path / "secreto.txt"
    secret.write_text("clave", encoding="utf-8")
    text = f'<!DOCTYPE f [<!ENTITY s SYSTEM "{secret.as_uri()}">]><fcd-export>&s;</fcd-export>'
    with pytest.raises(CasoError) as raised:
        read(tmp_path, text)
    assert "clave" not in raised.value.message


def test_a_huge_repeated_vehicle_id_gives_a_short_message(tmp_path: Path) -> None:
    vehicle = f'<vehicle id="{HUGE}" speed="1" lane="x"/>'
    text = f'<fcd-export><timestep time="0">{vehicle}{vehicle}</timestep></fcd-export>'
    with pytest.raises(CasoError) as raised:
        read(tmp_path, text)
    assert len(raised.value.message) < MAX_MESSAGE


def test_a_huge_vehicle_id_with_negative_speed_gives_a_short_message(tmp_path: Path) -> None:
    vehicle = f'<vehicle id="{HUGE}" speed="-1" lane="x"/>'
    text = f'<fcd-export><timestep time="0">{vehicle}</timestep></fcd-export>'
    with pytest.raises(CasoError) as raised:
        read(tmp_path, text)
    assert len(raised.value.message) < MAX_MESSAGE


@pytest.mark.parametrize("value", ["1e400", "-1e400", "1e308e2", "0x10", "infinity", ""])
def test_numbers_that_are_not_finite_decimals_are_refused(tmp_path: Path, value: str) -> None:
    vehicle = f'<vehicle id="a" speed="{value}" lane="x"/>'
    text = f'<fcd-export><timestep time="0">{vehicle}</timestep></fcd-export>'
    with pytest.raises(CasoError):
        read(tmp_path, text)


def test_deep_nesting_inside_a_step_does_not_crash(tmp_path: Path) -> None:
    depth = 20_000
    nested = "<a>" * depth + "</a>" * depth
    text = f'<fcd-export><timestep time="0">{nested}</timestep></fcd-export>'
    started = time.perf_counter()
    assert read(tmp_path, text) == 1
    assert time.perf_counter() - started < 10


def test_many_steps_are_read_without_keeping_them(tmp_path: Path) -> None:
    steps = "".join(
        f'<timestep time="{t}"><vehicle id="v{t % 50}" speed="0" lane="demo_N_0"/></timestep>'
        for t in range(200_000)
    )
    seen = 0

    def count(_time: float, records: list[Any]) -> None:
        nonlocal seen
        seen += len(records)

    path = tmp_path / "fcd.xml"
    path.write_text(f"<fcd-export>{steps}</fcd-export>", encoding="utf-8")
    assert read_fcd(path, LIMIT, count) == 200_000
    assert seen == 200_000


def test_huge_protocol_policies_give_short_messages() -> None:
    with pytest.raises(EvaluacionError) as raised:
        require_supported(parse_protocol(protocol_data(cohort_policy=HUGE)))
    assert len(raised.value.message) < MAX_MESSAGE
    alternative = parse_protocol(
        protocol_data(censoring_policy="approved_alternative", alternate_censoring_rule=HUGE)
    )
    with pytest.raises(EvaluacionError) as raised:
        require_supported(alternative)
    assert len(raised.value.message) < MAX_MESSAGE


@pytest.mark.parametrize(
    "changes",
    [
        {"zone_lane_ids": [HUGE, HUGE]},
        {"queue_sampling_s": float("inf")},
        {"queue_speed_threshold_mps": "0.1"},
        {"seeds": {"search": [True], "finalists": [2], "final": [3]}},
    ],
)
def test_a_hostile_protocol_is_refused_with_a_short_message(changes: dict[str, Any]) -> None:
    with pytest.raises(ProtocolInvalidError) as raised:
        parse_protocol(protocol_data(**changes))
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert len(raised.value.message) < MAX_MESSAGE


def test_a_huge_vehicle_id_in_the_trips_gives_a_short_message() -> None:
    outcome = VehicleOutcome(
        vehicle_id=HUGE,
        movement_id="N_S",
        vehicle_class="car",
        in_cohort=True,
        scheduled_s=0.0,
        status="finished",
        inserted_s=0.0,
        arrival_s=10.0,
    )
    reconciliation = Reconciliation(
        outcomes=[outcome], counts=[], requested=1, finished=1, unfinished=0, not_inserted=0
    )
    with pytest.raises(EvaluacionError) as raised:
        cohort_delay(reconciliation, {HUGE: Trip(0.0, 10.0)}, case(), 100.0)
    assert len(raised.value.message) < MAX_MESSAGE


@pytest.mark.parametrize("run_id", ["../fuera", "..\\fuera", "C:/x", "/x", ".oculta", ""])
def test_a_hostile_run_id_cannot_leave_the_runs_folder(tmp_path: Path, run_id: str) -> None:
    request = request_for(tmp_path)
    folder = publish_inputs(tmp_path / "entradas", request, MOMENT)
    (tmp_path / "runs").mkdir()
    with pytest.raises(DomainError) as raised:
        evaluate_run(
            folder, tmp_path / "runs", run_id, request.case, parse_protocol(protocol_data())
        )
    assert raised.value.code in {ErrorCode.PATH_NOT_ALLOWED, ErrorCode.INPUT_SCHEMA}
    assert not (tmp_path / "fuera").exists()
    shutil.rmtree(tmp_path / "runs")
