"""Lectura y validación del archivo de un caso (DEV02).

Lee el JSON del caso con límites de seguridad y lo valida con las reglas de
``semaforo.dominio.case``. No ejecuta nada del archivo: solo lo interpreta como datos (diseño
técnico, «Fronteras de confianza y controles»).

- CASE-S04: el archivo pesa 1 MiB como máximo. Se leen a lo sumo ``MAX_CASE_BYTES + 1`` bytes, así
  que un archivo enorme no se carga entero.
- El archivo es UTF-8, con o sin marca de orden de bytes (BOM): PowerShell 5.1 la escribe.
- Se rechazan NaN, infinito y claves repetidas, que JSON admitiría y harían ambiguo el caso.
- Un enlace simbólico o una unión no se sigue: PATH_NOT_ALLOWED.

Un archivo ausente o que no es un archivo da INPUT_SCHEMA con ``CasoError``. Un contenido que no
cumple el contrato da ``CaseInvalidError``, con todos sus problemas.
"""

import json
from pathlib import Path
from typing import Any, NoReturn

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.dominio.case import (
    SIZE_RULE,
    STRUCTURE_RULE,
    Case,
    CaseInvalidError,
    CaseIssue,
)
from semaforo.dominio.case_rules import accept_case

__all__ = ["MAX_CASE_BYTES", "read_case"]

MAX_CASE_BYTES = 1024 * 1024
FIELD = "case"
UTF8_BOM = b"\xef\xbb\xbf"


class _RepeatedKeyError(ValueError):
    """Una clave aparece dos veces en el mismo objeto JSON."""


def _object_without_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _RepeatedKeyError(key)
        result[key] = value
    return result


def _reject_constant(name: str) -> NoReturn:
    """``json`` acepta NaN, Infinity y -Infinity por defecto; el caso no."""
    raise ValueError(name)


def _issue(message: str, rule_id: str = STRUCTURE_RULE) -> CaseInvalidError:
    return CaseInvalidError([CaseIssue(rule_id, None, message)])


def _read_bytes(path: Path) -> bytes:
    if path.is_symlink() or path.is_junction():
        raise CasoError(
            ErrorCode.PATH_NOT_ALLOWED, "el archivo del caso es un enlace o una unión", FIELD
        )
    if not path.exists():
        raise CasoError(ErrorCode.INPUT_SCHEMA, "no existe el archivo del caso", FIELD)
    if not path.is_file():
        raise CasoError(ErrorCode.INPUT_SCHEMA, "la ruta del caso no es un archivo", FIELD)
    try:
        with path.open("rb") as handle:
            return handle.read(MAX_CASE_BYTES + 1)
    except OSError as error:
        raise CasoError(
            ErrorCode.INPUT_SCHEMA,
            f"no se pudo leer el archivo del caso ({type(error).__name__})",
            FIELD,
        ) from error


def _parse_json(content: bytes) -> object:
    """Contenido del JSON, o ``CaseInvalidError`` si no se puede interpretar."""
    try:
        text = content.removeprefix(UTF8_BOM).decode("utf-8")
    except UnicodeDecodeError:
        raise _issue("el archivo no está en UTF-8") from None
    try:
        return json.loads(
            text, object_pairs_hook=_object_without_repeats, parse_constant=_reject_constant
        )
    except _RepeatedKeyError as error:
        raise _issue(f"la clave {error.args[0]!r} aparece más de una vez en un objeto") from None
    except json.JSONDecodeError as error:
        raise _issue(
            f"el archivo no es JSON válido (línea {error.lineno}, columna {error.colno}): "
            f"{error.msg}"
        ) from None
    except RecursionError:
        raise _issue("el JSON está demasiado anidado") from None
    except ValueError as error:
        raise _issue(
            f"el archivo contiene {error.args[0]}, que JSON permite pero el caso no"
        ) from None


def read_case(path: Path) -> Case:
    """Lee y valida el archivo del caso.

    Raises:
        CasoError: PATH_NOT_ALLOWED si la ruta es un enlace o una unión; INPUT_SCHEMA si no existe,
            no es un archivo o no se puede leer.
        CaseInvalidError: si el archivo supera ``MAX_CASE_BYTES`` (CASE-S04), no es JSON o UTF-8
            válido, no cumple el contrato (CASE-S01 a S03) o es incoherente (CASE-C01 a C13).
    """
    content = _read_bytes(path)
    if len(content) > MAX_CASE_BYTES:
        raise _issue(f"el archivo pesa más de {MAX_CASE_BYTES} bytes", SIZE_RULE)
    return accept_case(_parse_json(content))
