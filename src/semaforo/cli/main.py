"""Interfaz de línea de comandos: ``python -m semaforo``.

Solo traduce argumentos y resultados; la lógica vive en ``app`` (ADR01). La salida estándar lleva
siempre un JSON: quien la consuma debe leer su estado, no solo el código de salida (diseño
técnico, «Errores y códigos de salida»). La salida de error lleva un resumen para la persona.

Comandos:

- ``doctor``: diagnóstico del entorno (versiones, permisos y capacidad) para una carpeta de
  trabajo (DEV01).
- ``case receive``: recibe una simulación (copia, inventario, auditoría, corrida base y registro).
- ``case publish-report``: copia el informe público de una recepción verificada a
  ``docs/recepcion``.
- ``case compare``: muestra qué cambió entre dos recepciones.
- ``simulate run``: ejecuta una carpeta de entradas de SUMO y publica la corrida (DEV07). Códigos
  de salida: 0 exitosa; 2 entradas inválidas; 3 SUMO ausente; 4 fallida, tiempo agotado o
  cancelada; 5 integridad o ruta no permitida. Hay que leer ``status`` del JSON, no solo el código.
- ``runs verify``: revisa todas las carpetas publicadas del espacio de trabajo (0 íntegro, 5 algo
  alterado); con ``--run-id``, la cadena de esa corrida (0 completa, 5 alterada, 3 falta o cambió
  un eslabón) (DEV08).
- ``runs compare``: compara dos corridas y publica el reporte de réplica (0 al registrarlo, sea
  ``equivalent`` o ``different``: hay que leer ``status``) (DEV08).
- ``report case`` y ``report data``: publican el informe HTML del caso o de sus datos (DEV09). Un
  caso inválido también genera informe (0; hay que leer ``case_status``); un archivo que no se
  puede leer sale 2 o 5, y un reporte de calidad alterado o de otro caso, 5.
- ``scenarios generate``: genera un conjunto de escenarios controlados con sus llegadas y lo
  publica (DEV11). Códigos de salida: 0 publicado; 2 caso o especificación inválidos o
  ilegibles (no se publica nada, se listan todos los problemas); 5 ruta no permitida o conjunto
  ya existente.
- ``splits create`` y ``splits validate``: reparten las familias de un conjunto de escenarios en
  entrenamiento, validación y prueba, y lo publican congelado, o comprueban una partición ya
  publicada (DEV12). Códigos de salida: 0 correcto; 2 argumentos, conjunto, política o partición
  inválidos (se listan todos los problemas); 5 enlace, algo alterado o el conjunto ya tiene su
  partición.
- `bd iniciar`, `bd cargar`, `bd verificar`, `bd hito` y `bd respaldar`: la base de datos de
  consulta en PostgreSQL (DEV31). Códigos de salida: 0 correcto; 3 sin conexión con PostgreSQL;
  5 conflictos de carga, archivos que cambiaron o una base regenerada con otra huella. Una carga
  con unidades pendientes o no cargables termina en 0: hay que leer `counts` del JSON.
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from semaforo.app.bd_commands import (
    LoadReport,
    backup_database,
    initialize,
    load,
    load_exit_code,
    register_milestone,
    verify,
    verify_exit_code,
)
from semaforo.app.comparison import compare_receptions
from semaforo.app.exit_codes import INTERNAL_ERROR_EXIT, exit_code_for
from semaforo.app.integrity import (
    RunTrace,
    WorkspaceReport,
    trace_exit_code,
    trace_run,
    verify_workspace,
    workspace_exit_code,
)
from semaforo.app.issue_lines import issue_lines
from semaforo.app.reception import (
    DomainError,
    publish_public_report,
    receive_case,
)
from semaforo.app.replica import Tolerance, replicate
from semaforo.app.report_commands import report_case, report_data
from semaforo.app.scenario_commands import MAX_SEED, generate_scenario_set
from semaforo.app.simulate import RunReport, run_prepared
from semaforo.app.split_commands import create_split_set, validate_split_set
from semaforo.cli.doctor import configure_doctor, run_doctor, summary


def _positive_seconds(text: str) -> float:
    """Segundos mayores que cero para ``--wall-timeout``."""
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"no es un número: {text!r}") from error
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError("debe ser un número de segundos mayor que cero")
    return value


def _positive_number(text: str) -> float:
    """Número mayor que cero para ``--tolerance``."""
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"no es un número: {text!r}") from error
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError("debe ser un número mayor que cero")
    return value


def _master_seed(text: str) -> int:
    """Semilla maestra para ``--seed``: un entero de 0 a ``MAX_SEED``."""
    try:
        value = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"no es un entero: {text!r}") from error
    if not 0 <= value <= MAX_SEED:
        raise argparse.ArgumentTypeError(f"debe ser un entero de 0 a {MAX_SEED}")
    return value


def _add_experiment_commands(
    add_group: Callable[..., argparse.ArgumentParser],
) -> list[argparse.ArgumentParser]:
    """Los grupos ``scenarios`` (DEV11) y ``splits`` (DEV12); devuelve sus comandos."""
    scenarios = add_group("scenarios", help="escenarios controlados (DEV11)")
    scenario_actions = scenarios.add_subparsers(dest="action", required=True)
    generate = scenario_actions.add_parser(
        "generate", help="genera un conjunto de escenarios con sus llegadas y lo publica"
    )
    generate.add_argument("--case", type=Path, required=True, help="archivo case.json")
    generate.add_argument(
        "--spec", type=Path, required=True, help="especificación de escenarios (JSON)"
    )
    generate.add_argument(
        "--seed", type=_master_seed, required=True, help="semilla maestra (entero desde 0)"
    )
    splits = add_group("splits", help="particiones sin fuga de la prueba (DEV12)")
    split_actions = splits.add_subparsers(dest="action", required=True)
    create = split_actions.add_parser(
        "create", help="reparte las familias de un conjunto de escenarios y publica la partición"
    )
    create.add_argument(
        "--scenarios",
        type=Path,
        required=True,
        help="carpeta del conjunto (derivados/escenarios/<caso>/<fecha>_<huella>)",
    )
    create.add_argument(
        "--seed", type=_master_seed, required=True, help="semilla de la partición (entero desde 0)"
    )
    create.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="archivo JSON con las proporciones (por defecto, las provisionales 0.6/0.2/0.2)",
    )
    check = split_actions.add_parser(
        "validate", help="comprueba una partición publicada contra su conjunto de escenarios"
    )
    check.add_argument("--split", type=Path, required=True, help="carpeta de la partición")
    check.add_argument("--scenarios", type=Path, required=True, help="carpeta del conjunto")
    return [generate, create, check]


MILESTONE_KINDS = ("protocol_frozen", "split_frozen", "model_frozen", "test_opened")


def _add_database_commands(
    add_group: Callable[..., argparse.ArgumentParser],
) -> list[argparse.ArgumentParser]:
    """El grupo ``bd`` (DEV31 F3); devuelve sus comandos."""
    database = add_group("bd", help="base de datos de consulta en PostgreSQL (DEV31)")
    actions = database.add_subparsers(dest="action", required=True)
    start = actions.add_parser(
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
    load = actions.add_parser("cargar", help="carga los archivos publicados de datos/ en la base")
    load.add_argument(
        "--preliminar",
        action="store_true",
        help="carga escenarios sin partición congelada, marcados como preliminares",
    )
    load.add_argument(
        "--sueltas",
        action="store_true",
        help="carga como diagnóstico las corridas que ninguna búsqueda publicada usa",
    )
    load.add_argument(
        "--sin-metricas",
        action="store_true",
        help="carga las corridas exitosas sin métricas publicadas (sus métricas quedan vacías)",
    )
    check = actions.add_parser(
        "verificar", help="huella de contenido, archivos raíz y, si se pide, regeneración"
    )
    check.add_argument("--huellas", type=Path, default=None, help="escribe el archivo de huellas")
    check.add_argument(
        "--regenerar",
        action="store_true",
        help="regenera la base en una temporal y compara su huella (QA36)",
    )
    milestone = actions.add_parser("hito", help="registra un hito del procedimiento con su acta")
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
    backup = actions.add_parser("respaldar", help="respaldo de la base con pg_dump")
    backup.add_argument("--carpeta", type=Path, required=True, help="carpeta de los respaldos")
    for command in (load, check, milestone, backup):
        command.add_argument(
            "--base", default=None, help="base de datos (por defecto, la del servicio: semaforo)"
        )
    for command in (load, check, milestone):
        command.add_argument(
            "--repositorio",
            type=Path,
            default=Path(),
            help="carpeta del repositorio, para las actas de los hitos (por defecto, la actual)",
        )
    return [start, load, check, milestone, backup]


def build_parser() -> argparse.ArgumentParser:
    """Analizador de argumentos de ``python -m semaforo``."""
    parser = argparse.ArgumentParser(prog="python -m semaforo")
    groups = parser.add_subparsers(dest="group", required=True)
    doctor = groups.add_parser(
        "doctor", help="diagnóstico del entorno: versiones, permisos y capacidad (DEV01)"
    )
    configure_doctor(doctor)
    case = groups.add_parser("case", help="operaciones sobre el caso")
    actions = case.add_subparsers(dest="action", required=True)
    receive = actions.add_parser(
        "receive",
        help="recibe una simulación SUMO: copia, inventario, auditoría y corrida base (DEV00)",
    )
    receive.add_argument("--source", type=Path, required=True, help="carpeta de la simulación")
    receive.add_argument("--config", required=True, help=".sumocfg de entrada, relativo a --source")
    receive.add_argument("--case-id", required=True, help="identificador del caso")
    receive.add_argument(
        "--mode", choices=("base", "smoke"), default="base", help="tipo de corrida"
    )
    receive.add_argument("--sumo-bin", type=Path, default=None, help="SUMO; por defecto, SUMO_HOME")
    publish = actions.add_parser(
        "publish-report", help="copia el informe público de una recepción a docs/recepcion"
    )
    publish.add_argument("--reception-id", required=True, help="identificador de la recepción")
    publish.add_argument(
        "--destination",
        type=Path,
        default=Path("docs") / "recepcion",
        help="carpeta del informe (por defecto, docs/recepcion)",
    )
    compare = actions.add_parser("compare", help="qué cambió entre dos recepciones")
    compare.add_argument("--before", required=True, help="recepción anterior")
    compare.add_argument("--after", required=True, help="recepción posterior")
    simulate = groups.add_parser("simulate", help="ejecuta simulaciones de SUMO (DEV07)")
    simulate_actions = simulate.add_subparsers(dest="action", required=True)
    run = simulate_actions.add_parser(
        "run", help="ejecuta una carpeta de entradas y publica la corrida"
    )
    run.add_argument(
        "--inputs", type=Path, required=True, help="carpeta de entradas que publicó DEV06"
    )
    run.add_argument("--sumo-bin", type=Path, default=None, help="SUMO; por defecto, SUMO_HOME")
    run.add_argument(
        "--wall-timeout",
        type=_positive_seconds,
        default=None,
        help="tiempo real máximo en segundos (por defecto, 900)",
    )
    run.add_argument(
        "--retry-of", default=None, help="run_id de una corrida fallida, cancelada o interrumpida"
    )
    runs = groups.add_parser("runs", help="revisa y compara corridas publicadas (DEV08)")
    runs_actions = runs.add_subparsers(dest="action", required=True)
    verify = runs_actions.add_parser(
        "verify", help="revisa el espacio de trabajo, o la cadena de una corrida con --run-id"
    )
    verify.add_argument("--run-id", default=None, help="corrida cuya cadena se revisa")
    compare_runs = runs_actions.add_parser(
        "compare", help="compara dos corridas y publica el reporte de réplica"
    )
    compare_runs.add_argument("--run-a", required=True, help="primera corrida")
    compare_runs.add_argument("--run-b", required=True, help="segunda corrida")
    compare_runs.add_argument(
        "--tolerance",
        type=_positive_number,
        default=None,
        help="diferencia admitida en números con decimales, relativa y absoluta (por defecto 1e-9)",
    )
    report = groups.add_parser("report", help="informes HTML del caso y de los datos (DEV09)")
    report_actions = report.add_subparsers(dest="action", required=True)
    case_report = report_actions.add_parser("case", help="informe HTML del caso")
    case_report.add_argument("--case", type=Path, required=True, help="archivo case.json")
    data_report = report_actions.add_parser(
        "data", help="informe HTML de los datos, a partir de su reporte de calidad"
    )
    data_report.add_argument("--case", type=Path, required=True, help="archivo case.json")
    data_report.add_argument(
        "--quality-report",
        type=Path,
        required=True,
        help="carpeta del reporte de calidad (derivados/calidad/<caso>/<fecha>_<huella>)",
    )
    for command in (
        doctor,
        receive,
        publish,
        compare,
        run,
        verify,
        compare_runs,
        case_report,
        data_report,
        *_add_experiment_commands(groups.add_parser),
        *_add_database_commands(groups.add_parser),
    ):
        command.add_argument(
            "--workspace",
            type=Path,
            default=Path("datos"),
            help="espacio de trabajo (por defecto, datos)",
        )
        command.add_argument(
            "--debug", action="store_true", help="muestra la traza de un error interno"
        )
    return parser


def _emit(text: str) -> None:
    """Escribe ``text`` en la salida estándar en UTF-8, sea cual sea la consola."""
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    sys.stdout.flush()


def _say(text: str) -> None:
    sys.stderr.buffer.write(text.encode("utf-8") + b"\n")
    sys.stderr.flush()


def _error(code: str, message: str, field: str | None) -> str:
    report = {"status": "error", "code": code, "field": field, "message": message}
    return json.dumps(report, ensure_ascii=False, indent=2)


def _run_summary(report: RunReport) -> str:
    """Resumen para la persona de una corrida terminada."""
    lines = [f"Corrida {report.run_id}: {report.status}"]
    if report.error_message is not None:
        lines.append(f"Motivo: {report.error_code}: {report.error_message}")
    if report.recovered_interrupted:
        lines.append(f"Corridas caídas apartadas: {', '.join(report.recovered_interrupted)}")
    return "\n".join(lines)


def _with_exit(data: dict[str, object], code: int) -> str:
    return json.dumps({**data, "exit_code": code}, ensure_ascii=False, indent=2)


def _workspace_summary(report: WorkspaceReport) -> str:
    counts = report.counts
    lines = [
        f"Espacio de trabajo {report.status}: {counts['intact']} íntegras, {counts['altered']} "
        f"alteradas, {counts['incomplete']} incompletas, {counts['temporary']} temporales, "
        f"{counts['unknown']} desconocidas"
    ]
    lines += [
        f"ALTERADA {item.path}: {item.detail}" for item in report.items if item.status == "altered"
    ]
    return "\n".join(lines)


def _trace_summary(trace: RunTrace) -> str:
    lines = [f"Corrida {trace.run_id}: cadena {trace.status}"]
    lines += [f"[{link.status}] {link.kind}: {link.path or link.detail}" for link in trace.links]
    return "\n".join(lines)


def _runs(arguments: argparse.Namespace, workspace: Path) -> int:
    if arguments.action == "verify" and arguments.run_id is None:
        report = verify_workspace(workspace)
        code = workspace_exit_code(report)
        _emit(_with_exit(report.model_dump(mode="json"), code))
        _say(_workspace_summary(report))
        return code
    if arguments.action == "verify":
        trace = trace_run(workspace, str(arguments.run_id))
        code = trace_exit_code(trace)
        _emit(_with_exit(trace.model_dump(mode="json"), code))
        _say(_trace_summary(trace))
        return code
    tolerance = (
        None
        if arguments.tolerance is None
        else Tolerance(relative=arguments.tolerance, absolute=arguments.tolerance)
    )
    report, folder = replicate(
        workspace, str(arguments.run_a), str(arguments.run_b), tolerance=tolerance
    )
    data: dict[str, object] = {
        "status": report.verdict,
        "path": folder.relative_to(workspace).as_posix(),
        "report": report.model_dump(mode="json"),
    }
    _emit(_with_exit(data, 0))
    reasons = "".join(f"\n- {reason}" for reason in report.reasons)
    _say(f"Réplica {report.run_a} y {report.run_b}: {report.verdict}{reasons}")
    return 0


CASE_STATES = {"valid": "válido", "valid_with_warnings": "válido con avisos", "invalid": "inválido"}


def _report(arguments: argparse.Namespace, workspace: Path) -> int:
    if arguments.action == "case":
        result = report_case(workspace, Path(arguments.case))
    else:
        result = report_data(workspace, Path(arguments.case), Path(arguments.quality_report))
    _emit(_with_exit(result.model_dump(mode="json"), 0))
    _say(f"Informe de {result.kind} publicado: {(workspace / result.index).resolve()}")
    _say(f"Estado del caso {result.case_id}: {CASE_STATES[result.case_status]}")
    return 0


def _scenarios(arguments: argparse.Namespace, workspace: Path) -> int:
    result = generate_scenario_set(
        workspace, Path(arguments.case), Path(arguments.spec), int(arguments.seed)
    )
    _emit(_with_exit(result.model_dump(mode="json"), 0))
    _say(f"Conjunto de escenarios publicado: {(workspace / result.folder).resolve()}")
    _say(
        f"{result.scenarios} escenarios en {result.families} familias; "
        f"{result.vehicles} vehículos en total"
    )
    return 0


def _splits(arguments: argparse.Namespace, workspace: Path) -> int:
    if arguments.action == "create":
        policy = None if arguments.policy is None else Path(arguments.policy)
        result = create_split_set(workspace, Path(arguments.scenarios), int(arguments.seed), policy)
        _emit(_with_exit(result.model_dump(mode="json"), 0))
        _say(f"Partición publicada: {(workspace / str(result.folder)).resolve()}")
    else:
        result = validate_split_set(Path(arguments.split), Path(arguments.scenarios))
        _emit(_with_exit(result.model_dump(mode="json"), 0))
        _say(f"La partición {result.split_id} es válida")
    note = " (proporciones provisionales: DEC07 pendiente)" if result.provisional else ""
    _say(
        "Grupos: "
        + ", ".join(f"{name} {count}" for name, count in result.groups.items())
        + "; escenarios: "
        + ", ".join(f"{name} {count}" for name, count in result.scenarios.items())
        + note
    )
    return 0


def _case(arguments: argparse.Namespace, workspace: Path) -> int:
    if arguments.action == "receive":
        record = receive_case(
            Path(arguments.source),
            str(arguments.config),
            workspace,
            case_id=str(arguments.case_id),
            mode="smoke" if arguments.mode == "smoke" else "base",
            sumo=None if arguments.sumo_bin is None else Path(arguments.sumo_bin),
        )
        _emit(record.model_dump_json(indent=2))
        _say(
            f"Recepción {record.reception_id}: {record.proposed_status} "
            f"(corrida base {record.base_run.status})"
        )
        return record.exit_code
    if arguments.action == "publish-report":
        target = publish_public_report(
            workspace, str(arguments.reception_id), Path(arguments.destination)
        )
        report = {
            "status": "published",
            "reception_id": arguments.reception_id,
            "path": target.as_posix(),
        }
        _emit(json.dumps(report, ensure_ascii=False, indent=2))
        _say(f"Informe publicado en {target.as_posix()}")
        return 0
    comparison = compare_receptions(workspace, str(arguments.before), str(arguments.after))
    _emit(comparison.model_dump_json(indent=2))
    _say(f"{len(comparison.changes)} cambios entre {comparison.before} y {comparison.after}")
    return 0


VERIFY_WORDS = {"intact": "íntegra", "changed": "con cambios"}
STATUS_WORDS = {
    "loaded": "cargadas",
    "already": "ya estaban",
    "pending": "pendientes",
    "rejected": "rechazadas",
    "not_loadable": "no cargables",
}


def _load_summary(report: LoadReport) -> str:
    counts = ", ".join(f"{report.counts[k]} {word}" for k, word in STATUS_WORDS.items())
    lines = [f"Carga {report.carga_id}: {report.status}. Unidades: {counts}."]
    if report.content_sha256:
        lines.append(f"Huella de contenido: {report.content_sha256}")
    reasons: dict[str, int] = {}
    for unit in report.units:
        if unit.status in ("pending", "rejected", "not_loadable"):
            reason = f"{STATUS_WORDS[unit.status]}: {unit.detail}"
            reasons[reason] = reasons.get(reason, 0) + 1
    lines += [f"- {count} {reason}" for reason, count in sorted(reasons.items())]
    lines += [f"Nota: {note}" for note in report.notes]
    return "\n".join(lines)


def _database(arguments: argparse.Namespace, workspace: Path) -> int:
    action = arguments.action
    if action == "iniciar":
        installed = initialize(Path(arguments.carpeta_datos), str(arguments.superusuario))
        _emit(_with_exit(installed.model_dump(mode="json"), 0))
        _say(
            f"PostgreSQL {installed.server_version} listo: base {installed.database}, "
            f"esquema {installed.schema_version_installed}"
        )
        return 0
    if action == "cargar":
        report = load(
            workspace,
            preliminary=bool(arguments.preliminar),
            loose_runs=bool(arguments.sueltas),
            without_metrics=bool(arguments.sin_metricas),
            repository=Path(arguments.repositorio),
            database=arguments.base,
        )
        code = load_exit_code(report)
        _emit(_with_exit(report.model_dump(mode="json"), code))
        _say(_load_summary(report))
        return code
    if action == "verificar":
        verified = verify(
            workspace,
            Path(arguments.repositorio),
            fingerprints=None if arguments.huellas is None else Path(arguments.huellas),
            regenerate=bool(arguments.regenerar),
            database=arguments.base,
        )
        code = verify_exit_code(verified)
        _emit(_with_exit(verified.model_dump(mode="json"), code))
        _say(
            f"Base {VERIFY_WORDS[verified.status]}: huella {verified.content_sha256}; "
            f"{verified.roots_checked} archivos raíz revisados, "
            f"{len(verified.roots_changed)} cambiaron"
            + (
                ""
                if verified.regenerated_equal is None
                else f"; regenerada {'igual' if verified.regenerated_equal else 'DISTINTA'}"
            )
        )
        return code
    if action == "hito":
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
        _emit(_with_exit({"hito_id": hito_id, "carga": report.model_dump(mode="json")}, code))
        _say(f"Hito {hito_id} registrado.\n{_load_summary(report)}")
        return code
    saved = backup_database(Path(arguments.carpeta), database=arguments.base)
    _emit(_with_exit(saved.model_dump(mode="json"), 0))
    _say(f"Respaldo {saved.file} ({saved.size_bytes} bytes), huella {saved.sha256}")
    return 0


COMMAND_GROUPS = {
    "report": _report,
    "scenarios": _scenarios,
    "splits": _splits,
    "runs": _runs,
    "bd": _database,
}


def _run(arguments: argparse.Namespace) -> int:
    workspace = Path(arguments.workspace)
    handler = COMMAND_GROUPS.get(arguments.group)
    if handler is not None:
        return handler(arguments, workspace)
    if arguments.group == "doctor":
        sumo = None if arguments.sumo_bin is None else Path(arguments.sumo_bin)
        report = run_doctor(workspace, sumo)
        _emit(report.model_dump_json(indent=2))
        _say(summary(report))
        return report.exit_code
    if arguments.group == "simulate":
        report = run_prepared(
            Path(arguments.inputs),
            workspace,
            sumo=None if arguments.sumo_bin is None else Path(arguments.sumo_bin),
            wall_timeout_s=arguments.wall_timeout,
            retry_of=None if arguments.retry_of is None else str(arguments.retry_of),
        )
        _emit(report.model_dump_json(indent=2))
        _say(_run_summary(report))
        return report.exit_code
    return _case(arguments, workspace)


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la CLI y devuelve el código de salida."""
    arguments = build_parser().parse_args(argv)
    try:
        return _run(arguments)
    except DomainError as error:
        _emit(_error(error.code.value, error.message, error.field))
        _say(f"Error {error.code.value}: {error.message}")
        for line in issue_lines(error):
            _say(line)
        return exit_code_for(error.code)
    except Exception:
        if arguments.debug:
            raise
        _emit(_error("INTERNAL", "error interno; repita con --debug para ver el detalle", None))
        _say("Error interno; repita con --debug para ver el detalle.")
        return INTERNAL_ERROR_EXIT
