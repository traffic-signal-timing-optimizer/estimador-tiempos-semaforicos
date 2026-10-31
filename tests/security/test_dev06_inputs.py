"""Seguridad de nombres, rutas y archivos en las entradas de SUMO de DEV06 (QA10, F3).

Cada caso intenta colar texto peligroso por una puerta distinta (rutas, tipos, red, nombres de
carpeta, opciones de SUMO) y comprueba que se rechaza antes de escribir nada, o que lo escrito
no cambia de estructura.
"""

import csv
import io
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from defusedxml.ElementTree import fromstring

from prepared_inputs import MOMENT, ROUTES, TYPES, json_of, request_for
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.demand_inputs import DemandInputError, RouteTable, VehicleTypes
from semaforo.simulacion.prepare import PreparationRequest, build_inputs, publish_inputs
from semaforo.trazabilidad.fs import remove_tree

INJECTION = '"/><evil x="'


def tree_of(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def with_type(change: dict[str, Any]) -> VehicleTypes:
    types: dict[str, Any] = {name: dict(value) for name, value in TYPES["types"].items()}
    types["car"] = {**types["car"], **change}
    return VehicleTypes.model_validate({"types": types})


def attempt(tmp_path: Path, request: PreparationRequest) -> None:
    """Intenta publicar y comprueba que no queda nada escrito."""
    root = tmp_path / "entradas"
    with pytest.raises(DomainError):
        publish_inputs(root, request, MOMENT)
    assert not root.exists() or not [p for p in root.rglob("*") if p.is_file()]


def test_an_xml_injection_in_a_route_street_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    routes = {"routes": {"N_S": ["demo_N", INJECTION], "E_W": ROUTES["routes"]["E_W"]}}
    request = request_for(tmp_path, routes=routes)
    with pytest.raises(DemandInputError) as raised:
        publish_inputs(tmp_path / "entradas", request, MOMENT)
    assert raised.value.code is ErrorCode.INPUT_SCHEMA
    assert any(issue.rule_id == "ROUTE-02" for issue in raised.value.issues)
    assert not (tmp_path / "entradas").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"vclass": INJECTION},
        {"gui_shape": INJECTION},
        {"color": INJECTION},
        {"attributes": {INJECTION: 1.0}},
        {"attributes": {"length": float("inf")}},
        {"attributes": {"length": float("nan")}},
    ],
)
def test_a_vehicle_type_cannot_carry_text_into_the_xml(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    try:
        types = with_type(change)
    except ValueError:
        return  # el modelo ya lo rechaza al leerlo
    request = request_for(tmp_path)
    attempt(tmp_path, replace(request, vehicle_types=types))


@pytest.mark.parametrize(
    "option",
    [
        "tripinfo-output",
        "net-file",
        "route-files",
        "additional-files",
        "output-prefix",
        "configuration-file",
        "save-configuration",
        "log",
        "error-log",
        "end",
        "seed",
    ],
)
def test_a_sumo_option_that_can_write_or_read_files_is_refused(tmp_path: Path, option: str) -> None:
    request = request_for(tmp_path, sumo_options={option: 1})
    attempt(tmp_path, request)


@pytest.mark.parametrize(
    "scenario_id",
    ["../fuera", "..", "a/b", "a\\b", "C:\\Windows", "/etc", ".oculto", "a b", "con;punto&coma"],
)
def test_a_scenario_id_that_could_leave_the_folder_writes_nothing_anywhere(
    tmp_path: Path, scenario_id: str
) -> None:
    def change(data: dict[str, Any]) -> None:
        data["scenario_id"] = scenario_id

    request = request_for(tmp_path, scenario_change=change)
    before = tree_of(tmp_path)
    with pytest.raises(DomainError) as raised:
        publish_inputs(tmp_path / "entradas", request, MOMENT)
    assert raised.value.code is ErrorCode.PATH_NOT_ALLOWED
    assert tree_of(tmp_path) == before


def test_a_network_with_an_entity_declaration_is_refused(tmp_path: Path) -> None:
    def with_entity(text: str) -> str:
        return text.replace("<net ", '<!DOCTYPE net [<!ENTITY x "boom">]>\n<net ', 1)

    with pytest.raises(DomainError):
        publish_inputs(tmp_path / "entradas", request_for(tmp_path, net=with_entity), MOMENT)
    assert not (tmp_path / "entradas").exists()


def test_a_tampered_network_is_refused_by_its_hash(tmp_path: Path) -> None:
    request = request_for(tmp_path)
    path = next(request.case_dir.glob("demo.net.xml"))
    path.write_bytes(path.read_bytes() + b"\n<!-- cambio -->\n")
    with pytest.raises(DomainError) as raised:
        build_inputs(request, MOMENT)
    assert raised.value.code is ErrorCode.HASH_MISMATCH


def test_every_identifier_in_the_sheet_is_text_for_the_spreadsheet(tmp_path: Path) -> None:
    folder = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    text = (folder / "cohorte.csv").read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    for row in rows[1:]:
        assert all(cell.startswith('="') and cell.endswith('"') for cell in row[:5])
    remove_tree(tmp_path / "entradas")


def test_the_written_xml_keeps_its_structure_whatever_the_names(tmp_path: Path) -> None:
    folder = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    root = fromstring((folder / "demanda.rou.xml").read_bytes(), forbid_dtd=True)
    assert {child.tag for child in root} == {"vType", "route", "vehicle"}
    assert not any("evil" in element.tag for element in root.iter())
    remove_tree(tmp_path / "entradas")


def test_a_routes_file_cannot_name_a_street_outside_the_network(tmp_path: Path) -> None:
    table = RouteTable.model_validate(
        {"routes": {"N_S": ["demo_N", "../../etc/passwd"], "E_W": ROUTES["routes"]["E_W"]}}
    )
    request = request_for(tmp_path)
    attempt(tmp_path, replace(request, routes=table))


def test_the_example_files_are_the_clean_baseline(tmp_path: Path) -> None:
    assert json_of("case.json")["case_id"] == "SYNTHETIC_DEMO"
    folder = publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)
    assert sorted(p.name for p in folder.iterdir()) == [
        "cohorte.csv",
        "demanda.rou.xml",
        "escenario.sumocfg",
        "manifiesto.json",
        "programa.tll.xml",
        "red.net.xml",
    ]
    remove_tree(tmp_path / "entradas")
