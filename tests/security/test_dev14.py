"""Seguridad de las etiquetas de la búsqueda (DEV14 F4, HU08).

Una carpeta de etiqueta se lee como no confiable: se prueba que los nombres con rutas no sacan nada
de la carpeta de trabajo, que los enlaces no se siguen, que un manifiesto o una etiqueta hostil se
rechaza sin tumbar el programa ni leer sin límite, y que no se puede falsificar una referencia
cambiando la etiqueta y su manifiesto a la vez. Datos sintéticos, sin SUMO.
"""

import json
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from search_tools import Search, new_search, outcome_for, reference_outcome
from semaforo.dominio.errors import ErrorCode
from semaforo.referencias.errors import ReferenciasError
from semaforo.referencias.label import (
    LABEL_FILE,
    MANIFEST_FILE,
    MAX_LABEL_BYTES,
    publish_label,
    read_label,
)
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import TrazabilidadError


def published(tmp_path: Path, *, reference: bool = True) -> Path:
    search = new_search(tmp_path)
    outcome = (
        reference_outcome(search)
        if reference
        else outcome_for(search, search_clean=True, finalists_clean=False)
    )
    return publish_label(tmp_path / "datos", search.setup, outcome)


def rewrite(folder: Path, name: str, data: bytes) -> None:
    """Cambia un archivo y pone su nueva huella en el manifiesto (un ataque que lo sabe todo)."""
    path = folder / name
    path.chmod(stat.S_IWRITE)
    path.write_bytes(data)
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = sha256_bytes(data)
    manifest_path.chmod(stat.S_IWRITE)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def code_of(folder: Path) -> ErrorCode:
    with pytest.raises(TrazabilidadError) as error:
        read_label(folder)
    return error.value.code


@pytest.mark.parametrize("case_id", ["../fuera", "a/b", "a\\b", "C:x", ".oculto", ""])
def test_a_case_name_with_a_path_cannot_become_a_label_folder(tmp_path: Path, case_id: str) -> None:
    search = new_search(tmp_path)
    case = search.setup.case.model_copy(update={"case_id": case_id})
    hostile = Search(replace(search.setup, case=case), search.candidates, search.journal)
    with pytest.raises(ReferenciasError) as error:
        publish_label(tmp_path / "datos", hostile.setup, reference_outcome(hostile))
    assert error.value.code == ErrorCode.PATH_NOT_ALLOWED
    assert not (tmp_path / "datos").exists()
    assert not (tmp_path / "fuera").exists()


def test_the_published_files_are_read_only(tmp_path: Path) -> None:
    folder = published(tmp_path)
    files = [path for path in folder.iterdir() if path.is_file()]
    assert len(files) == 4
    assert not any(os.access(path, os.W_OK) for path in files)


@pytest.mark.parametrize("name", ["../fuera.json", "/absoluta.json", "C:/x.json", "a/../../b"])
def test_a_manifest_naming_a_path_outside_the_folder_is_rejected(tmp_path: Path, name: str) -> None:
    folder = published(tmp_path)
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = "0" * 64
    manifest_path.chmod(stat.S_IWRITE)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert code_of(folder) == ErrorCode.PATH_NOT_ALLOWED


def test_a_label_folder_that_is_a_link_is_not_followed(tmp_path: Path) -> None:
    folder = published(tmp_path)
    link = tmp_path / "enlace"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos")
    assert code_of(link) == ErrorCode.PATH_NOT_ALLOWED


def test_a_label_over_the_size_limit_is_rejected_before_parsing(tmp_path: Path) -> None:
    folder = published(tmp_path)
    valid = (folder / LABEL_FILE).read_bytes()
    rewrite(folder, LABEL_FILE, valid + b" " * MAX_LABEL_BYTES)  # válida, pero pasa el límite
    assert code_of(folder) == ErrorCode.INPUT_SCHEMA


@pytest.mark.parametrize(
    "data",
    [b"[" * 100_000, b"\xff\xfe{}", b"", b"null", b'{"status": "reference"}'],
    ids=["anidada", "no-utf8", "vacia", "null", "incompleta"],
)
def test_a_hostile_label_is_rejected_with_a_domain_error(tmp_path: Path, data: bytes) -> None:
    folder = published(tmp_path)
    rewrite(folder, LABEL_FILE, data)
    assert code_of(folder) == ErrorCode.INPUT_SCHEMA


def test_a_no_reference_cannot_be_forged_into_a_reference(tmp_path: Path) -> None:
    folder = published(tmp_path, reference=False)
    label = json.loads((folder / LABEL_FILE).read_text(encoding="utf-8"))
    label["status"] = "reference"
    rewrite(folder, LABEL_FILE, json.dumps(label).encode("utf-8"))
    manifest_path = folder / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "reference"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert code_of(folder) == ErrorCode.INPUT_SCHEMA


def test_a_label_cannot_be_republished_over_an_existing_one(tmp_path: Path) -> None:
    folder = published(tmp_path)
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    other = tmp_path / "otra"
    other.mkdir()
    search = new_search(other)
    with pytest.raises(ReferenciasError):
        publish_label(
            tmp_path / "datos",
            search.setup,
            reference_outcome(search),
            now=read_label(folder).manifest.created_at,
        )
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before
