"""El modelo del caso sigue el contrato publicado ``schemas/case.schema.json`` (DEV02, F3).

El contrato lo genera el modelo de referencia de la documentación. La comparación ignora solo los
textos de documentación (``description``, el título y ``$schema``): cualquier cambio de campos,
tipos, obligatorios, valores permitidos o límites hace fallar la prueba.
"""

import json
from pathlib import Path

from semaforo.dominio.case import Case

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas" / "case.schema.json"
DOCUMENTATION_KEYS = frozenset({"description", "title", "$schema"})

type Json = dict[str, Json] | list[Json] | str | int | float | bool | None


def without_documentation(node: Json) -> Json:
    """El esquema sin textos de documentación; el resto se compara tal cual."""
    if isinstance(node, dict):
        return {
            key: without_documentation(value)
            for key, value in node.items()
            if key not in DOCUMENTATION_KEYS
        }
    if isinstance(node, list):
        return [without_documentation(item) for item in node]
    return node


def test_the_model_has_the_published_contract_structure() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert without_documentation(Case.model_json_schema()) == without_documentation(published)


def test_the_published_contract_names_the_same_required_fields() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(Case.model_json_schema()["required"]) == set(published["required"])


def test_the_published_contract_keeps_the_version_fixed_to_1_0_0() -> None:
    published = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert published["properties"]["schema_version"] == {
        "const": "1.0.0",
        "default": "1.0.0",
        "title": "Schema Version",
        "type": "string",
    }
