"""Comprueba que los contratos JSON están en schemas/ y son JSON Schema 2020-12 válidos."""

import json
from pathlib import Path

import pytest

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
CONTRATOS = [
    "case",
    "label",
    "model_manifest",
    "protocol",
    "request",
    "response",
    "run_manifest",
    "scenario",
    "split",
]


def test_hay_nueve_contratos() -> None:
    encontrados = sorted(p.name for p in SCHEMAS.glob("*.schema.json"))
    esperados = sorted(f"{c}.schema.json" for c in CONTRATOS)
    assert encontrados == esperados


@pytest.mark.parametrize("nombre", CONTRATOS)
def test_contrato_es_json_schema_2020_12(nombre: str) -> None:
    esquema = json.loads((SCHEMAS / f"{nombre}.schema.json").read_text(encoding="utf-8"))
    assert esquema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert esquema["title"].startswith(f"Contrato {nombre} ")
