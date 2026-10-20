"""Validación de rutas relativas dentro de una carpeta: manifiestos, copias y ejecuciones."""

from pathlib import PureWindowsPath

_LINE_BREAKING_CHARACTERS = "\t\n\r"


def is_absolute_like(text: str) -> bool:
    """Indica si ``text`` parece una ruta absoluta, con sintaxis de Windows o de POSIX.

    Incluye letras de unidad (``C:\\x``, ``C:/x``), rutas UNC y rutas relativas a una unidad
    (``C:x``), que también escapan de la carpeta de trabajo.
    """
    path = PureWindowsPath(text)
    return bool(path.drive or path.root)


def check_relative_path(value: str) -> str:
    """Devuelve ``value`` si es una ruta relativa POSIX que no sale de su carpeta.

    Raises:
        ValueError: si está vacía, es absoluta, usa ``\\``, contiene tabuladores o saltos de
            línea, o tiene tramos vacíos, ``.`` o ``..``.
    """
    if not value or is_absolute_like(value) or "\\" in value:
        raise ValueError(f"la ruta debe ser relativa y usar '/': {value!r}")
    if any(character in value for character in _LINE_BREAKING_CHARACTERS):
        raise ValueError(f"la ruta no puede contener tabuladores ni saltos de línea: {value!r}")
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError(f"la ruta no puede salir de la carpeta ni tener tramos vacíos: {value!r}")
    return value
