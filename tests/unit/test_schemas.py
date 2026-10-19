"""Comprueba que los contratos JSON están en schemas/ y son JSON Schema 2020-12 válidos."""

import json
from pathlib import Path

import pytest

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
CONTRACTS = [
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


def test_there_are_nine_contracts() -> None:
    found = sorted(p.name for p in SCHEMAS.glob("*.schema.json"))
    expected = sorted(f"{name}.schema.json" for name in CONTRACTS)
    assert found == expected


@pytest.mark.parametrize("name", CONTRACTS)
def test_contract_is_json_schema_2020_12(name: str) -> None:
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"].startswith(f"Contrato {name} ")
