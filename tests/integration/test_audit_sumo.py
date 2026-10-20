"""Los vehículos que la auditoría espera de un flujo son los que SUMO carga.

SUMO 1.27.1 emite techo(duración / intervalo) vehículos en un flujo de intervalo fijo, con el
final excluido. Esta prueba lo comprueba ejecutando SUMO sobre una copia del fixture.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml.ElementTree import parse

from semaforo.caso.audit import audit_simulation

pytestmark = pytest.mark.sumo

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"
FLOWS = {
    "per-hour-late-start": 'begin="6" end="3600" perHour="200"',
    "per-hour-later-start": 'begin="12" end="3600" perHour="200"',
    "per-hour-exact": 'begin="0" end="3600" perHour="600"',
    "per-hour-700": 'begin="0" end="1800" perHour="700"',
    "vehs-per-hour": 'begin="0" end="100" vehsPerHour="252"',
    "period-7": 'begin="0" end="100" period="7"',
    "period-late-start": 'begin="5" end="50" period="3"',
    "number": 'begin="0" end="900" number="7"',
}


@pytest.mark.parametrize("attributes", FLOWS.values(), ids=FLOWS.keys())
def test_expected_vehicles_match_what_sumo_loads(
    tmp_path: Path, sumo_binary: Path, attributes: str
) -> None:
    run = tmp_path / "run"
    shutil.copytree(DEMO, run)
    (run / "demo.rou.xml").write_text(
        f'<routes><route id="N_S" edges="demo_N demo_S"/><flow id="f" route="N_S" {attributes}/>'
        "</routes>",
        encoding="utf-8",
    )
    (item,) = audit_simulation(run, "demo.sumocfg").demand
    result = subprocess.run(  # noqa: S603
        [str(sumo_binary), "-c", "demo.sumocfg", "--end", "8000", "--no-step-log"],
        cwd=run,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    statistics = parse(run / "statistics.xml").getroot()
    assert statistics is not None
    vehicles = statistics.find("vehicles")
    assert vehicles is not None
    assert float(vehicles.get("loaded", "nan")) == item.expected_vehicles
