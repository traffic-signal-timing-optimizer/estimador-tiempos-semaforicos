"""Cobertura en los dos sentidos y decisiones sobre archivos excluidos (DEV31 F4c, C1.3 a C1.5).

Escenarios de la auditoría: B01 (una base vacía no puede salir «coincide»), N5 (un conflicto ya
decidido no vuelve a abrirse) y la exclusión de las corridas de DEV00, que debe sobrevivir a una
reconstrucción sin cubrir un archivo que después cambió.
"""

import subprocess
from pathlib import Path

import pytest

from bd_tools import scalar
from semaforo.app.bd_commands import load_exit_code, reconcile_exit_code, register_decision
from semaforo.bd.carga.motor import LoadOptions, LoadReport, load_workspace
from semaforo.bd.conciliacion import reconcile
from semaforo.bd.conexion import BdError
from semaforo.bd.temporales import create_database, drop_database
from workspace_tools import build_workspace

pytestmark = pytest.mark.bd

ACTA = "docs/actas/decision.md"


def _repository(tmp_path: Path) -> Path:
    """Un repositorio git con un acta confirmada."""
    repository = tmp_path / "repo"
    (repository / "docs" / "actas").mkdir(parents=True)
    (repository / ACTA).write_bytes(b"Acta de la decision de prueba.\n")
    git = ["git", "-c", "user.name=prueba", "-c", "user.email=prueba@example.com", "-C"]
    for arguments in (["init", "-q"], ["add", ACTA], ["commit", "-q", "-m", "acta"]):
        subprocess.run([*git, str(repository), *arguments], check=True, capture_output=True)  # noqa: S603
    return repository


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return build_workspace(tmp_path)[0]


def _case_file(workspace: Path) -> tuple[Path, str]:
    folder = next((workspace / "casos").iterdir())
    return folder / "case.json", f"casos/{folder.name}/case.json"


def _load(workspace: Path, base: str, repository: Path | None = None) -> LoadReport:
    return load_workspace(workspace, LoadOptions(repository=repository), database=base)


def _outcome(report: LoadReport, kind: str) -> str:
    return next(unit.status for unit in report.units if unit.kind == kind)


def _decide(workspace: Path, repository: Path, base: str, path: str) -> str:
    decision_id, report = register_decision(
        workspace,
        repository,
        path=path,
        decision="accepted_risk",
        reason="Archivo de prueba que no se puede cargar.",
        acta=ACTA,
        responsible="PO",
        database=base,
    )
    assert load_exit_code(report) == 0
    return decision_id


def test_an_empty_base_is_incomplete_never_equal(base: str, workspace: Path) -> None:
    report = reconcile(workspace, database=base)
    assert report.status == "incomplete"
    assert reconcile_exit_code(report) == 5
    assert (report.coverage.expected, report.coverage.missing, report.coverage.loaded) == (1, 1, 0)
    assert report.coverage.missing_keys[0].startswith("caso:")
    assert (report.files_checked, report.runs_checked, report.differences_total) == (0, 0, 0)


def test_what_is_loaded_coincides_and_the_coverage_counts_it(base: str, workspace: Path) -> None:
    assert load_exit_code(_load(workspace, base)) == 0
    report = reconcile(workspace, database=base)
    assert (report.status, reconcile_exit_code(report)) == ("equal", 0)
    assert (report.coverage.loaded, report.coverage.missing) == (1, 0)


def test_a_unit_that_cannot_be_loaded_is_pending_until_a_decision_covers_it(
    base: str, workspace: Path, tmp_path: Path
) -> None:
    case, relative = _case_file(workspace)
    case.write_bytes(b"{no es json")
    repository = _repository(tmp_path)
    first = _load(workspace, base, repository)
    assert _outcome(first, "case") == "not_loadable"
    assert load_exit_code(first) == 5
    pending = reconcile(workspace, database=base)
    assert (pending.status, pending.coverage.excluded_pending) == ("incomplete", 1)

    decision_id = _decide(workspace, repository, base, relative)
    second = _load(workspace, base, repository)
    assert (_outcome(second, "case"), load_exit_code(second)) == ("excluded", 0)
    assert decision_id in str(next(u.detail for u in second.units if u.kind == "case"))
    covered = reconcile(workspace, database=base, repository=repository)
    assert (covered.status, covered.coverage.excluded_with_decision) == ("equal", 1)
    # Cargar otra vez no reabre el conflicto ya decidido (N5).
    third = _load(workspace, base, repository)
    assert load_exit_code(third) == 0
    assert scalar(base, "SELECT count(*) FROM control.conflictos") == 1
    assert scalar(base, "SELECT count(*) FROM control.conflictos WHERE decision IS NULL") == 0


def test_the_decision_survives_a_new_database_built_from_the_same_files(
    base: str, bd_plantilla: str, workspace: Path, tmp_path: Path
) -> None:
    case, relative = _case_file(workspace)
    case.write_bytes(b"{no es json")
    repository = _repository(tmp_path)
    _load(workspace, base, repository)
    _decide(workspace, repository, base, relative)
    rebuilt = create_database(template=bd_plantilla)
    try:
        report = _load(workspace, rebuilt, repository)
        assert (_outcome(report, "case"), load_exit_code(report)) == ("excluded", 0)
        assert scalar(rebuilt, "SELECT decision FROM control.conflictos") == "accepted_risk"
        assert reconcile(workspace, database=rebuilt, repository=repository).status == "equal"
    finally:
        drop_database(rebuilt)


def test_an_old_decision_does_not_cover_a_file_that_changed(
    base: str, workspace: Path, tmp_path: Path
) -> None:
    case, relative = _case_file(workspace)
    case.write_bytes(b"{no es json")
    repository = _repository(tmp_path)
    _load(workspace, base, repository)
    old = _decide(workspace, repository, base, relative)
    case.write_bytes(b"{tampoco es json, es otra version")
    report = _load(workspace, base, repository)
    assert (_outcome(report, "case"), load_exit_code(report)) == ("not_loadable", 5)
    pending = reconcile(workspace, database=base, repository=repository)
    assert (pending.status, pending.coverage.excluded_pending) == ("incomplete", 1)
    # Hay un conflicto nuevo, para la versión nueva, y la decisión vieja sigue siendo de la vieja.
    assert scalar(base, "SELECT count(*) FROM control.conflictos") == 2
    assert scalar(base, "SELECT count(*) FROM control.conflictos WHERE decision IS NULL") == 1
    # Se puede decidir sobre la versión nueva, y solo una vez por ruta y huella.
    new = _decide(workspace, repository, base, relative)
    assert new != old
    assert load_exit_code(_load(workspace, base, repository)) == 0
    with pytest.raises(BdError, match="ya tienen una decisión"):
        register_decision(
            workspace,
            repository,
            path=relative,
            decision="discarded",
            reason="otra",
            acta=ACTA,
            responsible="PO",
            database=base,
        )
    assert scalar(base, "SELECT count(*) FROM control.conflictos WHERE decision IS NULL") == 0


def test_a_decision_needs_a_pending_conflict_and_minutes_committed_in_git(
    base: str, workspace: Path, tmp_path: Path
) -> None:
    _, relative = _case_file(workspace)
    repository = _repository(tmp_path)
    _load(workspace, base, repository)  # el caso se carga bien: no hay conflicto
    with pytest.raises(BdError, match="no hay un conflicto"):
        _decide(workspace, repository, base, relative)
    case, _ = _case_file(workspace)
    case.write_bytes(b"{no es json")
    _load(workspace, base, repository)
    (repository / ACTA).write_bytes(b"cambiada sin confirmar\n")
    with pytest.raises(BdError, match="sin confirmar"):
        _decide(workspace, repository, base, relative)
    with pytest.raises(BdError, match="no existe"):
        _decide(workspace, repository, base, "casos/no-existe/case.json")
