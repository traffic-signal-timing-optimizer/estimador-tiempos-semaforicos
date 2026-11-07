"""Cómo escribe la línea de comandos: el JSON en la salida estándar y el resumen en la de errores.

Todos los comandos escriben en UTF-8 sea cual sea la consola (Windows incluida) y agregan el código
de salida al JSON, para que quien lo lea (una persona, un guion o una auditoría) lo tenga completo.
"""

import json
import sys

__all__ = ["emit", "say", "with_exit"]


def emit(text: str) -> None:
    """Escribe ``text`` en la salida estándar en UTF-8, sea cual sea la consola."""
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    sys.stdout.flush()


def say(text: str) -> None:
    """Escribe ``text`` (el resumen para la persona) en la salida de errores en UTF-8."""
    sys.stderr.buffer.write(text.encode("utf-8") + b"\n")
    sys.stderr.flush()


def with_exit(data: dict[str, object], code: int) -> str:
    """El JSON de ``data`` con su código de salida."""
    return json.dumps({**data, "exit_code": code}, ensure_ascii=False, indent=2)
