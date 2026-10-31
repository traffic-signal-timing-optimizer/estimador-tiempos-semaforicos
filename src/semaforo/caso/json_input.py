"""Lectura segura de archivos JSON de entrada (escenario, rutas y tipos de vehículo; DEV06 F2).

Los archivos los prepara el equipo y se tratan como no confiables: se leen con un límite de
tamaño, sin seguir enlaces, en UTF-8 (con o sin BOM), sin claves repetidas y sin las constantes
``NaN`` e ``Infinity`` que Python acepta y JSON no. Los errores solo llevan el nombre del archivo,
nunca su ruta.
"""

import json
from pathlib import Path
from typing import Any, NoReturn

from semaforo.caso.errors import CasoError, ErrorCode

__all__ = ["MAX_JSON_BYTES", "read_json"]

MAX_JSON_BYTES = 4 * 1024 * 1024
UTF8_BOM = b"\xef\xbb\xbf"


class _RepeatedKeyError(ValueError):
    """Una clave aparece dos veces en el mismo objeto."""


def _object_without_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _RepeatedKeyError(key)
        result[key] = value
    return result


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(name)


def _invalid(message: str, field: str) -> CasoError:
    return CasoError(ErrorCode.INPUT_SCHEMA, message, field)


def read_json(path: Path, what: str, max_bytes: int = MAX_JSON_BYTES) -> object:
    """Contenido JSON de ``path``. ``what`` nombra el archivo en los mensajes (``rutas``…).

    Raises:
        CasoError: PATH_NOT_ALLOWED si es un enlace o una unión; INPUT_SCHEMA si no existe, no es
            un archivo, supera ``max_bytes``, no está en UTF-8 o no es JSON válido.
    """
    if path.is_symlink() or path.is_junction():
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED, f"{what}: el archivo es un enlace o una unión", path.name
        )
    if not path.is_file():
        raise _invalid(f"{what}: no existe el archivo", path.name)
    try:
        with path.open("rb") as handle:
            content = handle.read(max_bytes + 1)
    except OSError as error:
        raise _invalid(f"{what}: no se pudo leer ({type(error).__name__})", path.name) from error
    if len(content) > max_bytes:
        raise _invalid(f"{what}: el archivo supera el límite de {max_bytes} bytes", path.name)
    try:
        text = content.removeprefix(UTF8_BOM).decode("utf-8")
    except UnicodeDecodeError:
        raise _invalid(f"{what}: el archivo no está en UTF-8", path.name) from None
    try:
        return json.loads(
            text, object_pairs_hook=_object_without_repeats, parse_constant=_reject_constant
        )
    except _RepeatedKeyError as error:
        raise _invalid(
            f"{what}: la clave {error.args[0]!r} aparece más de una vez en un objeto", path.name
        ) from None
    except json.JSONDecodeError as error:
        raise _invalid(
            f"{what}: no es JSON válido (línea {error.lineno}, columna {error.colno}): {error.msg}",
            path.name,
        ) from None
    except RecursionError:
        raise _invalid(f"{what}: el JSON está demasiado anidado", path.name) from None
    except ValueError as error:
        raise _invalid(f"{what}: contiene {error.args[0]}, que JSON no admite", path.name) from None
