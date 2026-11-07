"""Los comandos ``bd`` de la línea de comandos: base de datos de consulta en PostgreSQL (DEV31).

- ``iniciar``, ``cargar``, ``hito`` y ``respaldar`` (F3); ``metricas`` y ``conciliar`` (F4);
- ``verificar`` (solo lectura, con referencia de git), ``regenerar``, ``decidir``, ``ficha``,
  ``probar-respaldo`` y ``reconstruir`` (F4c).

Códigos de salida: 0 correcto; 3 sin conexión con PostgreSQL; 4 con errores aislados (métricas);
5 conflictos, algo que no coincide, está incompleto o cambió; 6 resultado no concluyente (una
carga en curso, una referencia de otra versión, algo sin comprobar). Una carga con unidades
pendientes o no cargables sin decisión termina en 5.
"""

import argparse
from collections.abc import Callable
from pathlib import Path

from semaforo.app.bd_commands import (
    DATABASE,
    BackupTest,
    Ficha,
    FichaCampo,
    LoadReport,
    MetricsReport,
    ReconcileReport,
    RegenerateReport,
    VerifyReport,
    backup_card,
    backup_database,
    backup_test_exit_code,
    initialize,
    load,
    load_exit_code,
    publish_metrics,
    reconcile_database,
    reconcile_exit_code,
    regenerate,
    regenerate_exit_code,
    register_decision,
    register_milestone,
    test_backup,
    verify,
    verify_exit_code,
)
from semaforo.app.bd_reconstruir import (
    Preparation,
    Step,
    SwitchReport,
    prepare_rebuild,
    switch_database,
)
from semaforo.cli.salida import emit, say, with_exit

__all__ = ["add_database_commands", "run_database"]

MILESTONE_KINDS = ("protocol_frozen", "split_frozen", "model_frozen", "test_opened")
DECISION_KINDS = ("accepted_risk", "discarded", "kept_existing", "new_version")
VERIFY_WORDS = {
    "intact": "íntegra",
    "changed": "con cambios",
    "inconclusive": "sin resultado concluyente",
}
STATUS_WORDS = {
    "loaded": "cargadas",
    "already": "ya estaban",
    "pending": "pendientes",
    "rejected": "rechazadas",
    "not_loadable": "no cargables",
    "excluded": "excluidas con decisión",
}
METRIC_WORDS = {
    "published": "publicadas",
    "already": "ya estaban",
    "skipped": "sin medir",
    "failed": "con error",
}
RECONCILE_WORDS = {
    "equal": "coincide con los archivos",
    "different": "NO coincide con los archivos",
    "incomplete": "está INCOMPLETA respecto de los archivos",
    "inconclusive": "no tiene un resultado concluyente",
}
FICHA_FIELDS = (
    "sha256",
    "version_esquema",
    "tablas",
    "huella_contenido",
    "carga_id",
    "commit_codigo",
)


# --- parser ----------------------------------------------------------------------------------


def _add_load_and_reconcile(
    add: Callable[..., argparse.ArgumentParser],
) -> list[argparse.ArgumentParser]:
    start = add(
        "iniciar", help="crea el espacio de tablas, los usuarios, la base y su esquema (una vez)"
    )
    start.add_argument(
        "--carpeta-datos",
        type=Path,
        required=True,
        help="carpeta vacía donde PostgreSQL guarda la base (por ejemplo D:\\pgdata\\semaforo)",
    )
    start.add_argument(
        "--superusuario",
        default="postgres",
        help="administrador del servicio (por defecto postgres)",
    )
    loader = add("cargar", help="carga los archivos publicados de datos/ en la base")
    loader.add_argument(
        "--preliminar",
        action="store_true",
        help="carga escenarios sin partición congelada, marcados como preliminares",
    )
    loader.add_argument(
        "--sueltas",
        action="store_true",
        help="carga como diagnóstico las corridas que ninguna búsqueda publicada usa",
    )
    loader.add_argument(
        "--sin-metricas",
        action="store_true",
        help="carga las corridas exitosas sin métricas publicadas (sus métricas quedan vacías)",
    )
    metrics = add(
        "metricas",
        help="calcula y publica las métricas que faltan, en carpetas nuevas de solo lectura",
    )
    metrics.add_argument(
        "--protocolo",
        default=None,
        help="protocolo con que medir las corridas sueltas cuya zona calza con varios",
    )
    reconcile = add(
        "conciliar",
        help="compara la base con los archivos: cobertura, conteos y demora recalculada (QA33)",
    )
    reconcile.add_argument(
        "--sin-recalcular",
        action="store_true",
        help="no vuelve a calcular las métricas (solo cobertura, archivos y conteos)",
    )
    return [start, loader, metrics, reconcile]


def _add_check_and_decide(
    add: Callable[..., argparse.ArgumentParser],
) -> list[argparse.ArgumentParser]:
    check = add(
        "verificar",
        help="solo lectura: huella de contenido, reglas instaladas y referencia de git",
    )
    check.add_argument("--huellas", type=Path, default=None, help="escribe el archivo de huellas")
    check.add_argument(
        "--referencia",
        type=Path,
        default=None,
        help="archivo de huellas contra el que comparar (por defecto, docs/bd/huellas.json en git)",
    )
    check.add_argument(
        "--sin-referencia",
        action="store_true",
        help="no compara con ninguna referencia (solo mide la base y los archivos raíz)",
    )
    check.add_argument(
        "--red", action="store_true", help="informa dónde escucha PostgreSQL y qué reglas admite"
    )
    check.add_argument(
        "--hba", type=Path, default=None, help="pg_hba.conf que analizar con --red (si no se lee)"
    )
    regen = add("regenerar", help="regenera la base en una temporal y compara su huella (QA36)")
    milestone = add("hito", help="registra un hito del procedimiento con su acta")
    milestone.add_argument("--tipo", choices=MILESTONE_KINDS, required=True, help="tipo de hito")
    milestone.add_argument(
        "--objeto", required=True, help="protocolo, partición, modelo o experimento del hito"
    )
    milestone.add_argument("--particion", default=None, help="partición (al abrir la prueba)")
    milestone.add_argument(
        "--acta", required=True, help="acta en el repositorio (ruta relativa, confirmada en git)"
    )
    milestone.add_argument("--responsable", required=True, help="quién registra el hito")
    milestone.add_argument("--notas", default=None, help="aclaraciones del acta")
    decide = add(
        "decidir", help="publica la decisión sobre un archivo excluido (por ruta y huella)"
    )
    decide.add_argument("--ruta", required=True, help="archivo excluido, relativo a datos/")
    decide.add_argument("--decision", choices=DECISION_KINDS, required=True, help="qué se decide")
    decide.add_argument("--motivo", required=True, help="por qué")
    decide.add_argument(
        "--acta", required=True, help="acta en el repositorio (ruta relativa, confirmada en git)"
    )
    decide.add_argument("--responsable", required=True, help="quién decide")
    return [check, regen, milestone, decide]


def _add_backups_and_rebuild(
    add: Callable[..., argparse.ArgumentParser],
) -> list[argparse.ArgumentParser]:
    backup = add(
        "respaldar", help="respaldo de la base con pg_dump, con su ficha, por versión del esquema"
    )
    backup.add_argument("--carpeta", type=Path, required=True, help="carpeta de los respaldos")
    card = add("ficha", help="escribe la ficha de un respaldo que ya existe")
    card.add_argument("--respaldo", type=Path, required=True, help="el archivo .dump")
    probe = add(
        "probar-respaldo",
        help="restaura un respaldo en una base temporal y compara su huella (la borra al terminar)",
    )
    probe.add_argument("--respaldo", type=Path, required=True, help="el archivo .dump")
    rebuild = add(
        "reconstruir", help="reconstruye la base con una candidata validada antes del cambio"
    )
    phases = rebuild.add_subparsers(dest="fase", required=True)
    prepare = phases.add_parser("preparar", help="crea y valida la candidata (P0 a P5 y P7)")
    prepare.add_argument("--respaldos", type=Path, required=True, help="carpeta de los respaldos")
    prepare.add_argument("--candidata", default=None, help="nombre de la candidata (semaforo_…)")
    prepare.add_argument("--referencia", type=Path, default=None, help="huellas de referencia")
    prepare.add_argument(
        "--sin-referencia", action="store_true", help="no compara la vigente con una referencia"
    )
    switch = phases.add_parser("cambiar", help="cambia la candidata por la vigente (P6 a P9)")
    switch.add_argument("--candidata", required=True, help="la candidata que preparó la fase 1")
    switch.add_argument(
        "--huella-aprobada", required=True, help="la huella de contenido que aprobó el PO (D11)"
    )
    switch.add_argument(
        "--pruebas-aprobadas",
        action="store_true",
        help="declara que las pruebas de cegado y de seguridad pasaron en la base desechable",
    )
    switch.add_argument(
        "--anterior", default=None, help="nombre de la vigente (semaforo_anterior_…)"
    )
    switch.add_argument(
        "--escribir-huellas", type=Path, default=None, help="escribe el archivo de huellas nuevo"
    )
    return [backup, card, probe, prepare, switch]


def add_database_commands(
    add_group: Callable[..., argparse.ArgumentParser],
) -> list[argparse.ArgumentParser]:
    """El grupo ``bd``; devuelve sus comandos (los que llevan opciones, uno por uno)."""
    database = add_group("bd", help="base de datos de consulta en PostgreSQL (DEV31)")
    actions = database.add_subparsers(dest="action", required=True)
    start, loader, metrics, reconcile = _add_load_and_reconcile(actions.add_parser)
    check, regen, milestone, decide = _add_check_and_decide(actions.add_parser)
    backup, card, probe, prepare, switch = _add_backups_and_rebuild(actions.add_parser)
    for command in (loader, check, regen, milestone, backup, reconcile, decide, prepare, switch):
        command.add_argument(
            "--base", default=None, help="base de datos (por defecto, la del servicio: semaforo)"
        )
    for command in (loader, check, regen, milestone, reconcile, decide, prepare, switch):
        command.add_argument(
            "--repositorio",
            type=Path,
            default=Path(),
            help="carpeta del repositorio, para las actas de los hitos (por defecto, la actual)",
        )
    return [
        start,
        loader,
        metrics,
        reconcile,
        check,
        regen,
        milestone,
        decide,
        backup,
        card,
        probe,
        prepare,
        switch,
    ]


# --- resúmenes para la persona ---------------------------------------------------------------


def _load_summary(report: LoadReport) -> str:
    counts = ", ".join(f"{report.counts.get(k, 0)} {word}" for k, word in STATUS_WORDS.items())
    lines = [f"Carga {report.carga_id}: {report.status}. Unidades: {counts}."]
    if report.content_sha256:
        lines.append(f"Huella de contenido: {report.content_sha256}")
    reasons: dict[str, int] = {}
    for unit in report.units:
        if unit.status in ("pending", "rejected", "not_loadable", "excluded"):
            reason = f"{STATUS_WORDS[unit.status]}: {unit.detail}"
            reasons[reason] = reasons.get(reason, 0) + 1
    lines += [f"- {count} {reason}" for reason, count in sorted(reasons.items())]
    lines += [f"Nota: {note}" for note in report.notes]
    return "\n".join(lines)


def _metrics_summary(report: MetricsReport) -> str:
    counts = ", ".join(f"{report.counts[k]} {word}" for k, word in METRIC_WORDS.items())
    lines = [f"Métricas de las corridas: {counts}."]
    reasons: dict[str, int] = {}
    for run in report.runs:
        if run.status in ("skipped", "failed"):
            reason = f"{METRIC_WORDS[run.status]}: {run.detail}"
            reasons[reason] = reasons.get(reason, 0) + 1
    lines += [f"- {count} {reason}" for reason, count in sorted(reasons.items())]
    return "\n".join(lines)


def _reconcile_summary(report: ReconcileReport) -> str:
    coverage = report.coverage
    lines = [
        f"La base {RECONCILE_WORDS[report.status]}: {report.files_checked} archivos, "
        f"{report.runs_checked} corridas ({report.runs_recomputed} recalculadas, "
        f"{report.runs_unverified} sin verificar), {report.differences_total} diferencias.",
        f"Cobertura de lo publicado ({coverage.expected}): {coverage.loaded} cargadas, "
        f"{coverage.excluded_with_decision} excluidas con decisión, "
        f"{coverage.excluded_pending} excluidas pendientes, {coverage.missing} faltan, "
        f"{coverage.surplus} sobran.",
    ]
    if report.reason:
        lines.append(f"Motivo: {report.reason}")
    lines += [f"- falta: {key}" for key in coverage.missing_keys[:10]]
    lines += [f"- excluida pendiente: {key}" for key in coverage.pending_keys[:10]]
    lines += [
        f"- {d.where}: {d.item}: base {d.database}, archivos {d.files}"
        for d in report.differences[:20]
    ]
    lines += [f"- no verificada {d.where}: {d.files}" for d in report.unverified[:10]]
    return "\n".join(lines)


def _verify_summary(report: VerifyReport) -> str:
    lines = [
        f"Base {VERIFY_WORDS[report.status]}: huella {report.content_sha256}; "
        f"{report.roots_checked} archivos raíz revisados, {len(report.roots_changed)} cambiaron."
    ]
    if report.reason:
        lines.append(f"Motivo: {report.reason}")
    if report.rules_sha256:
        lines.append(f"Reglas instaladas: {report.rules_sha256}")
    if report.reference is not None:
        lines.append(f"Referencia ({report.reference.source}): {report.reference.outcome}")
        lines += [
            f"- {d.item}: referencia {d.reference}, base {d.database}"
            for d in report.reference.differences[:10]
        ]
    if report.network is not None:
        lines.append(
            f"Red: escucha en {report.network.listen_addresses}; reglas "
            f"({report.network.rules_source}): {report.network.verdict}"
        )
        lines += [f"- {warning}" for warning in report.network.warnings]
        lines += [
            f"- regla que admite equipos externos: {rule}" for rule in report.network.remote_rules
        ]
    return "\n".join(lines)


def _regenerate_summary(report: RegenerateReport) -> str:
    words = {"same": "igual", "different": "DISTINTA", "inconclusive": "sin resultado concluyente"}
    text = f"Base regenerada: {words[report.status]}."
    return text if report.reason is None else f"{text} Motivo: {report.reason}"


def _ficha_summary(ficha: Ficha) -> str:
    lines = [f"Ficha del respaldo {ficha.archivo}:"]
    for name in FICHA_FIELDS:
        field: FichaCampo = getattr(ficha, name)
        shown = field.valor
        value = f"{len(shown)} tablas" if isinstance(shown, list) else shown
        lines.append(f"- {name}: {value} [{field.estado}; {field.fuente}]")
    return "\n".join(lines)


def _probe_summary(evidence: BackupTest) -> str:
    content = evidence.contenido
    lines = [
        f"Respaldo {evidence.archivo}: archivo {evidence.sha256.estado}, "
        f"restauración {evidence.restauracion.estado}, contenido {content.estado}.",
    ]
    for label, detail in (
        ("archivo", evidence.sha256.detalle),
        ("restauración", evidence.restauracion.detalle),
        ("contenido", content.detalle),
    ):
        if detail:
            lines.append(f"- {label}: {detail}")
    if content.huella_calculada:
        lines.append(
            f"- versión detectada {content.version_detectada}; huella calculada "
            f"{content.huella_calculada}; esperada {content.huella_esperada} "
            f"({content.procedencia})"
        )
    return "\n".join(lines)


def _steps_summary(steps: list[Step], header: str) -> str:
    lines = [header]
    for step in steps:
        detail = f" ({step.detalle})" if step.detalle else ""
        lines.append(f"- {step.paso} {step.nombre}: {step.resultado}{detail}")
    return "\N{LINE FEED}".join(lines)


# --- manejadores -----------------------------------------------------------------------------


def _initialize(arguments: argparse.Namespace, workspace: Path) -> int:
    del workspace
    installed = initialize(Path(arguments.carpeta_datos), str(arguments.superusuario))
    emit(with_exit(installed.model_dump(mode="json"), 0))
    say(
        f"PostgreSQL {installed.server_version} listo: base {installed.database}, "
        f"esquema {installed.schema_version_installed}"
    )
    return 0


def _load(arguments: argparse.Namespace, workspace: Path) -> int:
    report = load(
        workspace,
        preliminary=bool(arguments.preliminar),
        loose_runs=bool(arguments.sueltas),
        without_metrics=bool(arguments.sin_metricas),
        repository=Path(arguments.repositorio),
        database=arguments.base,
    )
    code = load_exit_code(report)
    emit(with_exit(report.model_dump(mode="json"), code))
    say(_load_summary(report))
    return code


def _verify(arguments: argparse.Namespace, workspace: Path) -> int:
    verified = verify(
        workspace,
        Path(arguments.repositorio),
        reference=None if arguments.referencia is None else Path(arguments.referencia),
        compare=not arguments.sin_referencia,
        fingerprints=None if arguments.huellas is None else Path(arguments.huellas),
        network=bool(arguments.red),
        hba=None if arguments.hba is None else Path(arguments.hba),
        database=arguments.base,
    )
    code = verify_exit_code(verified)
    emit(with_exit(verified.model_dump(mode="json"), code))
    say(_verify_summary(verified))
    return code


def _regenerate(arguments: argparse.Namespace, workspace: Path) -> int:
    report = regenerate(workspace, Path(arguments.repositorio), database=arguments.base)
    code = regenerate_exit_code(report)
    emit(with_exit(report.model_dump(mode="json"), code))
    say(_regenerate_summary(report))
    return code


def _milestone(arguments: argparse.Namespace, workspace: Path) -> int:
    hito_id, report = register_milestone(
        workspace,
        Path(arguments.repositorio),
        kind=arguments.tipo,
        target=str(arguments.objeto),
        acta=str(arguments.acta),
        responsible=str(arguments.responsable),
        partition=None if arguments.particion is None else str(arguments.particion),
        notes=None if arguments.notas is None else str(arguments.notas),
        database=arguments.base,
    )
    code = load_exit_code(report)
    emit(with_exit({"hito_id": hito_id, "carga": report.model_dump(mode="json")}, code))
    say(f"Hito {hito_id} registrado.\n{_load_summary(report)}")
    return code


def _decide(arguments: argparse.Namespace, workspace: Path) -> int:
    decision_id, report = register_decision(
        workspace,
        Path(arguments.repositorio),
        path=str(arguments.ruta),
        decision=arguments.decision,
        reason=str(arguments.motivo),
        acta=str(arguments.acta),
        responsible=str(arguments.responsable),
        database=arguments.base,
    )
    code = load_exit_code(report)
    emit(with_exit({"decision_id": decision_id, "carga": report.model_dump(mode="json")}, code))
    say(f"Decisión {decision_id} registrada.\n{_load_summary(report)}")
    return code


def _backup(arguments: argparse.Namespace, workspace: Path) -> int:
    del workspace
    saved = backup_database(Path(arguments.carpeta), database=arguments.base)
    emit(with_exit(saved.model_dump(mode="json"), 0))
    say(f"Respaldo {saved.file} ({saved.size_bytes} bytes), huella {saved.sha256}")
    return 0


def _card(arguments: argparse.Namespace, workspace: Path) -> int:
    del workspace
    ficha = backup_card(Path(arguments.respaldo))
    emit(with_exit(ficha.model_dump(mode="json"), 0))
    say(_ficha_summary(ficha))
    return 0


def _probe(arguments: argparse.Namespace, workspace: Path) -> int:
    del workspace
    evidence = test_backup(Path(arguments.respaldo))
    code = backup_test_exit_code(evidence)
    emit(with_exit(evidence.model_dump(mode="json"), code))
    say(_probe_summary(evidence))
    return code


def _metrics(arguments: argparse.Namespace, workspace: Path) -> int:
    published = publish_metrics(
        workspace, protocol_id=None if arguments.protocolo is None else str(arguments.protocolo)
    )
    code = 4 if published.counts["failed"] else 0
    emit(with_exit(published.model_dump(mode="json"), code))
    say(_metrics_summary(published))
    return code


def _reconcile(arguments: argparse.Namespace, workspace: Path) -> int:
    compared = reconcile_database(
        workspace,
        repository=Path(arguments.repositorio),
        recompute=not arguments.sin_recalcular,
        database=arguments.base,
    )
    code = reconcile_exit_code(compared)
    emit(with_exit(compared.model_dump(mode="json"), code))
    say(_reconcile_summary(compared))
    return code


def _rebuild(arguments: argparse.Namespace, workspace: Path) -> int:
    repository = Path(arguments.repositorio)
    database = arguments.base or DATABASE
    if arguments.fase == "preparar":
        prepared: Preparation = prepare_rebuild(
            workspace,
            repository,
            backups=Path(arguments.respaldos),
            database=database,
            candidate=arguments.candidata,
            reference=None if arguments.referencia is None else Path(arguments.referencia),
            compare=not arguments.sin_referencia,
        )
        code = 0 if prepared.status == "lista" else 5
        emit(with_exit(prepared.model_dump(mode="json"), code))
        header = (
            f"Candidata {prepared.candidate} lista. Huella de contenido a aprobar: "
            f"{prepared.content_sha256}"
            if prepared.status == "lista"
            else f"Reconstrucción detenida en {prepared.stopped_at}: {prepared.reason}"
        )
        say(_steps_summary(prepared.steps, header))
        return code
    switched: SwitchReport = switch_database(
        workspace,
        repository,
        candidate=str(arguments.candidata),
        approved_sha256=str(arguments.huella_aprobada),
        tests_approved=bool(arguments.pruebas_aprobadas),
        database=database,
        previous=arguments.anterior,
        fingerprints=None
        if arguments.escribir_huellas is None
        else Path(arguments.escribir_huellas),
    )
    code = 0 if switched.status == "cambiada" else 5
    emit(with_exit(switched.model_dump(mode="json"), code))
    header = (
        f"Base cambiada. La anterior quedó como {switched.previous} (no se borra)."
        if switched.status == "cambiada"
        else f"Cambio detenido: {switched.reason}"
    )
    say(_steps_summary(switched.steps, header))
    return code


HANDLERS: dict[str, Callable[[argparse.Namespace, Path], int]] = {
    "iniciar": _initialize,
    "cargar": _load,
    "verificar": _verify,
    "regenerar": _regenerate,
    "hito": _milestone,
    "decidir": _decide,
    "respaldar": _backup,
    "ficha": _card,
    "probar-respaldo": _probe,
    "metricas": _metrics,
    "conciliar": _reconcile,
    "reconstruir": _rebuild,
}


def run_database(arguments: argparse.Namespace, workspace: Path) -> int:
    """Ejecuta el comando ``bd`` pedido y devuelve su código de salida."""
    return HANDLERS[arguments.action](arguments, workspace)
