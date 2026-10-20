"""Identificadores por contenido."""

import re
from collections.abc import Iterable

from semaforo.trazabilidad.hashing import sha256_bytes

_SHA256_HEX = re.compile(r"[a-f0-9]{64}")
_LINE_BREAKING_CHARACTERS = ("\t", "\n", "\r")


def content_id(entries: Iterable[tuple[str, str]]) -> str:
    """Identificador por contenido de un conjunto de archivos (ADR09).

    Es el SHA-256 de una línea por archivo, ``<ruta relativa>\\t<sha256>\\n``, ordenadas por ruta
    (orden de puntos de código Unicode). No depende del orden en que se entreguen los archivos:
    el mismo contenido da siempre el mismo identificador, y cualquier cambio de ruta o de
    contenido lo cambia.

    Args:
        entries: pares (ruta relativa, SHA-256 hexadecimal en minúsculas), sin rutas repetidas.

    Raises:
        ValueError: si no hay archivos, si una ruta se repite, está vacía o contiene tabulador o
            salto de línea (romperían el formato de línea), o si un hash no es SHA-256 válido.
    """
    items = sorted(entries)
    if not items:
        raise ValueError("el conjunto de archivos está vacío")
    seen: set[str] = set()
    lines: list[str] = []
    for path, digest in items:
        if not path or any(character in path for character in _LINE_BREAKING_CHARACTERS):
            raise ValueError(f"ruta no válida para el identificador: {path!r}")
        if path in seen:
            raise ValueError(f"ruta duplicada: {path!r}")
        if not _SHA256_HEX.fullmatch(digest):
            raise ValueError(f"sha256 no válido para {path!r}: {digest!r}")
        seen.add(path)
        lines.append(f"{path}\t{digest}\n")
    return sha256_bytes("".join(lines).encode("utf-8"))
