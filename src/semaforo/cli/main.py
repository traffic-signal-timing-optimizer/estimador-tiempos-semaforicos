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
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from semaforo.app.comparison import compare_receptions
from semaforo.app.exit_codes import INTERNAL_ERROR_EXIT, exit_code_for
from semaforo.app.reception import (
    DomainError,
    publish_public_report,
    receive_case,
)
from semaforo.app.simulate import RunReport, run_prepared
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
    for command in (doctor, receive, publish, compare, run):
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


def _run(arguments: argparse.Namespace) -> int:
    workspace = Path(arguments.workspace)
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


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la CLI y devuelve el código de salida."""
    arguments = build_parser().parse_args(argv)
    try:
        return _run(arguments)
    except DomainError as error:
        _emit(_error(error.code.value, error.message, error.field))
        _say(f"Error {error.code.value}: {error.message}")
        return exit_code_for(error.code)
    except Exception:
        if arguments.debug:
            raise
        _emit(_error("INTERNAL", "error interno; repita con --debug para ver el detalle", None))
        _say("Error interno; repita con --debug para ver el detalle.")
        return INTERNAL_ERROR_EXIT
