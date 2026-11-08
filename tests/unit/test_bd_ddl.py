"""El SQL de la base sale del diseño y está al día (DEV31 F3)."""

import dataclasses
import re
import subprocess
import sys
from pathlib import Path

import pytest

from semaforo.bd import ddl
from semaforo.bd.diseno import Design, load, verify
from semaforo.bd.esquema import SQL_FILES, schema_sql, schema_version

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "bd" / "esquema.toml"


@pytest.fixture(scope="module")
def design() -> Design:
    return load(SCHEMA)


def test_the_published_sql_and_dictionary_are_up_to_date() -> None:
    result = subprocess.run(  # noqa: S603  (el Python del proyecto con un guion del repositorio)
        [sys.executable, str(ROOT / "scripts" / "bd_esquema.py"), "--comprobar"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout


def test_every_table_and_column_of_the_design_is_created(design: Design) -> None:
    text = ddl.tables_sql(design)
    tables = re.findall(r"^CREATE TABLE (\S+) \(", text, flags=re.MULTILINE)
    assert sorted(tables) == sorted(t.full for t in design.tablas)
    assert len(tables) == 57
    for table in design.tablas:
        for column in table.columnas:
            assert f"COMMENT ON COLUMN {table.full}.{column.nombre} IS" in text


def test_every_relation_of_the_design_is_a_foreign_key(design: Design) -> None:
    text = ddl.tables_sql(design)
    keys = sum(len(t.claves_foraneas) for t in design.tablas)
    # C2 añade dos enlaces de archivo y fija la selección en el hito y el experimento.
    assert text.count(" FOREIGN KEY (") == keys == 227


def test_only_the_partition_link_is_deferred(design: Design) -> None:
    deferred = [line for line in ddl.tables_sql(design).splitlines() if "DEFERRABLE" in line]
    assert len(deferred) == 1
    assert "experimento.asignaciones" in deferred[0]
    assert "experimento.escenarios" in deferred[0]


def test_every_table_rejects_changes_and_every_blinded_one_has_its_two_policies(
    design: Design,
) -> None:
    text = ddl.security_sql(design)
    for table in design.tablas:
        assert f"BEFORE UPDATE OR DELETE ON {table.full} " in text
        assert f"BEFORE TRUNCATE ON {table.full} " in text
        blinded = table.cegado != "no"
        assert (f"ALTER TABLE {table.full} ENABLE ROW LEVEL SECURITY;" in text) == blinded
        assert (f"CREATE POLICY lectura_cegada ON {table.full} " in text) == blinded


def test_a_child_inherits_the_visibility_of_its_parent(design: Design) -> None:
    vehicles = design.table("simulacion.vehiculos")
    assert vehicles is not None
    condition = ddl.blinding_expression(vehicles)
    assert condition == (
        "EXISTS (SELECT 1 FROM simulacion.corridas AS padre WHERE padre.run_id = vehiculos.run_id)"
    )
    differences = design.table("evaluacion.diferencias")
    assert differences is not None
    condition = str(ddl.blinding_expression(differences))
    assert "a.comparacion_id = diferencias.comparacion_a_id" in condition
    assert "b.comparacion_id = diferencias.comparacion_b_id" in condition


def test_a_scenario_table_hides_the_rows_of_a_closed_test(design: Design) -> None:
    scenarios = design.table("experimento.escenarios")
    assert scenarios is not None
    assert "control.escenarios_cegados" in str(ddl.blinding_expression(scenarios))
    queries = design.table("aprendizaje.consultas")
    assert queries is not None
    assert str(ddl.blinding_expression(queries)).startswith("consultas.escenario_id IS NULL OR ")
    unblinded = design.table("control.cargas")
    assert unblinded is not None
    assert ddl.blinding_expression(unblinded) is None


def test_the_loader_may_only_update_the_two_declared_exceptions(design: Design) -> None:
    text = ddl.security_sql(design)
    updates = [line for line in text.splitlines() if line.startswith("GRANT UPDATE")]
    assert updates == ["GRANT UPDATE ON control.cargas, control.conflictos TO semaforo_carga;"]
    assert "GRANT SELECT, INSERT ON ALL TABLES" in text
    assert "semaforo_lectura" not in text.split("GRANT SELECT, INSERT")[1].split(";")[0]


def test_a_name_that_is_not_a_simple_identifier_never_reaches_the_sql(design: Design) -> None:
    first = design.tablas[0]
    bad = dataclasses.replace(first, nombre="cargas; DROP TABLE x")
    broken = dataclasses.replace(design, tablas=(bad, *design.tablas[1:]))
    with pytest.raises(ValueError, match="identificadores simples"):
        ddl.tables_sql(broken)
    with pytest.raises(ValueError, match="identificadores simples"):
        ddl.security_sql(broken)


def test_the_design_still_verifies_against_its_catalog(design: Design) -> None:
    approved = {t.nombre for t in design.tablas}
    assert verify(design, approved) == []


def test_the_schema_version_changes_with_any_of_its_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = schema_sql()
    assert [name for name, _ in files] == list(SQL_FILES)
    before = schema_version()
    changed = [
        (name, text + ("\n-- otro" if name == "02_reglas.sql" else "")) for name, text in files
    ]
    monkeypatch.setattr("semaforo.bd.esquema.schema_sql", lambda: changed)
    assert schema_version() != before
    assert re.fullmatch(r"sql-[0-9a-f]{16}", before)
