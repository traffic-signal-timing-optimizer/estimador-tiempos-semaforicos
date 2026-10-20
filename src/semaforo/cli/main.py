"""Interfaz de línea de comandos: ``python -m semaforo``.

Solo traduce argumentos y resultados; la lógica vive en ``app`` (ADR01). La salida estándar lleva
siempre un JSON: quien la consuma debe leer su estado, no solo el código de salida (diseño
técnico, «Errores y códigos de salida»). La salida de error lleva un resumen para la persona.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from semaforo.app.reception import DomainError, exit_code_for, receive_case

INTERNAL_ERROR_EXIT = 1


def build_parser() -> argparse.ArgumentParser:
    """Analizador de argumentos de ``python -m semaforo``."""
    parser = argparse.ArgumentParser(prog="python -m semaforo")
    groups = parser.add_subparsers(dest="group", required=True)
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
        "--workspace",
        type=Path,
        default=Path("datos"),
        help="espacio de trabajo (por defecto, datos)",
    )
    receive.add_argument(
        "--mode", choices=("base", "smoke"), default="base", help="tipo de corrida"
    )
    receive.add_argument("--sumo-bin", type=Path, default=None, help="SUMO; por defecto, SUMO_HOME")
    receive.add_argument(
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


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la CLI y devuelve el código de salida."""
    arguments = build_parser().parse_args(argv)
    try:
        record = receive_case(
            Path(arguments.source),
            str(arguments.config),
            Path(arguments.workspace),
            case_id=str(arguments.case_id),
            mode="smoke" if arguments.mode == "smoke" else "base",
            sumo=None if arguments.sumo_bin is None else Path(arguments.sumo_bin),
        )
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
    _emit(record.model_dump_json(indent=2))
    _say(
        f"Recepción {record.reception_id}: {record.proposed_status} "
        f"(corrida base {record.base_run.status})"
    )
    return record.exit_code
