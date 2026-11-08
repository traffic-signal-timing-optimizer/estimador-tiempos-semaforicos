"""Comandos de la base de datos (DEV31 F3): ``bd iniciar``, ``cargar``, ``verificar``, ``hito`` y
``respaldar``.

La lógica vive en ``semaforo.bd``; aquí solo se arman las piezas de cada comando. Ningún informe
lleva contraseñas ni rutas de la máquina.
"""

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psycopg
from psycopg import sql

from semaforo.bd.acceso import NetworkReport, network_report
from semaforo.bd.carga.decisiones import (
    Decision,
    DecisionKind,
    publish_decision,
    read_decision,
)
from semaforo.bd.carga.fuentes import discover
from semaforo.bd.carga.hitos import Milestone, MilestoneKind, milestone_row, publish_milestone
from semaforo.bd.carga.insercion import Catalog, write_rows
from semaforo.bd.carga.modelo import (
    DATA_ROOT,
    REPOSITORY_ROOT,
    CargaError,
    FileRecord,
    Unit,
    artifact_id,
    read_file,
)
from semaforo.bd.carga.motor import (
    LoadOptions,
    LoadReport,
    artifact_links,
    artifact_rows,
    load_workspace,
)
from semaforo.bd.conciliacion import ReconcileReport, reconcile
from semaforo.bd.conexion import CARGA, DATABASE, BdError, Connection, connect
from semaforo.bd.esquema import installed_version
from semaforo.bd.instalacion import InstallReport, InstallRequest, install
from semaforo.bd.instantanea import Inconcluso, lectura_estable
from semaforo.bd.metricas import MetricsReport, publish_missing
from semaforo.bd.prueba_respaldo import BackupTest, backup_test_exit_code, probar_respaldo
from semaforo.bd.reglas import RULES_ALGORITHM, rules_digest
from semaforo.bd.respaldo import BackupReport, Ficha, FichaCampo, backup, ficha_de_archivo
from semaforo.bd.temporales import scratch_database
from semaforo.bd.verificacion import (
    HASH_ALGORITHM,
    FingerprintFile,
    Measured,
    ReferenceCheck,
    RootCheck,
    check_roots,
    compare_with_reference,
    content_hash,
    read_fingerprints,
    root_fingerprints,
    write_fingerprints,
)
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import DomainError, ErrorCode
from semaforo.simulacion.herramientas import git_output
from semaforo.trazabilidad.hashing import sha256_file
from semaforo.trazabilidad.paths import check_relative_path
from semaforo.trazabilidad.store import utc_now

__all__ = [
    "DATABASE",
    "BackupTest",
    "Ficha",
    "FichaCampo",
    "LoadOptions",
    "LoadReport",
    "MetricsReport",
    "ReconcileReport",
    "RegenerateReport",
    "VerifyReport",
    "backup_card",
    "backup_database",
    "backup_test_exit_code",
    "initialize",
    "load",
    "load_exit_code",
    "load_options_of",
    "publish_metrics",
    "reconcile_database",
    "reconcile_exit_code",
    "regenerate",
    "regenerate_exit_code",
    "register_decision",
    "register_milestone",
    "test_backup",
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
    """0 si todo quedó cargado o excluido con decisión; 5 si alguna unidad quedó rechazada,
    pendiente o no cargable sin decisión."""
    counts = report.counts
    open_items = (
        counts.get("rejected", 0) + counts.get("pending", 0) + counts.get("not_loadable", 0)
    )
    return INTEGRITY_EXIT if open_items else 0


# --- verificar -------------------------------------------------------------------------------


HUELLAS_FILE = "docs/bd/huellas.json"
INCONCLUSIVE_EXIT = 6


class VerifyReport(FrozenModel):
    """Resultado de ``bd verificar``: solo lectura, en una instantánea (C1.6)."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    status: Literal["intact", "changed", "inconclusive"]
    reason: str | None
    database_schema: str | None
    last_load: str | None
    content_sha256: str | None
    hash_algorithm: str
    rules_sha256: str | None
    rules_algorithm: str
    rows: dict[str, int]
    roots_checked: int
    roots_changed: list[RootCheck]
    reference: ReferenceCheck | None
    network: NetworkReport | None
    fingerprints_file: str | None


class RegenerateReport(FrozenModel):
    """Resultado de ``bd regenerar``: la base regenerada desde los archivos (QA36)."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["same", "different", "inconclusive"]
    reason: str | None
    content_sha256: str | None
    regenerated_sha256: str | None


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


def _no_reference(source: str, reason: str) -> ReferenceCheck:
    return ReferenceCheck(source=source, outcome="no_concluyente", reason=reason, differences=[])


def _from_git(repository: Path | None) -> tuple[FingerprintFile, str] | ReferenceCheck:
    """El ``docs/bd/huellas.json`` del último commit que lo cambió."""
    if repository is None:
        return _no_reference("git", "no se indicó la carpeta del repositorio")
    commit = git_output(repository, "log", "-1", "--format=%H", "--", HUELLAS_FILE)
    if not commit:
        return _no_reference("git", f"{HUELLAS_FILE} no está en ningún commit del repositorio")
    source = f"git {commit[:12]}:{HUELLAS_FILE}"
    text = git_output(repository, "show", f"{commit}:{HUELLAS_FILE}")
    try:
        if text is None:
            return _no_reference(source, "no se pudo leer la referencia de git")
        return read_fingerprints(text), source
    except ValueError:
        return _no_reference(source, "la referencia de git no es un archivo de huellas válido")


def _reference(
    repository: Path | None, reference: Path | None
) -> tuple[FingerprintFile, str] | ReferenceCheck:
    """La huella de referencia: la indicada, o la del último commit de ``docs/bd/huellas.json``."""
    if reference is None:
        return _from_git(repository)
    try:
        return read_fingerprints(reference.read_text(encoding="utf-8")), "archivo indicado"
    except (OSError, ValueError) as error:
        return _no_reference(
            "archivo indicado",
            f"no se puede leer la referencia indicada ({type(error).__name__})",
        )


def _verify_status(
    change: str | None, changed: list[RootCheck], check: ReferenceCheck | None
) -> tuple[Literal["intact", "changed", "inconclusive"], str | None]:
    if change is not None:
        return "inconclusive", change
    if changed:
        return "changed", f"{len(changed)} archivos raíz ya no coinciden con la base"
    if check is not None and check.outcome == "difiere":
        return "changed", f"{len(check.differences)} diferencias con la referencia"
    if check is not None and check.outcome == "no_concluyente":
        return "inconclusive", check.reason
    return "intact", None


def _read_hba(hba: Path | None) -> str | None:
    if hba is None:
        return None
    try:
        return hba.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise BdError(
            ErrorCode.INPUT_SCHEMA,
            f"no se puede leer el archivo de reglas ({type(error).__name__})",
            "hba",
        ) from error


def verify(  # noqa: PLR0913  (cada opción es de solo palabra clave)
    workspace: Path,
    repository: Path | None,
    *,
    reference: Path | None = None,
    compare: bool = True,
    fingerprints: Path | None = None,
    network: bool = False,
    hba: Path | None = None,
    database: str | None = None,
) -> VerifyReport:
    """``bd verificar``: huella de contenido, archivos raíz, reglas instaladas y referencia.

    Solo lee: una instantánea de solo lectura con el candado compartido (``instantanea``). No crea
    ni borra bases (la regeneración está en ``regenerate``).

    - recalcula la huella de cada archivo raíz que conoce la base (manifiestos y archivos sueltos)
      y dice cuáles ya no coinciden;
    - calcula la huella de contenido y la de las reglas instaladas (disparadores, políticas,
      permisos…) y las compara con la **referencia**: la indicada, o la del último commit de
      ``docs/bd/huellas.json``. Una referencia de otra versión del esquema da *no concluyente*;
    - con ``fingerprints``, escribe el archivo de huellas para guardarlo en git (ADR03);
    - con ``network``, informa dónde escucha el servicio y qué reglas de acceso admiten equipos de
      fuera de la laptop (C1.9).
    """
    hba_text = _read_hba(hba)
    try:
        with lectura_estable(CARGA, database=database) as reading:
            connection = reading.connection
            digest, rows = content_hash(connection, Catalog.load(connection))
            rules, _ = rules_digest(connection)
            checked, changed = check_roots(connection, workspace, repository)
            schema = installed_version(connection)
            roots = root_fingerprints(connection)
            last = _last_load(connection)
            net = network_report(connection, hba_text) if network else None
    except Inconcluso as stopped:
        return VerifyReport(
            status="inconclusive",
            reason=stopped.reason,
            database_schema=None,
            last_load=None,
            content_sha256=None,
            hash_algorithm=HASH_ALGORITHM,
            rules_sha256=None,
            rules_algorithm=RULES_ALGORITHM,
            rows={},
            roots_checked=0,
            roots_changed=[],
            reference=None,
            network=None,
            fingerprints_file=None,
        )
    check: ReferenceCheck | None = None
    if compare:
        found = _reference(repository, reference)
        check = (
            found
            if isinstance(found, ReferenceCheck)
            else compare_with_reference(
                found[0], Measured(schema, digest, rules, rows, roots), found[1]
            )
        )
    written: str | None = None
    if fingerprints is not None:
        write_fingerprints(
            fingerprints,
            FingerprintFile(
                generated_at=utc_now(),
                carga_id=last,
                schema_version_db=schema,
                content_sha256=digest,
                algoritmo_huella=HASH_ALGORITHM,
                reglas_sha256=rules,
                algoritmo_reglas=RULES_ALGORITHM,
                rows=rows,
                roots=roots,
            ),
        )
        written = fingerprints.name
    status, reason = _verify_status(reading.cambio, changed, check)
    return VerifyReport(
        status=status,
        reason=reason,
        database_schema=schema,
        last_load=last,
        content_sha256=digest,
        hash_algorithm=HASH_ALGORITHM,
        rules_sha256=rules,
        rules_algorithm=RULES_ALGORITHM,
        rows=rows,
        roots_checked=checked,
        roots_changed=changed,
        reference=check,
        network=net,
        fingerprints_file=written,
    )


def verify_exit_code(report: VerifyReport) -> int:
    """0 si todo coincide; 5 si algo cambió; 6 si el resultado no es concluyente."""
    return {"intact": 0, "changed": INTEGRITY_EXIT, "inconclusive": INCONCLUSIVE_EXIT}[
        report.status
    ]


@dataclass(frozen=True)
class _Stable:
    digest: str
    load: str | None
    options: LoadOptions


def _stable(database: str | None) -> _Stable:
    with lectura_estable(CARGA, database=database) as reading:
        connection = reading.connection
        digest, _ = content_hash(connection, Catalog.load(connection))
        return _Stable(digest, _last_load(connection), _authorizations(connection))


def regenerate(
    workspace: Path, repository: Path | None, *, database: str | None = None
) -> RegenerateReport:
    """``bd regenerar`` (QA36): carga los mismos archivos en una base temporal y compara huellas.

    La lectura de la base es estable (instantánea y candado compartido) y se repite al final: si
    la base cambió mientras se regeneraba, el resultado no es concluyente.
    """
    try:
        before = _stable(database)
    except Inconcluso as stopped:
        return RegenerateReport(
            status="inconclusive",
            reason=stopped.reason,
            content_sha256=None,
            regenerated_sha256=None,
        )
    options = LoadOptions(
        preliminary=before.options.preliminary,
        loose_runs=before.options.loose_runs,
        without_metrics=before.options.without_metrics,
        repository=repository,
    )
    with scratch_database() as name:
        regenerated = load_workspace(workspace, options, database=name).content_sha256
    try:
        after = _stable(database)
    except Inconcluso as stopped:
        return RegenerateReport(
            status="inconclusive",
            reason=stopped.reason,
            content_sha256=before.digest,
            regenerated_sha256=regenerated,
        )
    if (after.load, after.digest) != (before.load, before.digest):
        return RegenerateReport(
            status="inconclusive",
            reason="la base cambió mientras se regeneraba",
            content_sha256=before.digest,
            regenerated_sha256=regenerated,
        )
    return RegenerateReport(
        status="same" if regenerated == before.digest else "different",
        reason=None,
        content_sha256=before.digest,
        regenerated_sha256=regenerated,
    )


def regenerate_exit_code(report: RegenerateReport) -> int:
    """0 si la base regenerada da la misma huella; 5 si no; 6 si no es concluyente."""
    return {"same": 0, "different": INTEGRITY_EXIT, "inconclusive": INCONCLUSIVE_EXIT}[
        report.status
    ]


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
        selection = None
        if kind == "model_frozen":
            selection = connection.execute(
                "SELECT seleccion_id, huella_seleccion FROM aprendizaje.seleccion "
                "WHERE modelo_ganador_id = %s",
                (target,),
            ).fetchone()
            if selection is None:
                raise BdError(
                    ErrorCode.INPUT_SCHEMA,
                    "el modelo no tiene una selección registrada que se pueda congelar",
                    target,
                )
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
            seleccion_id=None if selection is None else str(selection[0]),
            huella_seleccion=None if selection is None else str(selection[1]),
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
    rows = {
        "control.artefactos": artifact_rows(unit),
        "control.archivo_escenarios": artifact_links(unit),
        **unit.rows,
    }
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
    """0 si coincide; 5 si difiere o está incompleta; 6 si el resultado no es concluyente."""
    if report.status == "inconclusive":
        return INCONCLUSIVE_EXIT
    return 0 if report.status == "equal" else INTEGRITY_EXIT


def load_options_of(database: str | None = None) -> LoadOptions:
    """Las autorizaciones que usaron las cargas completas de ``database`` (para repetirlas)."""
    return _stable(database).options


# --- decisiones sobre archivos excluidos (C1.5) -----------------------------------------------


def register_decision(  # noqa: PLR0913  (cada dato de la decisión es de solo palabra clave)
    workspace: Path,
    repository: Path,
    *,
    path: str,
    decision: DecisionKind,
    reason: str,
    acta: str,
    responsible: str,
    database: str | None = None,
) -> tuple[str, LoadReport]:
    """``bd decidir``: publica la decisión sobre un archivo excluido y la carga.

    La identidad de la decisión es la **ruta y la huella** del archivo tal como está hoy en
    ``datos/``: debe haber un conflicto pendiente de esa ruta y esa huella. Si el archivo cambió
    desde que se excluyó, no hay conflicto con la huella nueva hasta la próxima carga, y la
    decisión de la versión vieja no la cubre.

    Raises:
        BdError: si el archivo no existe, no hay conflicto pendiente de esa ruta y esa huella, ya
            hay una decisión para ellas o el acta no está confirmada en git.
    """
    try:
        relative = check_relative_path(path)
        acta_relative = check_relative_path(acta)
    except ValueError as error:
        raise BdError(ErrorCode.PATH_NOT_ALLOWED, str(error), "ruta") from error
    target = workspace / relative
    if target.is_symlink() or not target.is_file():
        raise BdError(ErrorCode.INPUT_SCHEMA, "el archivo no existe en datos/", relative)
    digest = sha256_file(target)
    commit = _committed_minutes(repository, acta_relative)
    acta_record, _ = read_file(repository, REPOSITORY_ROOT, acta_relative, "minutes")
    with connect(CARGA, database=database, autocommit=True) as connection:
        rows = connection.execute(
            "SELECT decision FROM control.conflictos WHERE artefacto_id = %s AND huella_nueva = %s",
            (artifact_id(DATA_ROOT, relative), digest),
        ).fetchall()
    if not rows:
        raise BdError(
            ErrorCode.INPUT_SCHEMA,
            "no hay un conflicto de esa ruta y esa huella: ¿el archivo cambió después de la "
            "última carga?",
            relative,
        )
    if all(row[0] is not None for row in rows):
        raise BdError(
            ErrorCode.RUN_EXISTS, "ese archivo y esa huella ya tienen una decisión", relative
        )
    for source in discover(workspace).of("decision"):
        try:
            published, _ = read_decision(workspace, source.folder)
        except (DomainError, CargaError):
            continue
        if (published.ruta, published.huella) == (relative, digest):
            raise BdError(
                ErrorCode.RUN_EXISTS,
                f"ya hay una decisión publicada para esa ruta y esa huella "
                f"({published.decision_id})",
                relative,
            )
    moment = utc_now()
    made = Decision(
        decision_id=f"decision-{moment:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}",
        decision=decision,
        ruta=relative,
        huella=digest,
        motivo=reason,
        acta=acta_relative,
        acta_sha256=acta_record.sha256,
        commit_codigo=commit,
        responsable=responsible,
        decidido_en=moment,
    )
    publish_decision(workspace, made)
    report = load_workspace(
        workspace,
        LoadOptions(kinds=frozenset({"decision"}), repository=repository),
        database=database,
    )
    return made.decision_id, report


# --- fichas y pruebas de respaldos (C1.8) -----------------------------------------------------


def backup_card(dump: Path) -> Ficha:
    """``bd ficha``: escribe la ficha de un respaldo que ya existe (campo por campo)."""
    return ficha_de_archivo(dump)


def test_backup(dump: Path) -> BackupTest:
    """``bd probar-respaldo``: restaura el respaldo en una base temporal y compara su huella."""
    return probar_respaldo(dump)
