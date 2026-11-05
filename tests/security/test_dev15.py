"""Seguridad de los comparadores (DEV15 F5, HU08 y HU12).

El archivo de parámetros de Webster, la carpeta del programa vigente y una carpeta de comparadores
publicada se leen como no confiables: se prueba que un valor hostil se rechaza con un error de
dominio y un mensaje corto, que no se lee sin límite, que los enlaces no se siguen y que un
archivo cambiado se nota. Datos sintéticos, sin SUMO.
"""

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from baselines_tools import parameters, parameters_data
from prepared_inputs import request_for
from semaforo.caso.json_input import MAX_JSON_BYTES
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.dominio.feasibility import prepare
from semaforo.referencias.baselines import read_parameters
from semaforo.referencias.comparators import (
    COMPARATORS_FILE,
    MANIFEST_FILE,
    compute_comparators,
    publish_comparators,
    read_comparators,
)
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import TrazabilidadError

MAX_MESSAGE = 400


def new_dir(tmp_path: Path, name: str = "caso") -> Path:
    folder = tmp_path / name
    folder.mkdir()
    return folder


def published(tmp_path: Path) -> Path:
    request = request_for(new_dir(tmp_path))
    result = compute_comparators(
        prepare(request.case), request.scenario, parameters(), request.program_dir
    )
    return publish_comparators(tmp_path / "datos", result)


def write_parameters(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "parametros.json"
    path.write_text(json.dumps(data, allow_nan=True), encoding="utf-8")
    return path


def forge(folder: Path, name: str, data: bytes) -> None:
    """Cambia un archivo y pone su huella nueva en el manifiesto (un ataque que lo sabe todo)."""
    path = folder / name
    path.chmod(stat.S_IWRITE)
    path.write_bytes(data)
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = sha256_bytes(data)
    manifest_path.chmod(stat.S_IWRITE)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


# --- parámetros de Webster ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"saturation_flow_veh_h_lane": float("nan")},
        {"saturation_flow_veh_h_lane": float("inf")},
        {"saturation_flow_veh_h_lane": -1800},
        {"saturation_flow_veh_h_lane": 0},
        {"saturation_flow_veh_h_lane": True},
        {"saturation_flow_veh_h_lane": "1800"},
        {"saturation_flow_sensitivity_veh_h_lane": [1500, float("nan")]},
        {"saturation_flow_sensitivity_veh_h_lane": [1500, -1]},
        {"saturation_flow_sensitivity_veh_h_lane": [1000 + i for i in range(10_000)]},
        {"vehicle_equivalence": {"passenger": -1.0}},
        {"vehicle_equivalence": {"passenger": float("inf")}},
        {"status": "approved"},  # aprobado sin especialista
        {"lost_time_rule": "fixed_24_s"},
        {"applicability": {"y_must_be_below": 1.0, "cycle_must_be_inside_bounds": True}},
        {"extra": "campo desconocido"},
    ],
    ids=[
        "saturacion-nan",
        "saturacion-infinita",
        "saturacion-negativa",
        "saturacion-cero",
        "saturacion-booleana",
        "saturacion-texto",
        "sensibilidad-nan",
        "sensibilidad-negativa",
        "sensibilidad-enorme",
        "equivalencia-negativa",
        "equivalencia-infinita",
        "aprobado-sin-especialista",
        "otra-regla-de-perdidas",
        "aplicabilidad-incompleta",
        "campo-desconocido",
    ],
)
def test_hostile_webster_parameters_are_refused(tmp_path: Path, change: dict[str, Any]) -> None:
    request = request_for(new_dir(tmp_path))
    path = write_parameters(tmp_path, parameters_data(**change))
    with pytest.raises(DomainError) as error:
        read_parameters(path, request.case)
    assert error.value.code == ErrorCode.INPUT_SCHEMA
    assert len(error.value.message) < MAX_MESSAGE


def test_a_huge_case_name_in_the_parameters_gives_a_short_message(tmp_path: Path) -> None:
    request = request_for(new_dir(tmp_path))
    path = write_parameters(tmp_path, parameters_data(case_id="x" * 1_000_000))
    with pytest.raises(DomainError) as error:
        read_parameters(path, request.case)
    assert error.value.code == ErrorCode.INPUT_SCHEMA
    assert len(error.value.message) < MAX_MESSAGE


def test_a_parameters_file_over_the_limit_is_refused_before_parsing(tmp_path: Path) -> None:
    request = request_for(new_dir(tmp_path))
    path = tmp_path / "parametros.json"
    path.write_bytes(b" " * (MAX_JSON_BYTES + 1))
    with pytest.raises(DomainError) as error:
        read_parameters(path, request.case)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_parameters_that_are_not_an_object_are_refused(tmp_path: Path) -> None:
    request = request_for(new_dir(tmp_path))
    hostile: list[object] = [[], "texto", 1800, None]
    for data in hostile:
        with pytest.raises(DomainError) as error:
            read_parameters(write_parameters(tmp_path, data), request.case)
        assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_a_parameters_file_that_is_a_link_is_not_followed(tmp_path: Path) -> None:
    request = request_for(new_dir(tmp_path))
    real = write_parameters(tmp_path, parameters_data())
    link = tmp_path / "enlace.json"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(DomainError) as error:
        read_parameters(link, request.case)
    assert error.value.code == ErrorCode.PATH_NOT_ALLOWED


# --- programa vigente ---------------------------------------------------------------------------


def test_a_current_program_changed_after_publishing_is_noticed(tmp_path: Path) -> None:
    request = request_for(new_dir(tmp_path))
    program = request.program_dir
    tramos = program / "tramos.json"
    tramos.chmod(stat.S_IWRITE)
    data = json.loads(tramos.read_text(encoding="utf-8"))
    data["slots"][0]["duration_s"] += 1
    tramos.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TrazabilidadError) as error:
        compute_comparators(prepare(request.case), request.scenario, parameters(), program)
    assert error.value.code == ErrorCode.HASH_MISMATCH


# --- comparadores publicados --------------------------------------------------------------------


def test_a_deeply_nested_comparators_file_is_refused_without_crashing(tmp_path: Path) -> None:
    folder = published(tmp_path)
    depth = 100_000
    forge(folder, COMPARATORS_FILE, b"[" * depth + b"]" * depth)
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


def test_a_comparators_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    folder = published(tmp_path)
    forge(folder, COMPARATORS_FILE, b"\xff\xfe no es json")
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code == ErrorCode.INPUT_SCHEMA


@pytest.mark.parametrize("name", ["../fuera.json", "..\\fuera.json", "C:/x.json", "/x.json"])
def test_a_manifest_that_names_a_file_outside_the_folder_is_refused(
    tmp_path: Path, name: str
) -> None:
    folder = published(tmp_path)
    (tmp_path / "datos" / "fuera.json").write_text("{}", encoding="utf-8")
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = sha256_bytes(b"{}")
    manifest_path.chmod(stat.S_IWRITE)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(TrazabilidadError):
        read_comparators(folder)


def test_a_link_inside_the_comparators_folder_is_not_followed(tmp_path: Path) -> None:
    folder = published(tmp_path)
    outside = tmp_path / "fuera.json"
    outside.write_text("{}", encoding="utf-8")
    target = folder / COMPARATORS_FILE
    content = target.read_bytes()
    target.chmod(stat.S_IWRITE)
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        target.write_bytes(content)
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(folder)
    assert error.value.code in {ErrorCode.PATH_NOT_ALLOWED, ErrorCode.HASH_MISMATCH}


def test_a_comparators_folder_that_is_a_link_is_not_followed(tmp_path: Path) -> None:
    folder = published(tmp_path)
    link = tmp_path / "enlace"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    with pytest.raises(TrazabilidadError) as error:
        read_comparators(link)
    assert error.value.code == ErrorCode.PATH_NOT_ALLOWED


def test_a_published_folder_is_read_only(tmp_path: Path) -> None:
    folder = published(tmp_path)
    for item in folder.iterdir():
        assert not os.access(item, os.W_OK), item.name
