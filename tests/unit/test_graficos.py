"""Los gráficos de la arquitectura salen del esquema y del código, y no se quedan viejos (DEV31 F7).

El archivo de draw.io se comprueba por su estructura. Que se abra bien en draw.io es una revisión
manual: esta prueba no lo ejecuta.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from defusedxml import ElementTree

from semaforo.bd.diseno import Design, load

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "graficos.py"
FOLDER = ROOT / "docs" / "arquitectura"
IMAGES = FOLDER / "diagramas"
EDITABLE = IMAGES / "BD00_modelo_completo.drawio"
DOCUMENTS = ("arquitectura-tecnica.md", "arquitectura-de-solucion.md", "modelo-de-datos.md")
TIMEOUT_S = 300


def _check(folder: Path) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(  # noqa: S603  (el Python del proyecto con un guion del repositorio)
        [sys.executable, "-B", str(SCRIPT), "--comprobar", "--carpeta", str(folder)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=TIMEOUT_S,
        cwd=ROOT,
    )


def _design() -> Design:
    return load(ROOT / "docs" / "bd" / "esquema.toml")


def _cells() -> list[dict[str, str]]:
    root = ElementTree.parse(EDITABLE).getroot()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    assert root is not None
    return [dict(cell.attrib) for cell in root.iter("mxCell")]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportUnknownArgumentType]


def test_the_images_and_the_editable_file_match_the_schema_and_the_code() -> None:
    result = _check(IMAGES)
    assert result.returncode == 0, result.stderr


def test_a_changed_editable_file_is_reported_as_out_of_date(tmp_path: Path) -> None:
    """Sin esto, la prueba anterior podría pasar sin comprobar nada."""
    for file in IMAGES.iterdir():
        shutil.copy2(file, tmp_path / file.name)
    copy = tmp_path / EDITABLE.name
    copy.write_text(copy.read_text(encoding="utf-8").replace("run_id", "corrida"), encoding="utf-8")
    result = _check(tmp_path)
    assert result.returncode == 1
    assert EDITABLE.name in result.stderr


def test_the_editable_file_has_every_table_and_every_column_once() -> None:
    design = _design()
    identifiers = [cell["id"] for cell in _cells()]
    assert len(identifiers) == len(set(identifiers))
    tables = {f"t:{t.esquema}.{t.nombre}" for t in design.tablas}
    columns = {f"c:{t.esquema}.{t.nombre}.{c.nombre}" for t in design.tablas for c in t.columnas}
    assert {i for i in identifiers if i.startswith("t:")} == tables
    assert {i for i in identifiers if i.startswith("c:")} == columns


def test_every_line_joins_two_columns_that_exist() -> None:
    cells = _cells()
    identifiers = {cell["id"] for cell in cells}
    lines = [cell for cell in cells if cell.get("edge") == "1"]
    expected = sum(1 for t in _design().tablas for k in t.claves_foraneas if not k.comun)
    assert len(lines) == expected
    for line in lines:
        assert line["source"] in identifiers
        assert line["target"] in identifiers


def test_each_column_row_hangs_from_its_own_table() -> None:
    for cell in _cells():
        if cell["id"].startswith("c:"):
            schema_table = ".".join(cell["id"][2:].split(".")[:2])
            assert cell["parent"] == f"t:{schema_table}"


def test_the_data_model_document_names_every_table_and_view() -> None:
    text = (FOLDER / "modelo-de-datos.md").read_text(encoding="utf-8")
    design = _design()
    for table in design.tablas:
        assert f"`{table.nombre}`" in text, table.nombre
    for view, _, _ in design.vistas:
        assert f"`{view.split('.')[1]}`" in text, view


@pytest.mark.parametrize("name", DOCUMENTS)
def test_every_image_a_document_cites_exists(name: str) -> None:
    text = (FOLDER / name).read_text(encoding="utf-8")
    cited = re.findall(r"\]\((diagramas/[^)]+)\)", text)
    assert cited
    for path in cited:
        assert (FOLDER / path).is_file(), path


def test_no_image_is_left_without_a_document() -> None:
    text = "".join((FOLDER / name).read_text(encoding="utf-8") for name in DOCUMENTS)
    for image in IMAGES.glob("*.png"):
        assert f"diagramas/{image.name}" in text, image.name
