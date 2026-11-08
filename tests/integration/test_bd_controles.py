"""Los controles de la base (DEV31 F4c): reglas instaladas, lectura estable y referencia de git.

Cada prueba repite el escenario de una observación de la auditoría (N3, N6, B06, B07).
"""

import json
from pathlib import Path

import pytest

from bd_tools import scalar
from semaforo.app.bd_commands import regenerate, verify
from semaforo.bd.candado import try_exclusive
from semaforo.bd.carga.motor import LoadOptions, load_workspace
from semaforo.bd.conciliacion import reconcile
from semaforo.bd.conexion import ADMIN, CARGA, LECTURA, ROLES, BdError, connect
from semaforo.bd.instantanea import Inconcluso, lectura_estable
from semaforo.bd.reglas import RULES_ALGORITHM, rules_digest
from semaforo.bd.temporales import create_database, drop_database

pytestmark = pytest.mark.bd


def _rules(database: str) -> str:
    with connect(CARGA, database=database, autocommit=True) as connection:
        return rules_digest(connection)[0]


def _admin(database: str, *statements: str) -> None:
    with connect(ADMIN, database=database, autocommit=True) as connection:
        for statement in statements:
            connection.execute(statement.encode())


def _running_load(database: str) -> None:
    """Una carga que figura «en curso» (la deja así una carga que se cayó sin cerrarse)."""
    _admin(
        database,
        "INSERT INTO control.cargas (carga_id, inicio, estado, comando, version_paquete, "
        "version_postgres, version_esquema) VALUES ('en-curso', now(), 'running', '{}'::jsonb, "
        "'prueba', 'prueba', 'prueba')",
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    folder = tmp_path / "datos"
    folder.mkdir()
    return folder


# --- reglas instaladas (C1.10; N3) ------------------------------------------------------------


def test_two_databases_with_the_same_schema_have_the_same_rules_fingerprint(
    base: str, bd_plantilla: str
) -> None:
    other = create_database(template=bd_plantilla)
    try:
        assert _rules(base) == _rules(other)
        assert _rules(base) == _rules(base)
    finally:
        drop_database(other)


def test_turning_off_a_trigger_without_touching_a_row_changes_the_fingerprint(base: str) -> None:
    before = _rules(base)
    rows = scalar(base, "SELECT count(*) FROM control.cargas")
    _admin(base, "ALTER TABLE simulacion.corridas DISABLE TRIGGER solo_agregar")
    assert scalar(base, "SELECT count(*) FROM control.cargas") == rows  # ninguna fila cambió
    assert _rules(base) != before
    _admin(base, "ALTER TABLE simulacion.corridas ENABLE TRIGGER solo_agregar")
    assert _rules(base) == before


def test_changing_a_policy_a_permission_a_function_or_an_index_changes_the_fingerprint(
    base: str,
) -> None:
    before = _rules(base)
    changes = (
        (
            "ALTER POLICY lectura_cegada ON simulacion.corridas USING (true)",
            "ALTER POLICY lectura_cegada ON simulacion.corridas USING (NOT EXISTS "
            "(SELECT 1 FROM control.escenarios_cegados AS cegado "
            "WHERE cegado.escenario_id = corridas.escenario_id))",
        ),
        (
            "GRANT UPDATE ON simulacion.corridas TO semaforo_lectura",
            "REVOKE UPDATE ON simulacion.corridas FROM semaforo_lectura",
        ),
        (
            "ALTER TABLE simulacion.corridas DISABLE ROW LEVEL SECURITY",
            "ALTER TABLE simulacion.corridas ENABLE ROW LEVEL SECURITY",
        ),
        (
            "DROP INDEX control.hitos_un_protocolo",
            "CREATE UNIQUE INDEX hitos_un_protocolo ON control.hitos (protocolo_id) "
            "WHERE tipo = 'protocol_frozen'",
        ),
        (
            "ALTER TABLE simulacion.cola_por_acceso DROP CONSTRAINT cola_por_acceso_pk",
            "ALTER TABLE simulacion.cola_por_acceso ADD CONSTRAINT cola_por_acceso_pk "
            "PRIMARY KEY (run_id, acceso)",
        ),
    )
    for change, undo in changes:
        _admin(base, change)
        assert _rules(base) != before, change
        _admin(base, undo)
        assert _rules(base) == before, undo


def test_the_rules_fingerprint_also_watches_the_panel_user(base: str) -> None:
    with connect(ADMIN, database=base, autocommit=True) as connection:
        before = rules_digest(connection)[1]["usuarios del proyecto"]
    assert before == len(ROLES)
    assert "semaforo_panel" in ROLES


# --- verificación contra la referencia (C1.6; B06) --------------------------------------------


def _write_reference(workspace: Path, base: str, where: Path) -> dict[str, object]:
    report = verify(workspace, None, compare=False, fingerprints=where, database=base)
    assert report.status == "intact"
    loaded = json.loads(where.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded  # pyright: ignore[reportUnknownVariableType]


def test_the_base_coincides_with_the_reference_it_wrote_and_names_the_algorithms(
    base: str, workspace: Path, tmp_path: Path
) -> None:
    reference = tmp_path / "huellas.json"
    written = _write_reference(workspace, base, reference)
    assert written["algoritmo_reglas"] == RULES_ALGORITHM
    assert written["algoritmo_huella"]
    report = verify(workspace, None, reference=reference, database=base)
    assert (report.status, report.reference and report.reference.outcome) == ("intact", "coincide")


def test_a_trigger_turned_off_without_touching_data_makes_the_verification_fail(
    base: str, workspace: Path, tmp_path: Path
) -> None:
    reference = tmp_path / "huellas.json"
    _write_reference(workspace, base, reference)
    _admin(base, "ALTER TABLE control.hitos DISABLE TRIGGER validar_hito")
    report = verify(workspace, None, reference=reference, database=base)
    assert report.status == "changed"
    assert report.reference is not None
    assert [d.item for d in report.reference.differences] == ["reglas instaladas"]
    assert (
        report.content_sha256 == json.loads(reference.read_text(encoding="utf-8"))["content_sha256"]
    )


def test_a_reference_of_another_schema_or_algorithm_is_inconclusive_not_different(
    base: str, workspace: Path, tmp_path: Path
) -> None:
    reference = tmp_path / "huellas.json"
    written = _write_reference(workspace, base, reference)
    for field, value, word in (
        ("schema_version_db", "sql-de-otra-version", "otra versión del esquema"),
        ("algoritmo_huella", "contenido-9", "algoritmo distinto"),
    ):
        reference.write_text(json.dumps({**written, field: value}), encoding="utf-8")
        report = verify(workspace, None, reference=reference, database=base)
        assert report.status == "inconclusive"
        assert word in str(report.reason)
        assert report.reference is not None and report.reference.outcome == "no_concluyente"


def test_without_a_usable_reference_the_result_is_inconclusive(
    base: str, workspace: Path, tmp_path: Path
) -> None:
    assert verify(workspace, None, database=base).status == "inconclusive"
    missing = tmp_path / "no-existe.json"
    assert verify(workspace, None, reference=missing, database=base).status == "inconclusive"
    broken = tmp_path / "roto.json"
    broken.write_text("{no es json", encoding="utf-8")
    assert verify(workspace, None, reference=broken, database=base).status == "inconclusive"


# --- lectura estable y candado (C1.6, C1.7; N6) ----------------------------------------------


def test_a_verification_or_reconciliation_does_not_run_while_a_load_holds_the_lock(
    base: str, workspace: Path
) -> None:
    with connect(CARGA, database=base, autocommit=True) as loading:
        assert try_exclusive(loading)
        report = verify(workspace, None, compare=False, database=base)
        assert report.status == "inconclusive"
        assert "carga en curso" in str(report.reason)
        compared = reconcile(workspace, database=base)
        assert compared.status == "inconclusive"
        assert "carga en curso" in str(compared.reason)
        assert regenerate(workspace, None, database=base).status == "inconclusive"


def test_a_load_does_not_start_while_something_is_reading(base: str, workspace: Path) -> None:
    with lectura_estable(CARGA, database=base):
        with pytest.raises(BdError, match="candado ocupado"):
            load_workspace(workspace, LoadOptions(), database=base)
    assert load_workspace(workspace, LoadOptions(), database=base).status == "completed"


def test_two_readings_can_run_at_the_same_time(base: str) -> None:
    with lectura_estable(CARGA, database=base) as first, lectura_estable(LECTURA, database=base):
        assert first.carga_id is None


def test_a_load_recorded_while_reading_makes_the_result_inconclusive(base: str) -> None:
    with lectura_estable(CARGA, database=base) as reading:
        _running_load(base)
    assert reading.cambio is not None
    assert "cambió" in reading.cambio


def test_loads_that_appear_in_progress_without_a_process_are_inconclusive(
    base: str, workspace: Path
) -> None:
    _running_load(base)
    with pytest.raises(Inconcluso, match="running"), lectura_estable(CARGA, database=base):
        pass
    report = verify(workspace, None, compare=False, database=base)
    assert report.status == "inconclusive"
    assert "running" in str(report.reason)
