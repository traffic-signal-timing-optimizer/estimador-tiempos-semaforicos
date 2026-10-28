"""Pruebas de los informes y planillas de una recepción, sin ejecutar SUMO (F8)."""

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from semaforo.app.reception_models import BaseRunRecord, IncompleteRun
from semaforo.app.reception_report import (
    demand_types,
    find_machine_paths,
    findings_markdown,
    public_report,
    qa23_csv,
    qa24_csv,
)
from semaforo.caso.audit import audit_simulation
from semaforo.caso.audit_models import SimulationAudit
from semaforo.caso.inventory import read_network_inventory
from semaforo.caso.inventory_models import NetworkInventory
from semaforo.caso.movements import Movement, read_movements
from semaforo.caso.reception import snapshot_source
from semaforo.caso.reception_models import SnapshotManifest
from semaforo.trazabilidad.fs import remove_tree
from semaforo.trazabilidad.manifest import Artifact

DEMO = Path(__file__).resolve().parents[1] / "fixtures" / "sumo" / "demo"
HASH = "c" * 64
RUN = BaseRunRecord(
    run_id="20261020T190000Z_simulation_0000abcd",
    path="ejecuciones/20261020T190000Z_simulation_0000abcd",
    status="succeeded",
    manifest_sha256=HASH,
    exit_code=0,
    error_code=None,
    summary=None,
)


@pytest.fixture(scope="module")
def demo() -> tuple[NetworkInventory, list[Movement], SimulationAudit]:
    net = DEMO / "demo.net.xml"
    return (
        read_network_inventory(net),
        read_movements(net, ["passenger", "bus"]),
        audit_simulation(DEMO, "demo.sumocfg"),
    )


@pytest.fixture
def snapshot(tmp_path: Path) -> Iterator[SnapshotManifest]:
    root = tmp_path / "copias"
    yield snapshot_source(DEMO, "demo.sumocfg", root).manifest
    remove_tree(root)


def rows(data: bytes) -> list[list[str]]:
    assert data.startswith(b"\xef\xbb\xbf"), "UTF-8 con BOM, para que Excel muestre las tildes"
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))


def excel(value: str) -> str:
    """Celda que Excel muestra como el texto ``value`` (fórmula de texto)."""
    return f'="{value}"'


def test_qa23_has_one_row_per_movement_and_room_for_the_review(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit],
) -> None:
    table = rows(qa23_csv(demo[1]))
    assert table[0][0] == "ID"
    assert table[0][-2:] == ["Resultado (Correcto/Discrepancia)", "Nota"]
    assert [row[0] for row in table[1:3]] == ["QA23-M01", "QA23-M02"]
    assert table[0][2:4] == ["Enlace", "Enlace del punto de espera"]
    assert table[1][1:10] == [
        excel("DEMO_TLS"),
        "0",
        "",
        excel("demo_N"),
        "0",
        excel("demo_S"),
        "0",
        "recto",
        "auto, bus",
    ]
    assert table[1][-2:] == ["", ""]
    assert ["Revisado por:"] in table
    assert ["Fecha:"] in table


def test_qa23_names_the_vehicle_types_of_the_demand(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit],
) -> None:
    # Autos y camionetas son passenger: nombrar solo la clase («auto») ocultaba las camionetas.
    movement = demo[1][0].model_copy(update={"classes": ["passenger", "truck", "motorcycle"]})
    types = {
        "passenger": ["auto", "camioneta"],
        "truck": ["camion_ligero", "camion_mediano"],
    }
    table = rows(qa23_csv([movement], types))
    assert table[0][9] == "Vehículos de la demanda que pueden usarlo"
    # Una clase sin tipos en la demanda se nombra por la clase.
    assert table[1][9] == "auto, camioneta, camion_ligero, camion_mediano, moto"


def test_qa23_shows_the_sumo_default_type_by_its_class(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit],
) -> None:
    movement = demo[1][0].model_copy(update={"classes": ["passenger", "bus"]})
    types = {"passenger": ["DEFAULT_VEHTYPE", "auto"], "bus": ["bus_urbano"]}
    assert rows(qa23_csv([movement], types))[1][9] == "auto, bus_urbano"
    unusable = movement.model_copy(update={"classes": []})
    assert rows(qa23_csv([unusable], types))[1][9] == "ninguna"


def test_demand_types_groups_the_vehicle_types_by_class(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit],
) -> None:
    # El fixture declara tres flujos: dos de tipo car (passenger) y uno de tipo bus.
    assert demand_types(demo[2]) == {"bus": ["bus"], "passenger": ["car"]}


@pytest.mark.parametrize(
    ("identifier", "cell"),
    [
        # Excel convertiría estos en números o fechas: -1185174556 se vería como -1.185E+09.
        ("-1185174556", '="-1185174556"'),
        ("563085958", '="563085958"'),
        ("1-2", '="1-2"'),
        # Ni ejecuta una fórmula ni rompe la celda con comillas.
        ("=SUMA(1)", '="=SUMA(1)"'),
        ('a"b', '="a""b"'),
        # Excel no admite textos de más de 255 caracteres en una fórmula: queda tal cual.
        ("x" * 256, "x" * 256),
    ],
)
def test_identifiers_stay_text_in_excel(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit], identifier: str, cell: str
) -> None:
    inventory, movements, audit = demo
    movement = movements[0].model_copy(
        update={"tls_id": identifier, "from_edge": identifier, "to_edge": identifier}
    )
    row = rows(qa23_csv([movement]))[1]
    assert (row[1], row[4], row[6]) == (cell, cell, cell)
    tls = inventory.traffic_lights[0].model_copy(update={"id": identifier})
    renamed = inventory.model_copy(update={"traffic_lights": [tls]})
    phase = next(r for r in rows(qa24_csv(renamed, [movement], audit)) if "-F" in r[0])
    assert phase[1] == cell


def test_qa24_lists_each_phase_with_the_movements_it_lets_through(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit],
) -> None:
    inventory, movements, audit = demo
    table = rows(qa24_csv(inventory, movements, audit))
    phases = [row for row in table if row and row[0].startswith("QA24-S1-demo-F")]
    assert len(phases) == 6
    first = phases[0]
    assert first[1:3] == [excel("DEMO_TLS"), excel("demo")]
    (cycle_row,) = [row for row in table if row and row[0].endswith("-CICLO")]
    assert cycle_row[1:3] == [excel("DEMO_TLS"), excel("demo")]
    assert first[5:11] == ["0", "30", "", "", "M01", "-"]
    assert phases[1][9:11] == ["-", "M01"]
    assert phases[3][9] == "M02"
    (cycle,) = [row for row in table if row and row[0] == "QA24-S1-demo-CICLO"]
    assert cycle[6] == "60"
    ids = {row[0] for row in table if row}
    assert {"QA24-PEATONES", "QA24-FRONTERA"} <= ids
    assert "QA24-DETECTORES" not in ids  # el programa del fixture es fijo, no actuado
    assert "QA24-ESPERA" not in ids  # ningún movimiento del fixture tiene punto de espera


def test_the_waiting_point_inside_the_junction_has_its_own_signal(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit],
) -> None:
    # Giro a la izquierda con flecha: M02 entra con el enlace 1 y cruza con el 2 (linkIndex2).
    inventory, movements, audit = demo
    left = movements[1].model_copy(update={"waiting_link_index": 2})
    assert rows(qa23_csv([movements[0], left]))[2][2:4] == ["1", "2"]
    tls = inventory.traffic_lights[0]
    program = tls.programs[0]
    phases = [
        phase.model_copy(update={"state": state})
        for phase, state in zip(program.phases, ["GGr", "GgG", "ryy"], strict=False)
    ]
    changed = inventory.model_copy(
        update={
            "traffic_lights": [
                tls.model_copy(update={"programs": [program.model_copy(update={"phases": phases})]})
            ]
        }
    )
    table = rows(qa24_csv(changed, [movements[0], left], audit))
    lit = [(row[9], row[10]) for row in table if row and row[0].startswith("QA24-S1-demo-F")]
    assert lit == [
        ("M01 M02", "-"),
        ("M01 M02 M02-espera", "-"),
        ("-", "M02 M02-espera"),
    ]
    (waiting,) = [row for row in table if row and row[0] == "QA24-ESPERA"]
    assert "M02" in waiting[2]
    assert "M01" not in waiting[2]


def test_the_public_report_only_has_what_adr09_allows(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit], snapshot: SnapshotManifest
) -> None:
    artifacts = [Artifact(artifact_id="audit", path="audit.json", sha256="d" * 64)]
    text = public_report(
        reception_id="20261020T190000Z_0123abcd",
        created_at=datetime(2026, 10, 20, 19, 0, tzinfo=UTC),
        sumo_version="1.27.1",
        proposed_status="with_findings",
        snapshot=snapshot,
        run=RUN,
        artifacts=artifacts,
    )
    assert "20261020T190000Z_0123abcd" in text
    assert snapshot.snapshot_id in text
    assert HASH in text  # huella del manifiesto de la corrida base
    assert "1.27.1" in text
    assert "con hallazgos" in text
    for record in snapshot.files:
        assert f"`{record.path}`" in text
        assert record.sha256 is not None
        assert record.sha256 in text
    assert "`audit.json`" in text
    for detail in ("NO_END_TIME", "DEMAND", "minDur", "veh/h"):
        assert detail not in text
    assert find_machine_paths(text) == []


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("ver C:\\Users\\alguien\\x", True),
        ("ver D:/SUMO_demos/x", True),
        ("ver \\\\servidor\\recurso\\x", True),
        ("ver /home/alguien/x", True),
        ("ver /Users/alguien/x", True),
        ("ver inputs/demo.sumocfg y outputs/sumo.log", False),
        ("hora 19:00:00 y razón 3:1", False),
    ],
)
def test_find_machine_paths(text: str, *, found: bool) -> None:
    assert bool(find_machine_paths(text)) is found


def test_the_private_findings_list_every_finding(
    demo: tuple[NetworkInventory, list[Movement], SimulationAudit],
) -> None:
    inventory, movements, audit = demo
    unusable = movements[0].model_copy(update={"id": "M09", "classes": []})
    text = findings_markdown(
        reception_id="R",
        inventory=inventory,
        movements=[*movements, unusable],
        audit=audit,
        summary=None,
        incomplete_runs=[IncompleteRun(folder=".tmp-abc", run_id="X", created_at=None)],
    )
    assert "Privado (ADR09)" in text
    assert "`NO_END_TIME`" in text
    assert "La corrida base falló" in text
    assert "`.tmp-abc`" in text
    assert "ninguna clase de la demanda puede usar: 1 de 3 (M09)" in text
    assert "revision_qa23.csv" in text
    assert "netedit" in text  # la herramienta para revisar enlaces y fases
    # La planilla completada va fuera de la recepción, que no se modifica.
    assert "`datos/revisiones/R/`" in text
