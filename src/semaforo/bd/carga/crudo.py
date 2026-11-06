"""Lectura con tipos de JSON sin modelo propio (trazas, coberturas, tramos) (DEV31 F3).

Algunos archivos publicados no tienen un modelo de lectura en el proyecto (``traza.json``,
``cobertura.json``, ``tramos.json``). Estas funciones toman un valor ya decodificado y lo
devuelven con su tipo, o fallan con ``CargaError`` diciendo dónde.
"""

import json
from typing import cast

from semaforo.bd.carga.modelo import CargaError
from semaforo.dominio.errors import ErrorCode

__all__ = [
    "boolean",
    "integer",
    "items",
    "loads",
    "mapping",
    "number",
    "optional_integer",
    "optional_number",
    "optional_text",
    "text",
]


def _bad(message: str, where: str) -> CargaError:
    return CargaError(ErrorCode.INPUT_SCHEMA, message, where)


def loads(data: bytes, where: str) -> object:
    """El JSON de ``data``. Raises: CargaError si no es UTF-8 o JSON válido."""
    try:
        return cast(object, json.loads(data.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise _bad(f"no es JSON válido ({type(error).__name__})", where) from error


def mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _bad("se esperaba un objeto", where)
    raw = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in raw):
        raise _bad("las claves deben ser textos", where)
    return cast(dict[str, object], raw)


def items(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise _bad("se esperaba una lista", where)
    return cast(list[object], value)


def text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise _bad("se esperaba un texto", where)
    return value


def optional_text(value: object, where: str) -> str | None:
    return None if value is None else text(value, where)


def integer(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("se esperaba un entero", where)
    return value


def optional_integer(value: object, where: str) -> int | None:
    return None if value is None else integer(value, where)


def number(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _bad("se esperaba un número", where)
    return float(value)


def optional_number(value: object, where: str) -> float | None:
    return None if value is None else number(value, where)


def boolean(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise _bad("se esperaba verdadero o falso", where)
    return value
