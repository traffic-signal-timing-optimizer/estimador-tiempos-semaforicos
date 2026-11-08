"""Las columnas de las vistas que muestra el gráfico son las que crea el esquema (DEV31 F7)."""

import json
from pathlib import Path

import pytest

from semaforo.bd.conexion import ADMIN, connect

pytestmark = pytest.mark.bd

DOCUMENTED = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "arquitectura"
    / "diagramas"
    / "vistas_columnas.json"
)


def test_the_documented_view_columns_match_a_new_base(base: str) -> None:
    with connect(ADMIN, database=base) as connection:
        rows = connection.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'vistas' ORDER BY table_name, ordinal_position"
        ).fetchall()
    found: dict[str, list[list[str]]] = {}
    for table, column, kind in rows:
        found.setdefault(str(table), []).append([str(column), str(kind)])
    assert found == json.loads(DOCUMENTED.read_text(encoding="utf-8"))
