"""Recorrido completo de la base sintética con SUMO real (DEV10 F2, decisión D9).

Caso → aforos → calidad → programa → entradas → dos corridas → réplica → revisión. Cada valor se
compara con un cálculo hecho a mano en la prueba, no con lo que devuelve el código:

- El aforo del ejemplo: 90 autos y 10 buses en N_S, y 50 autos y 0 buses en E_W, en 900 s.
  N_S: (90 + 10) / 900 s x 3600 = 400 veh/h, con 0.9 de autos y 0.1 de buses.
  E_W: 50 / 900 s x 3600 = 200 veh/h, con 1.0 de autos y 0.0 de buses.
- El escenario pide esos mismos flujos durante 900 s: 400 x 0.25 h = 100 vehículos en N_S y
  200 x 0.25 h = 50 en E_W, 150 en total. Son los vehículos de la cohorte.
- Contra un control de 100 autos en N_S (los demás iguales), el error absoluto es 10 y el
  relativo 10 / 100 = 0.1; la cobertura de la ventana de 08:00 a 08:15 es 900 / 900 = 1.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from prepared_inputs import FIXTURES, json_of
from semaforo.app.integrity import trace_run, verify_workspace
from semaforo.app.replica import replicate
from semaforo.app.simulate import run_prepared
from semaforo.caso.case_validation import read_case
from semaforo.datos.coverage import assess_coverage, list_missing
from semaforo.datos.normalizer import prepare_counts
from semaforo.datos.quality import compare_files, find_exclusions
from semaforo.datos.quality_report import ReportInputs, publish_quality, read_quality_report
from semaforo.dominio.scenario import parse_scenario
from semaforo.simulacion.run_inputs import verify_inputs
from semaforo.trazabilidad.fs import remove_tree
from workspace_tools import build_workspace

pytestmark = pytest.mark.sumo

LIMA = timezone(timedelta(hours=-5))
START = datetime(2026, 10, 18, 8, 0, tzinfo=LIMA)
END = START + timedelta(minutes=15)
HEADER = (
    "case_id,observation_id,source_id,origin,start,end,"
    "movement_id,vehicle_class,count,quality_state"
)
PERIOD = "2026-10-18T08:00:00-05:00,2026-10-18T08:15:00-05:00"
CONTROL_COUNTS = {("N_S", "car"): 100, ("N_S", "bus"): 10, ("E_W", "car"): 50, ("E_W", "bus"): 0}
# A mano, ver el encabezado del archivo.
HAND_FLOWS = {"N_S": (400.0, {"car": 0.9, "bus": 0.1}), "E_W": (200.0, {"car": 1.0, "bus": 0.0})}
HAND_COHORT = 150


@pytest.fixture
def built(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    workspace, inputs = build_workspace(tmp_path)
    yield workspace, inputs
    remove_tree(workspace)


def test_the_synthetic_base_works_from_the_counts_to_the_replica(
    tmp_path: Path, built: tuple[Path, Path], sumo_binary: Path
) -> None:
    workspace, inputs = built
    case = read_case(next((workspace / "casos").iterdir()) / "case.json")

    # 1. Aforos: normalización contra el cálculo a mano.
    counts = FIXTURES / "aforos.csv"
    [period] = prepare_counts(counts, case).periods
    assert period.status == "complete"
    assert period.duration_s == 900
    for flow in period.movements:
        hand_flow, hand_composition = HAND_FLOWS[flow.movement_id]
        assert flow.flow_vph == hand_flow
        assert dict(flow.composition) == hand_composition

    # 2. El escenario pide exactamente esos flujos, y de ellos salen 150 vehículos.
    scenario = parse_scenario(json_of("scenario.json"))
    asked = {
        item.movement_id: (item.flow_vph, dict(item.composition or {}))
        for item in scenario.request.demand
    }
    assert asked == HAND_FLOWS
    assert sum(flow * 900 / 3600 for flow, _ in HAND_FLOWS.values()) == HAND_COHORT

    # 3. Calidad frente a un control: error absoluto 10 y relativo 0.1; cobertura 1.
    control = tmp_path / "control.csv"
    rows = [
        f"SYNTHETIC_DEMO,CTL,MANUAL,synthetic,{PERIOD},{movement},{vclass},{count},observed"
        for (movement, vclass), count in CONTROL_COUNTS.items()
    ]
    control.write_text("\n".join([HEADER, *rows]) + "\n", encoding="utf-8")
    comparison = compare_files(counts, control, case)
    [window] = comparison.windows
    found = {(c.movement_id, c.vehicle_class): c for c in window.counts}
    car = found["N_S", "car"]
    assert (car.absolute_error, car.absolute_value, car.relative_error) == (-10, 10, 0.1)
    assert all(
        found[key].absolute_error == 0 for key in found if key != ("N_S", "car")
    )  # el resto coincide con el control
    prepared = prepare_counts(counts, case)
    coverage = assess_coverage(prepared, case, (START, END))
    assert (coverage.window_s, coverage.covered_s, coverage.coverage) == (900, 900, 1.0)
    report_folder = publish_quality(
        workspace / "derivados" / "calidad",
        ReportInputs(
            comparison=comparison,
            coverage=coverage,
            exclusions=find_exclusions(comparison, None),
            missing=list_missing(prepared),
            case=case,
            max_relative_error=None,
        ),
        datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert read_quality_report(report_folder).case_id == "SYNTHETIC_DEMO"

    # 4. Entradas: la cohorte declarada es la que salió a mano.
    manifest = verify_inputs(inputs)
    assert manifest.scenario_id == scenario.scenario_id
    assert manifest.case_sha256 and manifest.seeds.demand_seed == 100

    # 5. Dos corridas con SUMO real: cuentan los mismos vehículos que se pidieron.
    first = run_prepared(inputs, workspace, sumo=sumo_binary)
    second = run_prepared(inputs, workspace, sumo=sumo_binary)
    assert (first.status, second.status) == ("succeeded", "succeeded")
    for report in (first, second):
        conciliation = report.conciliation
        assert conciliation is not None
        assert conciliation.requested == HAND_COHORT
        assert conciliation.finished + conciliation.unfinished + conciliation.not_inserted == (
            HAND_COHORT
        )
        by_key = {(c.movement_id, c.vehicle_class): c.requested for c in conciliation.counts}
        # E_W / bus pide 0 vehículos, así que no hay ninguno que conciliar
        assert by_key == {("N_S", "car"): 90, ("N_S", "bus"): 10, ("E_W", "car"): 50}

    # 6. Réplica y revisión de todo el espacio.
    replica, folder = replicate(workspace, first.run_id, second.run_id)
    assert (replica.verdict, replica.reasons) == ("equivalent", [])
    assert trace_run(workspace, first.run_id).status == "complete"
    overall = verify_workspace(workspace)
    assert overall.status == "intact"
    assert {item.family for item in overall.items} >= {
        "runs",
        "programs",
        "inputs",
        "quality",
        "replicas",
    }
    assert (workspace / folder.relative_to(workspace)).is_dir()
