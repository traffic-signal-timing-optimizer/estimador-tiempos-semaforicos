"""``bd evidencia``: la evidencia de la base en una carpeta que el auditor puede repetir (C3.5).

Une, en un solo comando y sin escribir nada en la base:

- **verificar**: huella de contenido, archivos raíz y reglas instaladas contra la referencia de git;
- **red**: dónde escucha PostgreSQL y qué reglas de acceso admiten equipos de fuera de la laptop;
- **conciliar**: la base contra los archivos de ``datos/`` (conteos, demora y cola recalculadas);
- **cobertura**: lo publicado frente a lo cargado, en los dos sentidos (sale de la conciliación);
- **barrido**: todas las tablas y vistas, como lector y como panel (``bd.barrido``);
- **respaldo**: restaura un respaldo en una base temporal y compara su huella (``probar_respaldo``).

Cada ejecución publica una carpeta **nueva** ``<datos>/reportes/bd/<fecha>/`` de solo lectura, con
un informe por sección, un resumen para la persona y un ``manifiesto.json`` con la huella de cada
archivo. Nunca sobrescribe. El resultado general es el peor de las secciones:
0 todo coincide; 5 algo difiere o está incompleto; 6 algo no se pudo comprobar.
"""

from pathlib import Path
from typing import Literal

from semaforo.app.bd_commands import (
    BackupTest,
    ReconcileReport,
    VerifyReport,
    backup_test_exit_code,
    reconcile_database,
    reconcile_exit_code,
    test_backup,
    verify,
    verify_exit_code,
)
from semaforo.bd.barrido import SweepReport, sweep, sweep_exit_code
from semaforo.bd.conexion import ADMIN, DATABASE, BdError, connect
from semaforo.bd.esquema import installed_version
from semaforo.bd.respaldo import latest_backup
from semaforo.dominio.base_model import FrozenModel
from semaforo.dominio.errors import ErrorCode
from semaforo.simulacion.herramientas import git_output
from semaforo.trazabilidad.fs import publish_files
from semaforo.trazabilidad.hashing import sha256_bytes
from semaforo.trazabilidad.store import utc_now

__all__ = [
    "EvidenceReport",
    "Section",
    "collect_evidence",
    "resolve_backup",
    "select_backup",
    "summary",
]

REPORTS = ("reportes", "bd")
INTEGRITY_EXIT = 5
INCONCLUSIVE_EXIT = 6
STATES: dict[int, Literal["ok", "difiere", "no_concluyente"]] = {
    0: "ok",
    INTEGRITY_EXIT: "difiere",
    INCONCLUSIVE_EXIT: "no_concluyente",
}
WORDS = {"ok": "coincide", "difiere": "DIFIERE", "no_concluyente": "no concluyente"}


class Section(FrozenModel):
    """El resultado de una de las comprobaciones."""

    name: str
    file: str | None
    state: Literal["ok", "difiere", "no_concluyente"]
    exit_code: int
    detail: str | None


class EvidenceReport(FrozenModel):
    """El manifiesto de la evidencia: qué se comprobó, con qué resultado y dónde está."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["ok", "difiere", "no_concluyente"]
    exit_code: int
    generated_at: str
    database: str | None
    version_esquema: str | None
    content_sha256: str | None
    rules_sha256: str | None
    commit: str | None
    repository_clean: bool | None
    folder: str
    sections: list[Section]
    files: dict[str, str]


def select_backup(folder: Path, version: str | None) -> Path:
    """El respaldo más reciente de la versión vigente del esquema (paso 1 de ``probar-respaldo``).

    Raises:
        BdError: INPUT_SCHEMA si no se conoce la versión vigente o no hay un respaldo suyo.
    """
    if version is None:
        raise BdError(ErrorCode.INPUT_SCHEMA, "no se conoce la versión del esquema vigente", "base")
    chosen = latest_backup(folder, version)
    if chosen is None:
        raise BdError(
            ErrorCode.INPUT_SCHEMA,
            f"no hay un respaldo de la versión {version} en la carpeta",
            "respaldos",
        )
    return chosen


def resolve_backup(backup: Path | None, backups: Path | None, database: str | None) -> Path:
    """El respaldo a probar: el indicado, o el más reciente de la versión vigente de ``database``.

    Raises:
        BdError: INPUT_SCHEMA si no se indicó nada o no hay un respaldo de la versión vigente.
    """
    if backup is not None:
        return backup
    if backups is None:
        raise BdError(ErrorCode.INPUT_SCHEMA, "indique --respaldo o --respaldos", "respaldo")
    with connect(ADMIN, database=database) as connection:
        version = installed_version(connection)
    return select_backup(backups, version)


def _section(name: str, file: str | None, code: int, detail: str | None = None) -> Section:
    return Section(name=name, file=file, state=STATES[code], exit_code=code, detail=detail)


def _network_section(verified: VerifyReport) -> Section:
    network = verified.network
    if network is None:
        return _section("red", None, INCONCLUSIVE_EXIT, "la verificación no midió la red")
    code = {"aislada": 0, "abierta": INTEGRITY_EXIT}.get(network.verdict, INCONCLUSIVE_EXIT)
    detail = (
        f"escucha en {network.listen_addresses}; reglas ({network.rules_source}): {network.verdict}"
    )
    return _section("red", "verificar.json", code, detail)


def _coverage_section(reconciled: ReconcileReport) -> Section:
    coverage = reconciled.coverage
    if reconciled.status == "inconclusive":
        return _section("cobertura", "conciliar.json", INCONCLUSIVE_EXIT, reconciled.reason)
    complete = not (coverage.missing or coverage.excluded_pending or coverage.surplus)
    detail = (
        f"{coverage.expected} publicadas: {coverage.loaded} cargadas, "
        f"{coverage.excluded_with_decision} con decisión, {coverage.excluded_pending} pendientes, "
        f"{coverage.missing} faltan, {coverage.surplus} sobran"
    )
    return _section("cobertura", "conciliar.json", 0 if complete else INTEGRITY_EXIT, detail)


def _sweep_section(report: SweepReport) -> Section:
    detail = (
        f"{report.relations} relaciones; {report.hidden_scenarios} escenarios cegados, "
        f"{report.marks} marcas buscadas"
    )
    if report.note:
        detail = f"{detail}. {report.note}"
    return _section("barrido", "barrido.json", sweep_exit_code(report), detail)


def _backup_section(tested: BackupTest | None, reason: str | None) -> Section:
    if tested is None:
        return _section("respaldo", None, INCONCLUSIVE_EXIT, reason)
    content = tested.contenido
    detail = (
        f"{tested.archivo}: archivo {tested.sha256.estado}, restauración "
        f"{tested.restauracion.estado}, contenido {content.estado}"
    )
    return _section("respaldo", "respaldo.json", backup_test_exit_code(tested), detail)


def summary(report: EvidenceReport) -> str:
    """El resumen de la evidencia para la persona."""
    lines = [
        f"Evidencia de la base: {WORDS[report.status]} (código {report.exit_code}).",
        f"Esquema {report.version_esquema}; contenido {report.content_sha256}; "
        f"reglas {report.rules_sha256}.",
        f"Commit del repositorio: {report.commit or 'sin commit'}"
        f"{' (con cambios sin confirmar)' if report.repository_clean is False else ''}.",
        "",
    ]
    lines += [
        f"- {section.name}: {WORDS[section.state]}"
        + (f". {section.detail}" if section.detail else "")
        for section in report.sections
    ]
    return "\n".join(lines) + "\n"


def collect_evidence(  # noqa: PLR0913  (cada opción es de solo palabra clave)
    workspace: Path,
    repository: Path,
    *,
    backup: Path | None = None,
    backups: Path | None = None,
    recompute: bool = True,
    hba: Path | None = None,
    database: str | None = None,
) -> EvidenceReport:
    """Junta la evidencia de la base y la publica en ``<workspace>/reportes/bd/<fecha>/``.

    ``backup`` es el respaldo a probar; si se omite, se busca el más reciente de la versión vigente
    en ``backups``. Sin ninguno de los dos, la sección de respaldo queda «no concluyente».

    Raises:
        BdError: si no hay conexión con la base.
        FileExistsError: si ya se publicó una evidencia con el mismo nombre (el mismo segundo).
    """
    verified = verify(workspace, repository, network=True, hba=hba, database=database)
    reconciled = reconcile_database(
        workspace, repository=repository, recompute=recompute, database=database
    )
    swept = sweep(database)
    tested: BackupTest | None = None
    reason: str | None = None
    chosen = backup
    if chosen is None and backups is not None:
        try:
            chosen = select_backup(backups, verified.database_schema)
        except BdError as error:
            reason = error.message
    if chosen is not None:
        tested = test_backup(chosen)
    elif reason is None:
        reason = "no se indicó un respaldo ni una carpeta de respaldos"

    sections = [
        _section("verificar", "verificar.json", verify_exit_code(verified), verified.reason),
        _network_section(verified),
        _section("conciliar", "conciliar.json", reconcile_exit_code(reconciled), reconciled.reason),
        _coverage_section(reconciled),
        _sweep_section(swept),
        _backup_section(tested, reason),
    ]
    codes = {section.exit_code for section in sections}
    code = INTEGRITY_EXIT if INTEGRITY_EXIT in codes else INCONCLUSIVE_EXIT if codes - {0} else 0

    now = utc_now()
    name = f"{now:%Y%m%dT%H%M%SZ}"
    status_output = git_output(repository, "status", "--porcelain", "--untracked-files=no")
    contents: dict[str, bytes] = {
        "verificar.json": verified.model_dump_json(indent=2).encode(),
        "conciliar.json": reconciled.model_dump_json(indent=2).encode(),
        "barrido.json": swept.model_dump_json(indent=2).encode(),
    }
    if tested is not None:
        contents["respaldo.json"] = tested.model_dump_json(indent=2).encode()
    report = EvidenceReport(
        status=STATES[code],
        exit_code=code,
        generated_at=now.isoformat(),
        database=database or DATABASE,
        version_esquema=verified.database_schema,
        content_sha256=verified.content_sha256,
        rules_sha256=verified.rules_sha256,
        commit=git_output(repository, "rev-parse", "HEAD"),
        repository_clean=None if status_output is None else status_output == "",
        folder="/".join((*REPORTS, name)),
        sections=sections,
        files={},
    )
    contents["resumen.txt"] = summary(report).encode()
    final = report.model_copy(
        update={"files": {file: sha256_bytes(data) for file, data in sorted(contents.items())}}
    )
    contents["manifiesto.json"] = final.model_dump_json(indent=2).encode()
    publish_files(workspace.joinpath(*REPORTS, name), contents)
    return final
