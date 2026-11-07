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

from semaforo.app.bd_commands import verify
from semaforo.app.bd_reconstruir import (
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
    approved: str,
    *,
    tests_approved: bool = True,
    fingerprints: Path | None = None,
    rename: Rename = _rename,
) -> SwitchReport:
    return switch_database(
        made.workspace,
        made.workspace.parent,
        candidate=made.candidate,
        approved_sha256=approved,
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
    without_tests = _switch(rebuild, prepared.content_sha256, tests_approved=False)
    assert (without_tests.status, without_tests.steps[-1].paso) == ("detenida", "P6")
    other = _switch(rebuild, "0" * 64)
    assert (other.status, other.steps[-1].paso) == ("detenida", "P7")
    assert _has_marker(rebuild.current) and not _exists(rebuild.previous)


def test_the_switch_keeps_the_previous_base_and_writes_the_new_fingerprints(
    rebuild: Rebuild, tmp_path: Path
) -> None:
    prepared = _prepare(rebuild)
    assert prepared.content_sha256 is not None
    fingerprints = tmp_path / "huellas.json"
    done = _switch(rebuild, prepared.content_sha256, fingerprints=fingerprints)
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
        _switch(rebuild, prepared.content_sha256, rename=flaky)
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
        stopped = _switch(rebuild, prepared.content_sha256)
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
            approved_sha256="0" * 64,
            tests_approved=True,
        )
    with pytest.raises(BdError, match="solo se tocan bases del proyecto"):
        switch_database(
            folder,
            tmp_path,
            candidate="semaforo_pruebas_x",
            approved_sha256="0" * 64,
            tests_approved=True,
            previous=other,
        )
    with pytest.raises(BdError):
        drop_database(other)
