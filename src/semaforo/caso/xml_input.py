"""Lectura segura de archivos XML de SUMO, comprimidos o no.

Los archivos de una simulación son externos y por tanto no confiables: se descomprimen con un
límite de tamaño (contra bombas de compresión) y se leen con ``defusedxml``, sin DTD ni
entidades. Los errores solo llevan el nombre del archivo, nunca su ruta.
"""

import gzip
import math
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from xml.etree.ElementTree import Element, ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from semaforo.caso.errors import CasoError, ErrorCode
from semaforo.trazabilidad.fs import Readable, read_at_most

GZIP_MAGIC = b"\x1f\x8b"


class _TooLargeError(Exception):
    """Se leyó más del tope."""


class _Capped:
    """Envuelve un flujo y falla si se lee más de ``limit`` bytes."""

    def __init__(self, stream: Readable, limit: int) -> None:
        self._stream = stream
        self._left = limit

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._stream.read(size)
        self._left -= len(chunk)
        if self._left < 0:
            raise _TooLargeError
        return chunk


def invalid(message: str, field: str) -> CasoError:
    """Error de entrada (``INPUT_SCHEMA``) sobre ``field``."""
    return CasoError(ErrorCode.INPUT_SCHEMA, message, field)


def read_bounded(path: Path, max_bytes: int) -> bytes:
    """Contenido de ``path``, descomprimido si es gzip (por contenido, no por nombre).

    Nunca lee más de ``max_bytes`` + 1 bytes descomprimidos.
    """
    try:
        with path.open("rb") as handle:
            compressed = handle.read(len(GZIP_MAGIC)) == GZIP_MAGIC
            handle.seek(0)
            source = gzip.GzipFile(fileobj=handle) if compressed else handle
            data = read_at_most(source, max_bytes + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise invalid(f"no se puede leer el archivo ({type(error).__name__})", path.name) from error
    if len(data) > max_bytes:
        raise invalid(f"el archivo supera el límite de {max_bytes} bytes", path.name)
    return data


def stream_parse[T](path: Path, max_bytes: int, parse: Callable[[Readable, str], T]) -> T:
    """Aplica ``parse(flujo, nombre)`` a ``path`` leído en flujo, sin cargarlo entero.

    El flujo se descomprime si es gzip (por contenido) y falla si se lee más de ``max_bytes``
    descomprimidos. ``parse`` debe usar ``defusedxml`` sin DTD. Los errores de lectura, de tamaño
    y de XML se convierten en ``INPUT_SCHEMA`` con solo el nombre del archivo; los de dominio que
    lance ``parse`` pasan tal cual.
    """
    name = path.name
    try:
        with path.open("rb") as handle:
            compressed = handle.read(len(GZIP_MAGIC)) == GZIP_MAGIC
            handle.seek(0)
            stream: BinaryIO | gzip.GzipFile = (
                gzip.GzipFile(fileobj=handle) if compressed else handle
            )
            return parse(_Capped(stream, max_bytes), name)
    except _TooLargeError:
        raise invalid(f"el archivo supera el límite de {max_bytes} bytes", name) from None
    except (DefusedXmlException, SyntaxError) as error:
        raise invalid(
            f"{name}: no es un XML válido o seguro ({type(error).__name__})", name
        ) from error
    except (OSError, EOFError, zlib.error) as error:
        raise invalid(f"no se puede leer el archivo ({type(error).__name__})", name) from error


def parse_root(path: Path, max_bytes: int, roots: frozenset[str], what: str) -> Element:
    """Raíz XML de ``path``, que debe ser una de ``roots``. ``what`` nombra el tipo de archivo."""
    data = read_bounded(path, max_bytes)
    try:
        root = fromstring(data, forbid_dtd=True)
    except (DefusedXmlException, ParseError) as error:
        raise invalid(
            f"{what}: no es un XML válido o seguro ({type(error).__name__})", path.name
        ) from error
    if root.tag not in roots:
        raise invalid(f"{what}: la raíz <{root.tag}> no es la esperada", path.name)
    return root


def required(element: Element, name: str) -> str:
    """Valor del atributo ``name``; ``INPUT_SCHEMA`` si falta."""
    value = element.get(name)
    if value is None:
        raise invalid(f"falta el atributo {name} en <{element.tag}>", f"{element.tag}.{name}")
    return value


def to_number(element: Element, name: str, text: str) -> float:
    """``text`` como número finito; ``INPUT_SCHEMA`` si no lo es."""
    try:
        value = float(text)
    except ValueError as error:
        raise invalid(
            f"{name} no es un número en <{element.tag}>", f"{element.tag}.{name}"
        ) from error
    if not math.isfinite(value):
        raise invalid(f"{name} no es finito en <{element.tag}>", f"{element.tag}.{name}")
    return value


def number(element: Element, name: str) -> float:
    """Atributo numérico obligatorio."""
    return to_number(element, name, required(element, name))


def optional_number(element: Element, name: str) -> float | None:
    """Atributo numérico opcional: None si falta."""
    text = element.get(name)
    return None if text is None else to_number(element, name, text)


def integer(element: Element, name: str) -> int:
    """Atributo entero obligatorio."""
    text = required(element, name)
    try:
        return int(text)
    except ValueError as error:
        raise invalid(
            f"{name} no es un entero en <{element.tag}>", f"{element.tag}.{name}"
        ) from error
