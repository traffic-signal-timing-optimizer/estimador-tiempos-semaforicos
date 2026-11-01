"""Comprobación de una carpeta de entradas antes de ejecutarla (DEV07 F1, decisión D2)."""

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from prepared_inputs import MOMENT, request_for
from semaforo.caso.errors import CasoError
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.prepare import CONFIG_FILE, MANIFEST_FILE, InputsManifest, publish_inputs
from semaforo.simulacion.run_inputs import verify_inputs
from semaforo.simulacion.runner import SimulacionError


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return publish_inputs(tmp_path / "entradas", request_for(tmp_path), MOMENT)


@pytest.fixture
def editable(folder: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "copia"
    shutil.copytree(folder, copy)
    for item in copy.iterdir():
        item.chmod(0o666)
    return copy


def change_manifest(folder: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = folder / MANIFEST_FILE
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def rewrite_config(folder: Path, old: str, new: str) -> None:
    """Cambia la configuración y pone su huella nueva en el manifiesto."""
    path = folder / CONFIG_FILE
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    data = text.replace(old, new).encode("utf-8")
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    change_manifest(folder, lambda manifest: manifest["files"].update({CONFIG_FILE: digest}))


def refused(folder: Path, code: ErrorCode, message: str) -> None:
    with pytest.raises(SimulacionError, match=message) as error:
        verify_inputs(folder)
    assert error.value.code is code


def test_a_published_folder_passes_and_gives_its_manifest(folder: Path) -> None:
    manifest = verify_inputs(folder)
    expected = InputsManifest.model_validate_json((folder / MANIFEST_FILE).read_bytes())
    assert manifest == expected
    assert manifest.times.end_s == 1860


def test_a_folder_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    refused(tmp_path / "no", ErrorCode.INPUT_SCHEMA, "no existe la carpeta")


def test_a_file_instead_of_a_folder_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "archivo"
    path.write_text("x", encoding="utf-8")
    refused(path, ErrorCode.INPUT_SCHEMA, "no existe la carpeta")


def test_a_folder_that_is_a_link_is_refused(folder: Path, tmp_path: Path) -> None:
    link = tmp_path / "enlace"
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    refused(link, ErrorCode.PATH_NOT_ALLOWED, "enlace")


def test_a_missing_manifest_is_refused(editable: Path) -> None:
    (editable / MANIFEST_FILE).unlink()
    with pytest.raises(CasoError, match="manifiesto"):
        verify_inputs(editable)


def test_a_broken_manifest_is_refused(editable: Path) -> None:
    change_manifest(editable, lambda manifest: manifest.pop("times"))
    refused(editable, ErrorCode.INPUT_SCHEMA, "manifiesto de las entradas no es válido")


# --- archivos de la carpeta -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["cohorte.csv", "demanda.rou.xml", CONFIG_FILE, "red.net.xml"])
def test_a_changed_file_is_refused(editable: Path, name: str) -> None:
    with (editable / name).open("ab") as handle:
        handle.write(b"\n")
    refused(editable, ErrorCode.HASH_MISMATCH, f"fue alterada: {name}")


def test_an_extra_file_is_refused(editable: Path) -> None:
    (editable / "sobra.txt").write_text("x", encoding="utf-8")
    refused(editable, ErrorCode.HASH_MISMATCH, "sobra sobra.txt")


def test_a_missing_file_is_refused(editable: Path) -> None:
    (editable / "programa.tll.xml").unlink()
    refused(editable, ErrorCode.HASH_MISMATCH, "falta programa.tll.xml")


def test_a_subfolder_is_refused(editable: Path) -> None:
    (editable / "otra").mkdir()
    refused(editable, ErrorCode.PATH_NOT_ALLOWED, "sin enlaces ni subcarpetas")


def test_a_file_that_is_a_link_is_refused(editable: Path, tmp_path: Path) -> None:
    target = tmp_path / "fuera.csv"
    (editable / "cohorte.csv").rename(target)
    try:
        (editable / "cohorte.csv").symlink_to(target)
    except OSError:
        pytest.skip("este equipo no permite crear enlaces simbólicos sin privilegios")
    refused(editable, ErrorCode.PATH_NOT_ALLOWED, "sin enlaces")


# --- configuración frente al manifiesto -----------------------------------------------------


@pytest.mark.parametrize(
    ("section", "key", "value", "option"),
    [
        ("times", "end_s", 900.0, "end"),
        ("times", "begin_s", 5.0, "begin"),
        ("times", "step_length_s", 0.5, "step-length"),
        ("seeds", "sumo_seed", 7, "seed"),
    ],
)
def test_a_manifest_that_disagrees_with_the_config_is_refused(
    editable: Path, section: str, key: str, value: float, option: str
) -> None:
    change_manifest(editable, lambda manifest: manifest[section].update({key: value}))
    refused(editable, ErrorCode.HASH_MISMATCH, f"dice {option}=")


@pytest.mark.parametrize(
    ("old", "new", "option"),
    [
        ('<net-file value="red.net.xml"', '<net-file value="otra.net.xml"', "net-file"),
        (
            '<route-files value="demanda.rou.xml"',
            '<route-files value="otra.rou.xml"',
            "route-files",
        ),
        (
            '<additional-files value="programa.tll.xml"',
            '<additional-files value="otro.xml"',
            "additional-files",
        ),
        ('<end value="1860"', '<end value="99"', "end"),
        ('<end value="1860"', '<end value="pronto"', "end"),
        ('<seed value="100"', '<seed value="101"', "seed"),
    ],
)
def test_a_config_that_disagrees_with_the_manifest_is_refused(
    editable: Path, old: str, new: str, option: str
) -> None:
    rewrite_config(editable, old, new)
    refused(editable, ErrorCode.HASH_MISMATCH, f"dice {option}=")


def test_a_config_without_end_is_refused(editable: Path) -> None:
    rewrite_config(editable, '<end value="1860" />', "")
    refused(editable, ErrorCode.HASH_MISMATCH, "no declara end")


def test_the_check_does_not_change_the_folder(folder: Path) -> None:
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    verify_inputs(folder)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


@pytest.mark.parametrize(
    "entry", ["../../fuera.sumocfg", "otro.sumocfg", "subdir/escenario.sumocfg"]
)
def test_a_manifest_that_points_elsewhere_for_the_config_is_refused(
    editable: Path, entry: str
) -> None:
    change_manifest(editable, lambda manifest: manifest.update({"entry_config": entry}))
    refused(editable, ErrorCode.PATH_NOT_ALLOWED, "no es la de la carpeta de entradas")
