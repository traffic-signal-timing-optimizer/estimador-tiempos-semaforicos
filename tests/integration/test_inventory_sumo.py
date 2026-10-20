"""El programa activo que declara el inventario es el que SUMO ejecuta (QA24).

Cuando un semáforo tiene varios programas en la red, SUMO 1.27.1 activa el último del archivo.
Esta prueba lo comprueba ejecutando SUMO sobre una copia del fixture. Se salta si SUMO no está
instalado (variable ``SUMO_HOME``).
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml.ElementTree import parse

from semaforo.caso.inventory import read_network_inventory

pytestmark = pytest.mark.sumo

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"
TLS_EVENTS = (
    '<additional><timedEvent type="SaveTLSStates" source="DEMO_TLS" dest="tls.xml"/></additional>'
)


def sumo_binary() -> Path | None:
    home = os.environ.get("SUMO_HOME")
    if home:
        for name in ("sumo.exe", "sumo"):
            candidate = Path(home) / "bin" / name
            if candidate.is_file():
                return candidate
    found = shutil.which("sumo")
    return Path(found) if found else None


def net_with_two_programs(original: str, *, alternative_first: bool) -> str:
    block = re.search(r"<tlLogic .*?</tlLogic>", original, re.S)
    assert block is not None
    demo = block.group(0)
    alternative = demo.replace('programID="demo"', 'programID="alt"')
    alternative = re.sub(r'duration="30(\.00)?"', 'duration="10"', alternative, count=1)
    programs = [alternative, demo] if alternative_first else [demo, alternative]
    return original.replace(demo, "\n".join(programs))


@pytest.mark.parametrize(
    ("alternative_first", "expected"),
    [(False, "alt"), (True, "demo")],
    ids=["alt-last", "demo-last"],
)
def test_sumo_runs_the_program_the_inventory_calls_active(
    tmp_path: Path, *, alternative_first: bool, expected: str
) -> None:
    binary = sumo_binary()
    if binary is None:
        pytest.skip("SUMO no está instalado (SUMO_HOME)")
    run = tmp_path / "run"
    shutil.copytree(DEMO, run)
    net = run / "demo.net.xml"
    net.write_text(
        net_with_two_programs(net.read_text(encoding="utf-8"), alternative_first=alternative_first),
        encoding="utf-8",
    )
    (run / "events.add.xml").write_text(TLS_EVENTS, encoding="utf-8")
    config = run / "demo.sumocfg"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            '<net-file value="demo.net.xml"/>',
            '<net-file value="demo.net.xml"/><additional-files value="events.add.xml"/>',
        ),
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603
        [str(binary), "-c", "demo.sumocfg", "--end", "5", "--no-step-log"],
        cwd=run,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    states = parse(run / "tls.xml").getroot()
    assert states is not None
    first_state = states.find("tlsState")
    assert first_state is not None
    assert first_state.get("programID") == expected
    (tls,) = read_network_inventory(net).traffic_lights
    assert tls.active_program_id == expected
