"""``bd reconstruir``: la candidata se valida antes de cambiar y el cambio se puede revertir.

Escenarios de la revisión del PO (puntos 1 y 2): validar la base nueva con nombre temporal antes de
sustituir la vigente, probar la reversión si el cambio falla, y no tocar bases que no son del
proyecto. La «vigente» de estas pruebas es una base temporal con marca propia.
"""

import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

import semaforo.app.bd_reconstruir as reconstruir
from semaforo.app.bd_commands import VerifyReport, verify
from semaforo.app.bd_reconstruir import (
    Approval,
    Preparation,
    Rename,
    SwitchReport,
    _rename,  # pyright: ignore[reportPrivateUsage]
    prepare_rebuild,
    switch_database,
)
from semaforo.bd.conexion import ADMIN, BdError, Connection, connect
from semaforo.bd.esquema import schema_version
from semaforo.bd.temporales import create_database, drop_database
from semaforo.dominio.errors import ErrorCode
from workspace_tools import build_workspace

pytestmark = pytest.mark.bd


@dataclass(frozen=True)
class Rebuild:
    current: str
    candidate: str
    previous: str
    workspace: Path
    backups: Path


def _exists(name: str) -> bool:
    with connect(ADMIN, database="postgres", autocommit=True) as connection:
        row = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    return row is not None


def _has_marker(database: str) -> bool:
    with connect(ADMIN, database=database, autocommit=True) as connection:
        row = connection.execute("SELECT to_regclass('public.marca_vigente')").fetchone()
    return row is not None and row[0] is not None


@pytest.fixture
def rebuild(tmp_path: Path) -> Iterator[Rebuild]:
    token = secrets.token_hex(3)
    current = create_database()
    with connect(ADMIN, database=current, autocommit=True) as connection:
        connection.execute("CREATE TABLE public.marca_vigente (x integer)")
    made = Rebuild(
        current=current,
        candidate=f"semaforo_pruebas_cand_{token}",
        previous=f"semaforo_pruebas_ant_{token}",
        workspace=tmp_path / "datos",
        backups=tmp_path / "respaldos",
    )
    made.workspace.mkdir()
    yield made
    for name in (current, made.candidate, made.previous):
        drop_database(name)


WRONG = Approval(
    version_esquema="sql-de-otra-version", content_sha256="0" * 64, rules_sha256="0" * 64
)


def _approval(prepared: Preparation) -> Approval:
    """Lo que aprueba el PO: las tres huellas que dejó la preparación."""
    assert prepared.version_esquema is not None
    assert prepared.content_sha256 is not None
    assert prepared.rules_sha256 is not None
    return Approval(
        version_esquema=prepared.version_esquema,
        content_sha256=prepared.content_sha256,
        rules_sha256=prepared.rules_sha256,
    )


def _prepare(made: Rebuild, workspace: Path | None = None) -> Preparation:
    return prepare_rebuild(
        workspace or made.workspace,
        made.workspace.parent,
        backups=made.backups,
        database=made.current,
        candidate=made.candidate,
        compare=False,
    )


def _switch(
    made: Rebuild,
    approved: Approval,
    *,
    tests_approved: bool = True,
    fingerprints: Path | None = None,
    rename: Rename = _rename,
) -> SwitchReport:
    return switch_database(
        made.workspace,
        made.workspace.parent,
        candidate=made.candidate,
        approved=approved,
        tests_approved=tests_approved,
        database=made.current,
        previous=made.previous,
        fingerprints=fingerprints,
        rename=rename,
    )


def test_the_candidate_is_validated_step_by_step_and_the_current_base_is_not_touched(
    rebuild: Rebuild,
) -> None:
    prepared = _prepare(rebuild)
    assert prepared.status == "lista", prepared.reason
    assert [(s.paso, s.resultado) for s in prepared.steps] == [
        ("P0", "ok"),
        ("P1", "ok"),
        ("P2", "ok"),
        ("P3", "ok"),
        ("P4", "ok"),
        ("P5", "ok"),
        ("P7", "ok"),
    ]
    assert prepared.candidate == rebuild.candidate
    assert prepared.version_esquema == schema_version()
    assert prepared.backup is not None and (rebuild.backups / prepared.backup).is_file()
    measured = verify(rebuild.workspace, None, compare=False, database=rebuild.candidate)
    assert measured.content_sha256 == prepared.content_sha256
    assert measured.rules_sha256 == prepared.rules_sha256
    assert _exists(rebuild.candidate) and _has_marker(rebuild.current)


def test_a_failed_gate_stops_the_process_and_removes_the_candidate(
    rebuild: Rebuild, tmp_path: Path
) -> None:
    (tmp_path / "otro").mkdir()
    broken, _ = build_workspace(tmp_path / "otro")
    case = next((broken / "casos").iterdir()) / "case.json"
    case.write_bytes(b"{no es json")
    prepared = _prepare(rebuild, broken)
    assert (prepared.status, prepared.stopped_at) == ("detenida", "P2")
    assert "not_loadable" in str(prepared.reason)
    assert prepared.steps[-1].resultado == "falla"
    assert not _exists(rebuild.candidate)  # no queda una candidata a medias
    assert _has_marker(rebuild.current)  # y la vigente sigue igual


def test_the_switch_needs_the_tests_declared_and_the_fingerprint_the_po_approved(
    rebuild: Rebuild,
) -> None:
    prepared = _prepare(rebuild)
    assert prepared.content_sha256 is not None
    without_tests = _switch(rebuild, _approval(prepared), tests_approved=False)
    assert (without_tests.status, without_tests.steps[-1].paso) == ("detenida", "P6")
    other = _switch(rebuild, WRONG)
    assert (other.status, other.steps[-1].paso) == ("detenida", "P7")
    assert _has_marker(rebuild.current) and not _exists(rebuild.previous)


def test_the_switch_keeps_the_previous_base_and_writes_the_new_fingerprints(
    rebuild: Rebuild, tmp_path: Path
) -> None:
    prepared = _prepare(rebuild)
    assert prepared.content_sha256 is not None
    fingerprints = tmp_path / "huellas.json"
    done = _switch(rebuild, _approval(prepared), fingerprints=fingerprints)
    assert (done.status, done.previous) == ("cambiada", rebuild.previous)
    assert [s.paso for s in done.steps] == ["P6", "P7", "P8", "P9"]
    assert not _has_marker(rebuild.current)  # la candidata ocupa el lugar de la vigente
    assert _has_marker(rebuild.previous)  # y la vigente se conserva con otro nombre
    assert not _exists(rebuild.candidate)
    written = json.loads(fingerprints.read_text(encoding="utf-8"))
    assert written["content_sha256"] == prepared.content_sha256
    assert written["schema_version_db"] == schema_version()


def test_if_the_second_rename_fails_the_first_is_reverted(rebuild: Rebuild) -> None:
    prepared = _prepare(rebuild)
    assert prepared.content_sha256 is not None
    calls: list[tuple[str, str]] = []

    def flaky(admin: Connection, old: str, new: str) -> None:
        calls.append((old, new))
        if len(calls) == 2:
            raise BdError(ErrorCode.OUTPUT_INVALID, "falla", "x")
        _rename(admin, old, new)

    with pytest.raises(BdError, match="falla"):
        _switch(rebuild, _approval(prepared), rename=flaky)
    assert calls == [
        (rebuild.current, rebuild.previous),
        (rebuild.candidate, rebuild.current),
        (rebuild.previous, rebuild.current),  # la reversión
    ]
    assert _has_marker(rebuild.current)  # la vigente quedó como estaba
    assert _exists(rebuild.candidate) and not _exists(rebuild.previous)


def test_the_switch_does_not_run_with_open_connections(rebuild: Rebuild) -> None:
    prepared = _prepare(rebuild)
    assert prepared.content_sha256 is not None
    with connect(ADMIN, database=rebuild.current, autocommit=True):
        stopped = _switch(rebuild, _approval(prepared))
    assert (stopped.status, stopped.steps[-1].paso) == ("detenida", "P8")
    assert "conexiones abiertas" in str(stopped.reason)
    assert _has_marker(rebuild.current) and _exists(rebuild.candidate)


@pytest.mark.parametrize("other", ["tickers_report_db", "trading_predict", "BankData", "postgres"])
def test_it_never_touches_a_base_that_is_not_the_projects(other: str, tmp_path: Path) -> None:
    folder = tmp_path / "datos"
    folder.mkdir()
    with pytest.raises(BdError, match="solo se tocan bases del proyecto"):
        prepare_rebuild(folder, tmp_path, backups=tmp_path / "r", database=other)
    with pytest.raises(BdError, match="solo se tocan bases del proyecto"):
        switch_database(
            folder,
            tmp_path,
            candidate=other,
            approved=WRONG,
            tests_approved=True,
        )
    with pytest.raises(BdError, match="solo se tocan bases del proyecto"):
        switch_database(
            folder,
            tmp_path,
            candidate="semaforo_pruebas_x",
            approved=WRONG,
            tests_approved=True,
            previous=other,
        )
    with pytest.raises(BdError):
        drop_database(other)


def test_a_candidate_whose_rules_differ_is_refused_even_though_its_rows_are_the_same(
    rebuild: Rebuild,
) -> None:
    """Un disparador apagado no cambia ninguna fila, así que la huella de contenido no lo ve."""
    prepared = _prepare(rebuild)
    with connect(ADMIN, database=rebuild.candidate, autocommit=True) as connection:
        connection.execute("ALTER TABLE simulacion.corridas DISABLE TRIGGER solo_agregar")
    stopped = _switch(rebuild, _approval(prepared))
    assert (stopped.status, stopped.steps[-1].paso) == ("detenida", "P7")
    assert "huella de reglas" in str(stopped.reason)
    assert _has_marker(rebuild.current) and _exists(rebuild.candidate)
    assert not _exists(rebuild.previous)


def test_an_approval_of_another_schema_version_is_refused(rebuild: Rebuild) -> None:
    prepared = _prepare(rebuild)
    approval = _approval(prepared)
    other = Approval(
        version_esquema="sql-de-otra-version",
        content_sha256=approval.content_sha256,
        rules_sha256=approval.rules_sha256,
    )
    stopped = _switch(rebuild, other)
    assert (stopped.status, stopped.steps[-1].paso) == ("detenida", "P7")
    assert "versión del esquema" in str(stopped.reason)
    assert _has_marker(rebuild.current) and _exists(rebuild.candidate)


def test_an_approval_whose_content_differs_is_refused_when_the_schema_and_rules_match(
    rebuild: Rebuild,
) -> None:
    """Cada huella se comprueba por separado: aquí solo la de contenido es la que no coincide."""
    prepared = _prepare(rebuild)
    approval = _approval(prepared)
    other = Approval(
        version_esquema=approval.version_esquema,
        content_sha256="0" * 64,
        rules_sha256=approval.rules_sha256,
    )
    stopped = _switch(rebuild, other)
    assert (stopped.status, stopped.steps[-1].paso) == ("detenida", "P7")
    assert "huella de contenido" in str(stopped.reason)
    assert _has_marker(rebuild.current) and _exists(rebuild.candidate)


def test_rules_that_change_while_the_names_are_swapped_are_reverted_at_P9(
    rebuild: Rebuild,
) -> None:
    """Un cambio de reglas justo después del cambio de nombre lo detecta la última comprobación."""
    prepared = _prepare(rebuild)

    def break_rules_on_swap(admin: Connection, old: str, new: str) -> None:
        _rename(admin, old, new)
        if old == rebuild.candidate:  # la candidata acaba de ocupar el lugar de la vigente
            with connect(ADMIN, database=new, autocommit=True) as connection:
                connection.execute("ALTER TABLE simulacion.corridas DISABLE TRIGGER solo_agregar")

    stopped = _switch(rebuild, _approval(prepared), rename=break_rules_on_swap)
    assert (stopped.status, stopped.steps[-1].paso) == ("detenida", "P9")
    assert "huella de reglas" in str(stopped.reason)
    assert _has_marker(rebuild.current)  # la vigente volvió a su lugar
    assert _exists(rebuild.candidate) and not _exists(rebuild.previous)


def test_an_error_while_verifying_P9_restores_the_previous_base(
    rebuild: Rebuild, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare(rebuild)
    original_verify = reconstruir.verify

    def fail_after_swap(
        workspace: Path, repository: Path | None, *, compare: bool, database: str
    ) -> VerifyReport:
        if database == rebuild.current:
            raise BdError(ErrorCode.OUTPUT_INVALID, "falló la verificación", "P9")
        return original_verify(workspace, repository, compare=compare, database=database)

    monkeypatch.setattr(reconstruir, "verify", fail_after_swap)
    stopped = _switch(rebuild, _approval(prepared))

    assert (stopped.status, stopped.steps[-1].paso) == ("detenida", "P9")
    assert "falló la verificación" in str(stopped.reason)
    assert "se revirtió" in str(stopped.reason)
    assert _has_marker(rebuild.current)
    assert _exists(rebuild.candidate) and not _exists(rebuild.previous)


def test_a_failed_P9_rollback_reports_the_uncertain_state(
    rebuild: Rebuild, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare(rebuild)
    original_verify = reconstruir.verify

    def fail_after_swap(
        workspace: Path, repository: Path | None, *, compare: bool, database: str
    ) -> VerifyReport:
        if database == rebuild.current:
            raise BdError(ErrorCode.OUTPUT_INVALID, "falló la verificación", "P9")
        return original_verify(workspace, repository, compare=compare, database=database)

    def fail_rollback(admin: Connection, old: str, new: str) -> None:
        if old == rebuild.current and new == rebuild.candidate:
            raise BdError(ErrorCode.OUTPUT_INVALID, "falló la reversión", "P9")
        _rename(admin, old, new)

    monkeypatch.setattr(reconstruir, "verify", fail_after_swap)
    with pytest.raises(BdError, match="estado de las bases por comprobar") as failure:
        _switch(rebuild, _approval(prepared), rename=fail_rollback)

    assert rebuild.current in failure.value.message
    assert rebuild.candidate in failure.value.message
    assert rebuild.previous in failure.value.message


@pytest.mark.parametrize("folder", ["sin-git", "no-existe"])
def test_acu17_a_rebuild_without_the_git_repository_stops_at_the_first_gate(
    rebuild: Rebuild, tmp_path: Path, folder: str
) -> None:
    """Sin la carpeta del repositorio no hay referencia de git ni actas: no se prepara nada."""
    repository = tmp_path / folder
    if folder == "sin-git":
        repository.mkdir()
    prepared = prepare_rebuild(
        rebuild.workspace,
        repository,
        backups=rebuild.backups,
        database=rebuild.current,
        candidate=rebuild.candidate,
    )
    assert (prepared.status, prepared.stopped_at) == ("detenida", "P0")
    assert prepared.steps[-1].resultado == "falla"
    assert not _exists(rebuild.candidate)  # no se creó ninguna candidata
    assert _has_marker(rebuild.current)  # y la vigente sigue igual
