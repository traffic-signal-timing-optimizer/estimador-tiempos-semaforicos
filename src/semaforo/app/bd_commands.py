"""Comandos de la base de datos (DEV31 F3): ``bd iniciar``, ``cargar``, ``verificar``, ``hito`` y
``respaldar``.

La lógica vive en ``semaforo.bd``; aquí solo se arman las piezas de cada comando. Ningún informe
lleva contraseñas ni rutas de la máquina.
"""

import secrets
from pathlib import Path
from typing import Literal

import psycopg
from psycopg import sql

from semaforo.bd.carga.hitos import Milestone, MilestoneKind, milestone_row, publish_milestone
from semaforo.bd.carga.insercion import Catalog, write_rows
from semaforo.bd.carga.modelo import REPOSITORY_ROOT, FileRecord, Unit, read_file
from semaforo.bd.carga.motor import LoadOptions, LoadReport, artifact_rows, load_workspace
from semaforo.bd.conciliacion import ReconcileReport, reconcile
from semaforo.bd.conexion import CARGA, BdError, Connection, connect
from semaforo.bd.esquema import installed_version
from semaforo.bd.instalacion import InstallReport, InstallRequest, install
from semaforo.bd.metricas import MetricsReport, publish_missing
from semaforo.bd.respaldo import BackupReport, backup
from semaforo.bd.temporales import scratch_database
from semaforo.bd.verificacion import (
    FingerprintFile,
    RootCheck,
    check_roots,
    content_hash,
    root_fingerprints,
    write_fingerprints,
)
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.herramientas import git_output
from semaforo.trazabilidad.paths import check_relative_path
from semaforo.trazabilidad.store import utc_now

__all__ = [
    "LoadReport",
    "MetricsReport",
    "ReconcileReport",
    "VerifyReport",
    "backup_database",
    "initialize",
    "load",
    "load_exit_code",
    "publish_metrics",
    "reconcile_database",
    "reconcile_exit_code",
    "register_milestone",
    "verify",
    "verify_exit_code",
]

INTEGRITY_EXIT = 5


def initialize(folder: Path, superuser: str = "postgres") -> InstallReport:
    """``bd iniciar``: espacio de tablas, usuarios, base y esquema (se puede repetir)."""
    return install(InstallRequest(folder=folder, superuser=superuser))


def load(  # noqa: PLR0913  (cada autorización es de solo palabra clave)
    workspace: Path,
    *,
    preliminary: bool = False,
    loose_runs: bool = False,
    without_metrics: bool = False,
    repository: Path | None = None,
    database: str | None = None,
) -> LoadReport:
    """``bd cargar``: carga ``workspace`` en la base."""
    options = LoadOptions(
        preliminary=preliminary,
        loose_runs=loose_runs,
        without_metrics=without_metrics,
        repository=repository,
    )
    return load_workspace(workspace, options, database=database)


def load_exit_code(report: LoadReport) -> int:
    """0 si la carga terminó sin conflictos; 5 si alguna unidad fue rechazada."""
    return INTEGRITY_EXIT if report.counts.get("rejected") else 0


# --- verificar -------------------------------------------------------------------------------


class VerifyReport(FrozenModel):
    """Resultado de ``bd verificar``."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["intact", "changed"]
    database_schema: str | None
    last_load: str | None
    content_sha256: str
    rows: dict[str, int]
    roots_checked: int
    roots_changed: list[RootCheck]
    regenerated_sha256: str | None
    regenerated_equal: bool | None
    fingerprints_file: str | None


def _authorizations(connection: Connection) -> LoadOptions:
    """Las autorizaciones que usó alguna carga completa (para regenerar igual)."""
    row = connection.execute(
        "SELECT coalesce(bool_or((comando->>'preliminar')::boolean), false), "
        "coalesce(bool_or((comando->>'sueltas')::boolean), false), "
        "coalesce(bool_or((comando->>'sin_metricas')::boolean), false) "
        "FROM control.cargas WHERE estado = 'completed'"
    ).fetchone()
    flags = (False, False, False) if row is None else (bool(row[0]), bool(row[1]), bool(row[2]))
    return LoadOptions(preliminary=flags[0], loose_runs=flags[1], without_metrics=flags[2])


def _last_load(connection: Connection) -> str | None:
    row = connection.execute(
        "SELECT carga_id FROM control.cargas WHERE estado = 'completed' "
        "ORDER BY inicio DESC LIMIT 1"
    ).fetchone()
    return None if row is None else str(row[0])


def verify(
    workspace: Path,
    repository: Path | None,
    *,
    fingerprints: Path | None = None,
    regenerate: bool = False,
    database: str | None = None,
) -> VerifyReport:
    """``bd verificar``: huella de contenido, archivos raíz y, si se pide, regeneración.

    - recalcula la huella de cada archivo raíz que conoce la base (manifiestos y archivos sueltos)
      y dice cuáles ya no coinciden;
    - con ``regenerate``, carga los mismos archivos en una base temporal nueva y compara su huella
      de contenido con la de la base (QA36);
    - con ``fingerprints``, escribe el archivo de huellas para guardarlo en git (ADR03).
    """
    with connect(CARGA, database=database, autocommit=True) as connection:
        catalog = Catalog.load(connection)
        digest, rows = content_hash(connection, catalog)
        checked, changed = check_roots(connection, workspace, repository)
        options = _authorizations(connection)
        last = _last_load(connection)
        schema = installed_version(connection)
        roots = root_fingerprints(connection)
    regenerated: str | None = None
    if regenerate:
        with scratch_database() as name:
            report = load_workspace(
                workspace,
                LoadOptions(
                    preliminary=options.preliminary,
                    loose_runs=options.loose_runs,
                    without_metrics=options.without_metrics,
                    repository=repository,
                ),
                database=name,
            )
            regenerated = report.content_sha256
    written: str | None = None
    if fingerprints is not None:
        write_fingerprints(
            fingerprints,
            FingerprintFile(
                generated_at=utc_now(),
                carga_id=last,
                schema_version_db=schema,
                content_sha256=digest,
                rows=rows,
                roots=roots,
            ),
        )
        written = fingerprints.name
    equal = None if regenerated is None else regenerated == digest
    intact = not changed and equal is not False
    return VerifyReport(
        status="intact" if intact else "changed",
        database_schema=schema,
        last_load=last,
        content_sha256=digest,
        rows=rows,
        roots_checked=checked,
        roots_changed=changed,
        regenerated_sha256=regenerated,
        regenerated_equal=equal,
        fingerprints_file=written,
    )


def verify_exit_code(report: VerifyReport) -> int:
    """0 si todo coincide; 5 si un archivo cambió o la base regenerada no da la misma huella."""
    return 0 if report.status == "intact" else INTEGRITY_EXIT


# --- hitos -----------------------------------------------------------------------------------

OBJECT_HASH: dict[MilestoneKind, sql.SQL] = {
    "protocol_frozen": sql.SQL(
        "SELECT a.sha256 FROM experimento.protocolos AS o "
        "JOIN control.artefactos AS a ON a.artefacto_id = o.artefacto_id WHERE o.protocolo_id = %s"
    ),
    "split_frozen": sql.SQL(
        "SELECT a.sha256 FROM experimento.particiones AS o "
        "JOIN control.artefactos AS a ON a.artefacto_id = o.artefacto_id WHERE o.particion_id = %s"
    ),
    "model_frozen": sql.SQL(
        "SELECT coalesce(o.huella_paquete, a.sha256) FROM aprendizaje.modelos AS o "
        "JOIN control.artefactos AS a ON a.artefacto_id = o.artefacto_id WHERE o.modelo_id = %s"
    ),
    "test_opened": sql.SQL(
        "SELECT huella_experimento FROM evaluacion.experimentos WHERE experimento_id = %s"
    ),
}


def _committed_minutes(repository: Path, acta: str) -> str:
    """El commit que contiene el acta, que tiene que estar en git y sin cambios."""
    if git_output(repository, "ls-files", "--error-unmatch", "--", acta) is None:
        raise BdError(ErrorCode.INPUT_SCHEMA, "el acta no está en git: confírmela primero", acta)
    if git_output(repository, "status", "--porcelain", "--", acta):
        raise BdError(ErrorCode.INPUT_SCHEMA, "el acta tiene cambios sin confirmar en git", acta)
    commit = git_output(repository, "log", "-1", "--format=%H", "--", acta)
    if not commit:
        raise BdError(ErrorCode.INPUT_SCHEMA, "no se encontró el commit del acta", acta)
    return commit


def _ids(kind: MilestoneKind, target: str, partition: str | None) -> dict[str, str | None]:
    ids: dict[str, str | None] = dict.fromkeys(
        ("protocolo_id", "particion_id", "modelo_id", "experimento_id")
    )
    column = {
        "protocol_frozen": "protocolo_id",
        "split_frozen": "particion_id",
        "model_frozen": "modelo_id",
        "test_opened": "experimento_id",
    }[kind]
    ids[column] = target
    if kind == "test_opened":
        ids["particion_id"] = partition
    return ids


def register_milestone(  # noqa: PLR0913  (cada dato del hito es de solo palabra clave)
    workspace: Path,
    repository: Path,
    *,
    kind: MilestoneKind,
    target: str,
    acta: str,
    responsible: str,
    partition: str | None = None,
    notes: str | None = None,
    database: str | None = None,
) -> tuple[str, LoadReport]:
    """``bd hito``: comprueba el hito contra la base, lo publica como archivo y lo carga.

    La comprobación se hace antes de publicar (en una transacción que se deshace): si la base lo
    rechazaría (por ejemplo, abrir la prueba sin el modelo congelado), no queda ningún archivo.

    Raises:
        BdError: si el objeto no está en la base, el acta no está confirmada en git, falta la
            partición de una apertura o la base rechaza el orden de los hitos.
    """
    if kind == "test_opened" and partition is None:
        raise BdError(ErrorCode.INPUT_SCHEMA, "abrir la prueba necesita su partición", "particion")
    try:
        relative = check_relative_path(acta)
    except ValueError as error:
        raise BdError(ErrorCode.PATH_NOT_ALLOWED, str(error), "acta") from error
    commit = _committed_minutes(repository, relative)
    acta_record, _ = read_file(repository, REPOSITORY_ROOT, relative, "minutes")
    with connect(CARGA, database=database, autocommit=True) as connection:
        found = connection.execute(OBJECT_HASH[kind], (target,)).fetchone()
        if found is None or found[0] is None:
            raise BdError(ErrorCode.INPUT_SCHEMA, f"el objeto {target} no está en la base", target)
        moment = utc_now()
        ids = _ids(kind, target, partition)
        milestone = Milestone(
            hito_id=f"hito-{moment:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}",
            tipo=kind,
            registrado_en=moment,
            protocolo_id=ids["protocolo_id"],
            particion_id=ids["particion_id"],
            modelo_id=ids["modelo_id"],
            experimento_id=ids["experimento_id"],
            huella_objeto=str(found[0]),
            acta=relative,
            acta_sha256=acta_record.sha256,
            commit_codigo=commit,
            responsable=responsible,
            notas=notes,
        )
        _dry_run(connection, milestone, acta_record)
    publish_milestone(workspace, milestone)
    report = load_workspace(
        workspace,
        LoadOptions(kinds=frozenset({"milestone"}), repository=repository),
        database=database,
    )
    return milestone.hito_id, report


class _DryRun(Exception):
    """Deshace a propósito la transacción de prueba del hito."""


def _dry_run(connection: Connection, milestone: Milestone, acta_record: FileRecord) -> None:
    """Escribe el hito en una transacción que se deshace: la base dice si lo aceptaría.

    Raises:
        BdError: INPUT_SCHEMA con el motivo, si la base rechaza el hito.
    """
    catalog = Catalog.load(connection)
    probe = f"prueba-{secrets.token_hex(4)}"
    unit = Unit(key=milestone.hito_id, kind="milestone", files=[acta_record])
    unit.add("control.hitos", milestone_row(milestone), acta_record)
    rows = {"control.artefactos": artifact_rows(unit), **unit.rows}
    try:
        with connection.transaction():
            connection.execute(
                "INSERT INTO control.cargas (carga_id, inicio, estado, comando, version_paquete, "
                "version_postgres, version_esquema) "
                "VALUES (%s, now(), 'running', '{}'::jsonb, 'prueba', 'prueba', 'prueba')",
                (probe,),
            )
            result = write_rows(connection, catalog, rows, probe)
            if result.conflicts:
                raise BdError(
                    ErrorCode.RUN_EXISTS, "ya hay un hito con ese identificador", "hito_id"
                )
            raise _DryRun
    except _DryRun:
        return
    except psycopg.Error as error:
        diagnostic = getattr(error, "diag", None)
        message = None if diagnostic is None else getattr(diagnostic, "message_primary", None)
        raise BdError(
            ErrorCode.INPUT_SCHEMA,
            f"la base rechaza el hito: {message or type(error).__name__}",
            "hito",
        ) from error


# --- respaldar -------------------------------------------------------------------------------


def backup_database(folder: Path, *, database: str | None = None) -> BackupReport:
    """``bd respaldar``: ``pg_dump`` de la base en ``folder``, con su huella al lado."""
    return backup(folder, database=database)


# --- métricas y conciliación (F4) ------------------------------------------------------------


def publish_metrics(workspace: Path, *, protocol_id: str | None = None) -> MetricsReport:
    """``bd metricas``: calcula y publica las métricas de las corridas que todavía no las tienen."""
    return publish_missing(workspace, protocol_id=protocol_id)


def reconcile_database(
    workspace: Path,
    *,
    repository: Path | None = None,
    recompute: bool = True,
    database: str | None = None,
) -> ReconcileReport:
    """``bd conciliar``: compara la base con los archivos (conteos y demora recalculada)."""
    return reconcile(workspace, database=database, repository=repository, recompute=recompute)


def reconcile_exit_code(report: ReconcileReport) -> int:
    """0 si la base coincide con los archivos; 5 si hay alguna diferencia."""
    return 0 if report.status == "equal" else INTEGRITY_EXIT
